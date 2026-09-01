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
# Deductions are summed over **payments only**, because `net_contribution` (§3.1)
# subtracts them for payments and for nothing else: a refund contributes exactly
# `-amount_paise`, whatever else its row carries.
#
# This is not a formality. `ROUNDING_DRIFT` and `INSTANT_SETTLEMENT` allocate their
# charge across a settlement's members (§4.3) and thirteen refunds on seed 42 come
# out holding a non-zero `fee_paise` that the payout arithmetic never sees. Summing
# over everything deducted that money a second time, so the strip's total missed the
# gate's by up to ₹1.72 on any composition holding one — the proof strip is the
# thing a human verifies, and one that does not equal the sum `check()` performed is
# the exact failure I8 exists to prevent. Caught at stage 11 by the first assertion
# that compared `Proof.delta_paise` with `Verdict.delta_paise`.
_DEDUCTED_FROM = "payment"
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
    """The §13 breakdown of a composition against its bank line.

    `total_paise` is `Σ net_contribution(composition)` by construction, and
    `tests/test_gates.py::test_the_proof_totals_what_the_gate_summed` pins that.
    The strip is only worth showing if it is the same arithmetic the gate ran.
    """
    chosen = [txns[e] for e in composition]
    rows: list[tuple[str, int, Paise]] = []

    for kind, label, sign in _KINDS:
        items = [t for t in chosen if t.type == kind]
        if items:
            rows.append((label, len(items), sign * sum(t.amount_paise for t in items)))
    for field, label in _DEDUCTIONS:
        amount = sum(getattr(t, field) for t in chosen
                     if t.type == _DEDUCTED_FROM)
        if amount:
            rows.append((label, 0, -amount))

    total = sum(r[2] for r in rows)
    return Proof(bank_line_id, tuple(rows), total, target_paise, total - target_paise)
