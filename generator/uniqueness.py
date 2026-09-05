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

from core.coherence import book_shape, is_plausible_payout
from core.models import BankLine, GatewayTxn, target, window_pool
from core.money import window_key
from core.subsetsum import (SearchBudgetExceeded, solve_exact,
                            solve_tolerance)
from generator.config import UNIQUENESS_NODE_BUDGET_OFFLINE



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
            if book_shape(solutions[0], txns) == book_shape(solutions[1], txns)
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


def audit_verified(records: dict[str, dict], lines: dict, txns: dict,
                   all_txns, window_days: int,
                   budget: int = UNIQUENESS_NODE_BUDGET_OFFLINE) -> list[str]:
    """**Every `uniqueness: "verified"` record must contain a composition the gate
    actually found.** Returns the bank line ids that failed and downgrades them.

    This is the assertion that should have shipped with §6.2 and did not, and the
    hole it leaves is not theoretical — `generator/breaks.py::rounding_drift`
    stamps `verified` by fiat and never calls `classify` at all. A ROUNDING_DRIFT
    line's recorded composition misses the credit by the drift, so the exact
    enumeration cannot contain it; where a *coincidental* exact composition also
    sits in the window, truth certifies a line as uniquely determined when two
    compositions close it and the matcher will take the other one. Seed 6's
    `bl_0079` is that line: 23 transactions recorded at −16 paise, a coincidental
    24-transaction set at 0, and §9.3's exact-first rule means the tolerance pass
    that would have proposed the real answer never runs.

    **The enumeration is not widened to make truth's answer appear — it is made
    faithful to §9.3.** The matcher runs `solve_exact` and falls through to the
    tolerance pass *only if that returned nothing*
    (`matcher/proposers/search_p.py::_search`), so the set of compositions the
    matcher will ever consider is exactly: the exact solutions, or — when there are
    none — the minimum-|delta| ones. A gate that enumerated only exact balances
    would refuse every ROUNDING_DRIFT line, including the ~145 of 150 that close
    correctly through G4 and are working as designed; a gate that enumerated
    everything within tolerance regardless would certify `bl_0079`, which is the
    line that is actually broken. The two-pass rule is what separates them, and it
    is not a widening: it is the gate asking the question the matcher will answer.

    A record that fails is downgraded to `unproven` — composition known, uniqueness
    not established — an existing disclosed bucket held out of the headline (§11).
    Nothing is dropped and no denominator shrinks; the line stops claiming a
    certification it does not have.
    """
    failed = []
    for bank_line_id, rec in sorted(records.items()):
        if rec.get("uniqueness") != "verified" or not rec.get("composition"):
            continue
        line = lines.get(bank_line_id)
        if line is None:
            continue
        pool = window_pool(line, all_txns, window_days)
        seen = {t.entity_id for t in pool}
        pool = pool + [txns[e] for e in rec["composition"]
                       if e in txns and e not in seen]
        keep = lambda c: is_plausible_payout(c, txns)      # noqa: E731 — §9.3's filter
        try:
            solutions = solve_exact(pool, target(line), budget, keep=keep)
            if not solutions:
                # §9.3's second pass, and only under the condition the matcher
                # applies it: exact returned nothing.
                solutions = [c for c, _ in solve_tolerance(
                    pool, target(line), budget, keep=keep)]
        except SearchBudgetExceeded:
            solutions = []
        want = set(rec["composition"])
        if any(set(s) == want for s in solutions):
            continue
        failed.append(bank_line_id)
        rec["uniqueness"] = "unproven"
        rec["uniqueness_refuted"] = True
        rec["unresolvable_reason"] = (
            "The recorded composition is not among the compositions §9.3's search "
            f"reaches for this credit ({len(solutions)} found). Another composition "
            "closes the line at a smaller |delta|, so the exact pass returns it and "
            "the tolerance pass that would propose this one never runs. Stamped "
            "`verified` without being enumerated — see "
            "generator/uniqueness.py::audit_verified.")
    return failed


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
