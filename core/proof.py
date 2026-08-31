"""The arithmetic a verdict carries. §7.2's `Proof`, rendered by §13's proof strip.

I8: no tier returns a match without a balanced proof. The proof is not decoration —
it is the sum `check()` actually performed, kept instead of thrown away, so a human
reading a match sees the same figures the gate did.

Aggregation only. `fmt_inr` and the double rule are the renderer's business.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from core.models import GatewayTxn
from core.money import Paise

# type -> (label, sign). Deductions carry their sign here so the rows add up to the
# total without the renderer knowing what a refund is.
_KINDS = (
    ("payment", "payments captured", 1),
    ("adjustment_credit", "adjustments credited", 1),
    ("refund", "refunds netted", -1),
    ("dispute", "disputes debited", -1),
    ("transfer", "route transfers", -1),
    ("adjustment_debit", "adjustments debited", -1),
)
_DEDUCTIONS = (
    ("fee_paise", "MDR"),
    ("tax_paise", "GST @ 18% on MDR"),
    ("tds_paise", "TDS @ 0.10% u/s 194-O"),
)


@dataclass(frozen=True)
class Proof:
    """`rows` are `(label, count, amount_paise)` and sum to `total_paise`."""

    bank_line_id: str
    rows: tuple[tuple[str, int, Paise], ...]
    total_paise: Paise
    target_paise: Paise
    delta_paise: Paise


def build_proof(bank_line_id: str, composition: Iterable[str],
                txns: Mapping[str, GatewayTxn], target_paise: Paise) -> Proof:
    """The §13 breakdown of a composition against its bank line."""
    chosen = [txns[e] for e in composition]
    rows: list[tuple[str, int, Paise]] = []

    for kind, label, sign in _KINDS:
        items = [t for t in chosen if t.type == kind]
        if items:
            rows.append((label, len(items), sign * sum(t.amount_paise for t in items)))
    for field, label in _DEDUCTIONS:
        amount = sum(getattr(t, field) for t in chosen)
        if amount:
            rows.append((label, 0, -amount))

    total = sum(r[2] for r in rows)
    return Proof(bank_line_id, tuple(rows), total, target_paise, total - target_paise)
