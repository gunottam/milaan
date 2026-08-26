"""Dataset construction. Clean data only — no breaks are injected here.

Every settlement is a whole payout: its transactions settle in their own cycle and
the bank credit equals the sum of their net contributions to the paise.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from datetime import timedelta

from core.fees import expected_fee
from core.models import BankLine, GatewayTxn, Order
from generator import config as cfg
from generator.narration import make_utr, render


@dataclass(frozen=True)
class Settlement:
    settlement_id: str
    utr: str
    cycle_date: str
    entity_ids: tuple[str, ...]
    bank_line_id: str


@dataclass(frozen=True)
class Dataset:
    txns: tuple[GatewayTxn, ...]
    bank_lines: tuple[BankLine, ...]
    orders: tuple[Order, ...]
    settlements: tuple[Settlement, ...]
    unrecoverable_narrations: int


def _method(rng: random.Random) -> str:
    names = [m for m, _ in cfg.METHOD_WEIGHTS]
    weights = [w for _, w in cfg.METHOD_WEIGHTS]
    return rng.choices(names, weights=weights)[0]


def _split_records(n_records: int, n_settlements: int, rng: random.Random) -> list[int]:
    """Transaction counts per settlement, summing to exactly `n_records`."""
    per = n_records // n_settlements
    counts = [per] * n_settlements
    for i in range(n_records - per * n_settlements):
        counts[i] += 1
    for _ in range(n_settlements):
        a, b = rng.randrange(n_settlements), rng.randrange(n_settlements)
        if counts[a] > 6:
            move = rng.randint(1, min(4, counts[a] - 6))
            counts[a] -= move
            counts[b] += move
    return counts


def _amount(rng: random.Random) -> tuple[int, str, bool]:
    """(amount_paise, method, international). Sticky prices are the §6.2 rate
    control for ambiguity: unjittered UPI, so nets collide exactly."""
    if rng.random() < cfg.STICKY_PRICE_RATE:
        return rng.choice(cfg.STICKY_PRICES), "upi", False
    method = _method(rng)
    base = rng.choice(cfg.PRICE_POINTS)
    amount = base + rng.randint(-cfg.JITTER_PAISE, cfg.JITTER_PAISE)
    return amount, method, method == "intl_card"


def _payment(entity_id: str, order_id: str, created: str, settled: str,
             settlement_id: str, utr: str, rng: random.Random) -> GatewayTxn:
    amount, method, international = _amount(rng)
    txn = GatewayTxn(
        entity_id=entity_id, type="payment", amount_paise=amount, method=method,
        created_at=created, settled_at=settled, settlement_id=settlement_id,
        settlement_utr=utr, order_id=order_id, international=international,
        card_network=rng.choice(cfg.CARD_NETWORKS)
        if method in ("card", "intl_card", "emi") else None,
        description=f"Payment for {order_id}",
        notes=f"channel={method}",
    )
    fee, tax, tds = expected_fee(txn)
    fx = None
    if international:
        fx = cfg.FX_RATE_MICROS + rng.randint(-250_000, 250_000)
    return replace(
        txn, fee_paise=fee, tax_paise=tax, tds_paise=tds,
        source_currency="USD" if international else None,
        source_amount_minor=amount * 1_000_000 // fx if fx else None,
        fx_rate_micros=fx,
    )


def build(seed: int, n_bank_lines: int, n_records: int, noise: str,
          window_days: int = cfg.SETTLEMENT_WINDOW_DAYS) -> Dataset:
    """One settlement per cycle, one bank line per settlement."""
    rng = random.Random(seed)
    profile = cfg.NOISE_PROFILES[noise]
    counts = _split_records(n_records, n_bank_lines, rng)
    spacing = cfg.cycle_spacing(window_days)

    txns: list[GatewayTxn] = []
    orders: list[Order] = []
    bank_lines: list[BankLine] = []
    settlements: list[Settlement] = []
    payments_by_id: dict[str, GatewayTxn] = {}
    refunded: dict[str, str] = {}
    balance = cfg.OPENING_BALANCE
    unrecoverable = 0

    for i, count in enumerate(counts):
        cycle = (cfg.EPOCH + timedelta(days=i * spacing)).isoformat()
        settled_at = f"{cycle}T{cfg.CYCLE_HOUR}+05:30"
        settlement_id = f"setl_{i:04d}"
        utr = make_utr(cfg.MERCHANT_BANK, cycle, i + 1)
        members: list[GatewayTxn] = []

        def add_payment() -> None:
            n = len(txns) + len(members)
            order_id = f"order_{n:05d}"
            created = (cfg.EPOCH + timedelta(days=i * spacing - rng.randint(0, 2))).isoformat()
            created += f"T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00+05:30"
            p = _payment(f"pay_{n:05d}", order_id, created, settled_at,
                         settlement_id, utr, rng)
            members.append(p)
            orders.append(Order(
                order_id=order_id, order_date=created[:10],
                customer_ref=f"cust_{rng.randrange(10 ** 5):05d}",
                gross_paise=p.amount_paise, currency="INR", status="paid",
                invoice_no=f"INV-2026-{n:05d}",
            ))

        n_refunds = min(count - 1, sum(rng.random() < cfg.REFUND_RATE for _ in range(count)))
        for _ in range(count - n_refunds):
            add_payment()

        # Refunds attach to a payment from an earlier cycle and stay small enough
        # that the settlement cannot net negative (that is NEGATIVE_SETTLEMENT,
        # a stage-4 break).
        cap = sum(p.net for p in members) // 4
        eligible = [p for p in payments_by_id.values()
                    if p.amount_paise <= cap and p.order_id not in refunded]
        for _ in range(n_refunds):
            if not eligible:
                add_payment()          # keep the record count exact
                continue
            parent = eligible.pop(rng.randrange(len(eligible)))
            n = len(txns) + len(members)
            full = rng.random() < 0.7
            amount = parent.amount_paise if full else parent.amount_paise // 2
            members.append(GatewayTxn(
                entity_id=f"rfnd_{n:05d}", type="refund", amount_paise=amount,
                method=parent.method,
                created_at=f"{cycle}T{rng.randint(0, 23):02d}:00:00+05:30",
                settled_at=settled_at, settlement_id=settlement_id,
                settlement_utr=utr, order_id=parent.order_id,
                payment_id=parent.entity_id,
                description=f"Refund against {parent.entity_id}",
                notes="reason=customer_request",
            ))
            refunded[parent.order_id] = "refunded" if full else "partially_refunded"

        credit = sum(t.net for t in members)
        assert credit > 0, f"{settlement_id} nets {credit}; clean data must not"
        narration, recoverable = render(utr, profile, rng)
        unrecoverable += not recoverable
        balance += credit
        bank_line_id = f"bl_{i:04d}"
        bank_lines.append(BankLine(
            bank_line_id=bank_line_id, txn_date=cycle, value_date=cycle,
            narration=narration,
            ref_no=utr if rng.random() < profile["ref_no"] else None,
            debit_paise=0, credit_paise=credit, balance_paise=balance,
        ))
        settlements.append(Settlement(
            settlement_id=settlement_id, utr=utr, cycle_date=cycle,
            entity_ids=tuple(t.entity_id for t in members),
            bank_line_id=bank_line_id,
        ))
        txns.extend(members)
        payments_by_id.update({t.entity_id: t for t in members if t.type == "payment"})

    orders = [replace(o, status=refunded.get(o.order_id, o.status)) for o in orders]
    return Dataset(tuple(txns), tuple(bank_lines), tuple(orders),
                   tuple(settlements), unrecoverable)
