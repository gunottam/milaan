"""Domain model. §3 of the spec.

Value types are frozen. Money is `int` paise everywhere (I1). Timestamps are
IST-aware ISO8601 strings, dates are IST calendar dates as `YYYY-MM-DD` — both
stored as text so a CSV round-trip is lossless.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from core.money import Paise, in_window, ist_date, window_key

T = TypeVar("T")

GATEWAY_COLUMNS = (
    "entity_id", "type", "created_at", "settled_at", "settlement_id",
    "settlement_utr", "order_id", "payment_id", "method", "card_network",
    "international", "amount_paise", "fee_paise", "tax_paise", "tds_paise",
    "source_currency", "source_amount_minor", "fx_rate_micros", "on_hold",
    "settled", "description", "notes",
)
BANK_COLUMNS = (
    "bank_line_id", "txn_date", "value_date", "narration", "ref_no",
    "debit_paise", "credit_paise", "balance_paise",
)
ORDER_COLUMNS = (
    "order_id", "order_date", "customer_ref", "gross_paise", "currency",
    "status", "invoice_no",
)


@dataclass(frozen=True)
class GatewayTxn:
    """A row of `gateway_txns.csv`. `amount_paise` is always positive — the sign
    of the contribution comes from `type`."""

    entity_id: str
    type: str
    amount_paise: Paise
    method: str = "upi"
    created_at: str = ""
    settled_at: str | None = None
    settlement_id: str | None = None
    settlement_utr: str | None = None
    order_id: str | None = None
    payment_id: str | None = None
    card_network: str | None = None
    international: bool = False
    fee_paise: Paise = 0
    tax_paise: Paise = 0
    tds_paise: Paise = 0
    source_currency: str | None = None
    source_amount_minor: int | None = None
    fx_rate_micros: int | None = None
    on_hold: bool = False
    settled: bool = True
    description: str = ""
    notes: str = ""

    @property
    def net(self) -> Paise:
        return net_contribution(self)


@dataclass(frozen=True)
class BankLine:
    """A row of `bank_statement.csv`. `balance_paise` is presentational only."""

    bank_line_id: str
    txn_date: str
    value_date: str
    narration: str
    ref_no: str | None
    debit_paise: Paise
    credit_paise: Paise
    balance_paise: Paise


@dataclass(frozen=True)
class Order:
    """A row of `orders.csv` — the ERP side, used for the §3.3 tie-out."""

    order_id: str
    order_date: str
    customer_ref: str
    gross_paise: Paise
    currency: str
    status: str
    invoice_no: str | None


def net_contribution(t: GatewayTxn) -> Paise:
    """What the transaction contributes to a payout. Never falls through — an
    unknown type is a generator bug and must crash loudly."""
    match t.type:
        case "payment":
            return t.amount_paise - t.fee_paise - t.tax_paise - t.tds_paise
        case "refund" | "dispute" | "transfer" | "adjustment_debit":
            return -t.amount_paise
        case "adjustment_credit":
            return t.amount_paise
        case _:
            raise ValueError(f"unknown txn type: {t.type}")


def target(line: BankLine) -> Paise:
    """Signed target (finding 8.1) — negative for debit lines."""
    return line.credit_paise - line.debit_paise


def settlement_members(txns: Iterable[GatewayTxn]) -> dict[str, tuple[str, ...]]:
    """`settlement_id -> its entity ids`, sorted. Membership is read straight out
    of the gateway export, so every tier that needs a whole group — A1-A3, B1, C1 —
    reads it the same way rather than keeping its own copy."""
    members: dict[str, list[str]] = defaultdict(list)
    for txn in txns:
        if txn.settlement_id is not None:
            members[txn.settlement_id].append(txn.entity_id)
    return {sid: tuple(sorted(ids)) for sid, ids in members.items()}


def window_pool(line: BankLine, txns: Iterable[GatewayTxn], window_days: int,
                claimed: frozenset[str] = frozenset()) -> list[GatewayTxn]:
    """Transactions whose `settled_at` IST date lies in
    `[value_date − window_days, value_date]`. Never reads `on_hold` (§9.3)."""
    anchor = window_key(line.value_date, line.txn_date)
    return [t for t in txns
            if t.settled_at and t.entity_id not in claimed
            and in_window(ist_date(t.settled_at), anchor, window_days)]


_BOOL_COLUMNS = frozenset({"international", "on_hold", "settled"})
_INT_COLUMNS = frozenset({"amount_paise", "fee_paise", "tax_paise", "tds_paise",
                          "debit_paise", "credit_paise", "balance_paise",
                          "gross_paise", "source_amount_minor", "fx_rate_micros"})
_TEXT_COLUMNS = frozenset({"description", "notes", "narration"})


def _parse(column: str, raw: str) -> object:
    """Invert `generator.generate._cell`. Empty means null, except where the
    column is free text and empty means empty."""
    if column in _BOOL_COLUMNS:
        return raw == "true"
    if column in _INT_COLUMNS:
        return int(raw) if raw else None
    return raw if raw or column in _TEXT_COLUMNS else None


def read_csv(path: Path, cls: type[T]) -> list[T]:
    """Read one of the three emitted CSVs back into its frozen value type."""
    with path.open(newline="", encoding="utf-8") as fh:
        return [cls(**{k: _parse(k, v) for k, v in row.items()})
                for row in csv.DictReader(fh)]
