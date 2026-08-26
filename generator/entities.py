"""Dataset construction. Clean data only — no breaks are injected here.

Every settlement is a whole payout: its transactions settle in their own cycle and
the bank credit equals the sum of their net contributions to the paise.

A cycle usually hosts one payout. `SHARED_WINDOW_RATE` of them host two, splitting
the cycle's record budget rather than adding to it, which is what makes a decoy —
and therefore ambiguity — possible at all. See `generator/config.py`.
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
    shared_cycles: tuple[str, ...] = ()


def _method(rng: random.Random) -> str:
    names = [m for m, _ in cfg.METHOD_WEIGHTS]
    weights = [w for _, w in cfg.METHOD_WEIGHTS]
    return rng.choices(names, weights=weights)[0]


def _split_records(n_records: int, n_settlements: int, rng: random.Random) -> list[int]:
    """Transaction counts per cycle, summing to exactly `n_records`."""
    per = n_records // n_settlements
    counts = [per] * n_settlements
    for i in range(n_records - per * n_settlements):
        counts[i] += 1
    for _ in range(n_settlements):
        a, b = rng.randrange(n_settlements), rng.randrange(n_settlements)
        if counts[a] > 6 and counts[b] < cfg.MAX_PAYOUT_ITEMS:
            move = rng.randint(1, min(4, counts[a] - 6, cfg.MAX_PAYOUT_ITEMS - counts[b]))
            counts[a] -= move
            counts[b] += move
    return counts


def _amount(rng: random.Random) -> tuple[int, str, bool]:
    """(amount_paise, method, international). Sticky prices carry no jitter, so two
    of them have identical net contributions."""
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


def build(seed: int, n_payouts: int, n_records: int, noise: str,
          window_days: int = cfg.SETTLEMENT_WINDOW_DAYS) -> Dataset:
    """One payout per cycle, plus a second small payout in shared windows."""
    rng = random.Random(seed)
    profile = cfg.NOISE_PROFILES[noise]
    spacing = cfg.cycle_spacing(window_days)

    n_shared = min(int(n_payouts * cfg.SHARED_WINDOW_RATE), n_payouts // 2)
    n_cycles = n_payouts - n_shared
    counts = _split_records(n_records, n_cycles, rng)
    shared = set(rng.sample(range(n_cycles), n_shared))

    txns: list[GatewayTxn] = []
    orders: list[Order] = []
    bank_lines: list[BankLine] = []
    settlements: list[Settlement] = []
    payments_by_id: dict[str, GatewayTxn] = {}
    refunded: dict[str, str] = {}
    unrecoverable = 0
    payout = 0

    def make_payout(cycle: str, cycle_day: int, count: int, seq: int,
                    force_cross: bool) -> None:
        """One settlement, its transactions, and the bank line that pays it out."""
        nonlocal payout, unrecoverable
        settled_at = f"{cycle}T{cfg.CYCLE_HOUR}+05:30"
        settlement_id = f"setl_{payout:04d}"
        bank_line_id = f"bl_{payout:04d}"
        utr = make_utr(cfg.MERCHANT_BANK, cycle, seq)
        members: list[GatewayTxn] = []

        def add_payment() -> None:
            n = len(txns) + len(members)
            order_id = f"order_{n:05d}"
            created = (cfg.EPOCH + timedelta(days=cycle_day - rng.randint(0, 2))).isoformat()
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

        n_cross = 1 if force_cross else (
            rng.randint(1, cfg.CROSS_CYCLE_MAX_ITEMS)
            if rng.random() < cfg.CROSS_CYCLE_REFUND_RATE else 0)
        n_refunds = max(0, min(count - 1 - n_cross,
                               sum(rng.random() < cfg.REFUND_RATE for _ in range(count))))
        for _ in range(count - n_refunds - n_cross):
            add_payment()

        def parents(cap: int, sticky_first: bool) -> list[GatewayTxn]:
            pool = [p for p in payments_by_id.values()
                    if p.amount_paise <= cap and p.order_id not in refunded]
            if sticky_first:
                catalogue = [p for p in pool if p.amount_paise in cfg.STICKY_PRICES]
                if catalogue:
                    return catalogue
            return pool

        # Refunds against a payment from an earlier cycle, small enough that the
        # payout cannot net negative (that is NEGATIVE_SETTLEMENT, an injector).
        cap = sum(p.net for p in members) // 4
        for _ in range(n_refunds):
            eligible = parents(cap, False)
            if not eligible:
                add_payment()
                continue
            parent = eligible[rng.randrange(len(eligible))]
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

        # Cross-cycle refunds: netted out of this payout, never tagged to the
        # settlement batch. They settle inside the payout's own window, so C2 can
        # reach them, and G3 accepts them as §9.4's "1-2 strays".
        for _ in range(n_cross):
            eligible = parents(cap, cfg.PREFER_CATALOGUE_REFUND_PARENT)
            if not eligible:
                add_payment()
                continue
            parent = eligible[rng.randrange(len(eligible))]
            n = len(txns) + len(members)
            settled_day = cycle_day - rng.randint(0, window_days)
            members.append(GatewayTxn(
                entity_id=f"rfnd_{n:05d}", type="refund",
                amount_paise=parent.amount_paise, method=parent.method,
                created_at=f"{(cfg.EPOCH + timedelta(days=settled_day - 1)).isoformat()}"
                           f"T{rng.randint(0, 23):02d}:00:00+05:30",
                settled_at=f"{(cfg.EPOCH + timedelta(days=settled_day)).isoformat()}"
                           f"T{cfg.CYCLE_HOUR}+05:30",
                settlement_id=None, settlement_utr=None,
                order_id=parent.order_id, payment_id=parent.entity_id,
                description=f"Cross-cycle refund against {parent.entity_id}",
                notes="reason=prior_cycle",
            ))
            refunded[parent.order_id] = "refunded"

        credit = sum(t.net for t in members)
        assert credit > 0, f"{settlement_id} nets {credit}; clean data must not"
        narration, recoverable = render(utr, profile, rng)
        unrecoverable += not recoverable
        bank_lines.append(BankLine(
            bank_line_id=bank_line_id, txn_date=cycle, value_date=cycle,
            narration=narration,
            ref_no=utr if rng.random() < profile["ref_no"] else None,
            debit_paise=0, credit_paise=credit, balance_paise=0,
        ))
        settlements.append(Settlement(
            settlement_id=settlement_id, utr=utr, cycle_date=cycle,
            entity_ids=tuple(t.entity_id for t in members),
            bank_line_id=bank_line_id,
        ))
        txns.extend(members)
        payments_by_id.update({t.entity_id: t for t in members if t.type == "payment"})
        payout += 1

    shared_dates: list[str] = []
    for i, count in enumerate(counts):
        cycle_day = i * spacing
        cycle = (cfg.EPOCH + timedelta(days=cycle_day)).isoformat()
        if i not in shared:
            make_payout(cycle, cycle_day, count, i * 2 + 1, force_cross=False)
            continue
        # Two payouts, one window. Split the cycle's budget so the combined pool
        # stays under C2_MAX_POOL; force a cross-cycle stray into each, since the
        # equal-net pair is the only ambiguity G3 permits.
        second = min(cfg.SECOND_PAYOUT_MAX_ITEMS, max(3, count // 4))
        make_payout(cycle, cycle_day, count - second, i * 2 + 1, force_cross=True)
        make_payout(cycle, cycle_day, second, i * 2 + 2, force_cross=True)
        shared_dates.append(cycle)

    balance = cfg.OPENING_BALANCE
    stamped: list[BankLine] = []
    for line in sorted(bank_lines, key=lambda x: (x.value_date, x.bank_line_id)):
        balance += line.credit_paise - line.debit_paise
        stamped.append(replace(line, balance_paise=balance))

    orders = [replace(o, status=refunded.get(o.order_id, o.status)) for o in orders]
    return Dataset(tuple(txns), tuple(stamped), tuple(orders), tuple(settlements),
                   unrecoverable, tuple(shared_dates))
