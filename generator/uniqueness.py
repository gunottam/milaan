"""The uniqueness gate. §6.2, and the DFS of §9.3 that it and the matcher share.

The gate runs the *same* solver the matcher will run — a solver bug that misses a
second solution would make the gate miss it too, asserting a uniqueness never
established. `tests/test_subsetsum.py` is the only check that this is sound (§6.3).

ponytail: `solve_exact` lives here because stage 3 is the first thing that needs
it. Stage 8's `matcher/proposers/search_p.py` imports it from here or it moves —
what must not happen is a second copy.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from core.coherence import is_plausible_payout
from core.models import BankLine, GatewayTxn, target
from core.money import Paise, ist_date, in_window, window_key
from generator.config import UNIQUENESS_NODE_BUDGET_OFFLINE


class SearchBudgetExceeded(Exception):
    """The tree was not exhausted, so nothing about uniqueness is known."""

    def __init__(self, nodes: int, pool_size: int) -> None:
        super().__init__(f"{nodes} nodes over a pool of {pool_size}")
        self.nodes = nodes
        self.pool_size = pool_size


def _suffix_sum(pool: list[GatewayTxn], f: Callable[[Paise], Paise]) -> list[Paise]:
    out = [0] * (len(pool) + 1)
    for i in range(len(pool) - 1, -1, -1):
        out[i] = out[i + 1] + f(pool[i].net)
    return out


def solve_exact(pool: list[GatewayTxn], target_paise: Paise, budget: int,
                max_solutions: int = 2,
                keep: Callable[[tuple[str, ...]], bool] | None = None
                ) -> list[tuple[str, ...]]:
    """Every subset of `pool` whose nets sum to the target, up to `max_solutions`.

    Two solutions is all the caller ever needs — one is a match, two is a refusal —
    so the default stops there. The property test raises the cap to compare full
    enumerations against brute force.

    `keep` filters candidates as they are found, which is §9.3's "C2 ... filtered
    by G3". It has to run inside the search: a rejected candidate must not consume
    the two-solution cutoff, or a coherent second solution further down the tree
    is never reached.
    """
    pool = sorted(pool, key=lambda t: (-abs(t.net), t.entity_id))
    pos = _suffix_sum(pool, lambda n: max(n, 0))
    neg = _suffix_sum(pool, lambda n: min(n, 0))
    solutions: list[tuple[str, ...]] = []
    nodes = 0

    def dfs(i: int, remaining: Paise, chosen: list[GatewayTxn]) -> None:
        nonlocal nodes
        if len(solutions) >= max_solutions:
            return
        nodes += 1
        if nodes > budget:
            raise SearchBudgetExceeded(nodes, len(pool))
        if i >= len(pool):
            return
        if remaining > pos[i] or remaining < neg[i]:
            return

        # A subset is recorded when its last element is taken, so each is reported
        # exactly once. §9.3's pseudocode instead tests `remaining == 0` on entry
        # and returns, which is wrong twice over: the return drops every superset
        # that adds a zero-netting group (a refund cancelling a payment inside the
        # same payout) — the very second solution this gate exists to find — and
        # without the return the same subset is re-reported at every node down the
        # all-skip path, letting duplicates consume the two-solution cutoff and
        # mark a uniquely resolvable line ambiguous.
        chosen.append(pool[i])
        rest = remaining - pool[i].net
        if rest == 0:                            # chosen is non-empty by construction (8.3)
            candidate = tuple(t.entity_id for t in chosen)
            if keep is None or keep(candidate):
                solutions.append(candidate)
        if len(solutions) < max_solutions:
            dfs(i + 1, rest, chosen)
        chosen.pop()
        dfs(i + 1, remaining, chosen)

    dfs(0, target_paise, [])
    return solutions


def window_pool(line: BankLine, txns: Iterable[GatewayTxn], window_days: int,
                claimed: frozenset[str] = frozenset()) -> list[GatewayTxn]:
    """Transactions whose `settled_at` IST date lies in
    `[value_date − window_days, value_date]`. Never reads `on_hold` (§9.3)."""
    anchor = window_key(line.value_date, line.txn_date)
    return [t for t in txns
            if t.settled_at and t.entity_id not in claimed
            and in_window(ist_date(t.settled_at), anchor, window_days)]


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
        return {
            "resolvable": True, "uniqueness": "budget_exhausted",
            "composition": sorted(intended), "excluded_from_scoring": True,
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

    assert solutions, f"{line.bank_line_id}: the intended composition is not reachable"
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
