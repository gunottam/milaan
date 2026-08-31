"""The uniqueness gate. §6.2.

The gate runs the *same* solver the matcher runs — a solver bug that misses a
second solution would make the gate miss it too, asserting a uniqueness never
established. `tests/test_subsetsum.py` is the only check that this is sound (§6.3).

The solver moved to `core/subsetsum.py` at stage 8, when `matcher/` became its
second caller: `matcher/` importing `generator/` is the wrong direction, and a
second copy is the one thing that must not happen.
"""

from __future__ import annotations

from collections.abc import Iterable

from core.coherence import is_plausible_payout
from core.models import BankLine, GatewayTxn, target
from core.money import ist_date, window_key
from core.subsetsum import SearchBudgetExceeded, solve_exact
from generator.config import UNIQUENESS_NODE_BUDGET_OFFLINE


def _shape(txns: dict[str, GatewayTxn], composition: tuple[str, ...]) -> list[tuple]:
    """The tax-and-timing fingerprint of a composition. Two compositions with the
    same fingerprint post identical books, so the ambiguity is `equivalent`."""
    return sorted(
        (t.type, t.method, t.amount_paise, t.fee_paise, t.tax_paise, t.tds_paise,
         ist_date(t.settled_at).isoformat() if t.settled_at else "")
        for t in (txns[e] for e in composition)
    )


def classify(line: BankLine, txns: dict[str, GatewayTxn], pool: list[GatewayTxn],
             intended: tuple[str, ...],
             budget: int = UNIQUENESS_NODE_BUDGET_OFFLINE) -> dict:
    """The §6.2 truth record for one bank line.

    Candidates are filtered through G3 as they are found. The matcher will run the
    solver *and* the gate chain, so a second solution G3 would reject is not a
    second answer — counting it would mark the line unresolvable and turn the
    matcher's correct match into a false positive.
    """
    try:
        solutions = solve_exact(pool, target(line), budget,
                                keep=lambda c: is_plausible_payout(c, txns))
    except SearchBudgetExceeded:
        # The composition is known by construction; only its uniqueness is
        # unproven. Those are different facts, and collapsing them into
        # `excluded_from_scoring` drops the line from every denominator — which
        # inflates recall, because cost tracks the count of negative-net items and
        # the excluded set is therefore the hardest lines. Scoring must disclose
        # this bucket separately (matched / refused / wrong) instead of hiding it.
        return {
            "resolvable": True, "uniqueness": "unproven",
            "composition": sorted(intended),
            "injected_breaks": [], "expected_delta_paise": 0,
        }

    if len(solutions) >= 2:
        return {
            "resolvable": False, "composition": None,
            "injected_breaks": ["AMBIGUOUS_SUBSET"],
            "ambiguity_class": "equivalent"
            if _shape(txns, solutions[0]) == _shape(txns, solutions[1])
            else "consequential",
            "alternate_compositions": [sorted(s) for s in solutions],
            "unresolvable_reason": "Two compositions sum to the bank amount.",
        }

    if not solutions:
        # G3 refuses the real composition. That is the documented cost of a prior
        # (§9.4): it rejects correct answers and loses recall, never admits a wrong
        # one. Truth still records the real composition — truth describes the data,
        # not the matcher's reach — so the matcher's refusal scores as a miss and
        # the cost of our own prior stays visible instead of being excluded.
        return {
            "resolvable": True, "uniqueness": "by_construction",
            "composition": sorted(intended), "g3_refuses_composition": True,
            "injected_breaks": [], "expected_delta_paise": 0,
        }

    return {
        "resolvable": True, "uniqueness": "verified",
        "composition": sorted(solutions[0]),
        "injected_breaks": [], "expected_delta_paise": 0,
    }


def mark_duplicate_targets(bank_lines: Iterable[BankLine], records: dict[str, dict]) -> int:
    """Finding 8.4: two bank lines with the same date and amount are
    interchangeable, so truth must mark the whole *set* unresolvable rather than
    assert an assignment scoring would then penalise.
    """
    groups: dict[tuple, list[str]] = {}
    for line in bank_lines:
        key = (window_key(line.value_date, line.txn_date), target(line))
        groups.setdefault(key, []).append(line.bank_line_id)

    marked = 0
    for ids in groups.values():
        if len(ids) < 2:
            continue
        for bank_line_id in ids:
            records[bank_line_id] = {
                "resolvable": False, "composition": None,
                "injected_breaks": ["AMBIGUOUS_SUBSET"],
                "ambiguity_class": "equivalent",
                "unresolvable_reason":
                    f"Bank lines {', '.join(ids)} share a date and amount; "
                    "any assignment between them balances.",
            }
            marked += 1
    return marked
