"""§6.3 — the only check that the uniqueness oracle is sound.

The gate uses the same solver the matcher uses, so a solver that misses a second
solution makes the gate miss it too: truth would assert a uniqueness never
established, invisibly, and every recall number measured against it would be wrong
in a way no other test catches. Brute force is trivially correct at ≤18 items.
"""

from __future__ import annotations

import itertools
import random

import pytest

from core.models import GatewayTxn
from generator.uniqueness import SearchBudgetExceeded, solve_exact

BIG = 10_000_000        # effectively unlimited node budget
ALL = 10_000            # effectively unlimited solution cap


def pool_of(nets: list[int]) -> list[GatewayTxn]:
    """Transactions with the given net contributions. A negative net is a refund —
    mixed signs are what the pos/neg suffix arrays exist for."""
    return [
        GatewayTxn(entity_id=f"e{i:02d}", type="payment" if n >= 0 else "refund",
                   amount_paise=abs(n))
        for i, n in enumerate(nets)
    ]


def brute_force(pool: list[GatewayTxn], target: int) -> set[frozenset[str]]:
    """Every non-empty subset summing to the target. The empty subset is excluded
    by construction (8.3)."""
    found = set()
    for r in range(1, len(pool) + 1):
        for combo in itertools.combinations(pool, r):
            if sum(t.net for t in combo) == target:
                found.add(frozenset(t.entity_id for t in combo))
    return found


def as_sets(solutions: list[tuple[str, ...]]) -> set[frozenset[str]]:
    return {frozenset(s) for s in solutions}


@pytest.mark.parametrize("max_size,iterations,seed", [(12, 120, 1), (18, 6, 2)])
def test_dfs_enumerates_exactly_what_brute_force_does(max_size, iterations, seed):
    rng = random.Random(seed)
    for _ in range(iterations):
        n = rng.randint(1, max_size)
        # A narrow value range forces collisions, which is the whole point — wide
        # random integers almost never produce a second solution.
        nets = [rng.choice([1, -1]) * rng.randint(1, 40) for _ in range(n)]
        pool = pool_of(nets)

        if rng.random() < 0.7:      # a reachable target, so solutions exist
            k = rng.randint(1, n)
            target = sum(t.net for t in rng.sample(pool, k))
        else:
            target = rng.randint(-60, 60)

        expected = brute_force(pool, target)
        found = solve_exact(pool, target, budget=BIG, max_solutions=ALL)
        # Compare as sets for equality, but check the raw list for duplicates too:
        # a set comparison alone hides a subset being reported more than once, and
        # duplicates consume the two-solution cutoff.
        assert len(found) == len(set(found)), (nets, target, found)
        assert as_sets(found) == expected, (nets, target, sorted(map(sorted, expected)))


def test_the_empty_subset_is_never_a_solution():
    # Finding 8.3. Target zero with no zero-net item has no answer at all.
    assert solve_exact(pool_of([5, 7, 11]), 0, budget=BIG, max_solutions=ALL) == []
    # A pair that cancels IS a solution; the empty set still is not.
    assert as_sets(solve_exact(pool_of([5, -5, 7]), 0, budget=BIG, max_solutions=ALL)) == {
        frozenset({"e00", "e01"})
    }


def test_a_zero_net_item_makes_every_solution_ambiguous():
    # A transaction contributing nothing can join any composition. Real: a refund
    # exactly offsetting one payment inside the same payout.
    solutions = as_sets(solve_exact(pool_of([9, 4, -4]), 9, budget=BIG, max_solutions=ALL))
    assert solutions == {frozenset({"e00"}), frozenset({"e00", "e01", "e02"})}


def test_the_default_cutoff_stops_at_two_and_they_are_real():
    # Two solutions is all any caller needs: one is a match, two is a refusal.
    nets = [10, 10, 10, 5, 5]
    everything = brute_force(pool_of(nets), 15)
    assert len(everything) > 2
    stopped = solve_exact(pool_of(nets), 15, budget=BIG)
    assert len(as_sets(stopped)) == 2        # two DISTINCT answers, not one twice
    assert as_sets(stopped) <= everything


def test_a_unique_answer_is_reported_as_one_not_truncated():
    solutions = solve_exact(pool_of([1, 2, 4, 8, 16]), 21, budget=BIG)
    assert as_sets(solutions) == {frozenset({"e00", "e02", "e04"})}


def test_the_budget_is_a_refusal_not_a_wrong_answer():
    # An exhausted budget means the tree was not exhausted, so nothing about
    # uniqueness is known — it must raise, never return a plausible list.
    # Every net is even, so an odd target is unreachable — but it is well inside
    # the pool's range, so proving that means exhausting the tree.
    pool = pool_of([2 * i for i in range(1, 25)])
    with pytest.raises(SearchBudgetExceeded) as excinfo:
        solve_exact(pool, 101, budget=50)
    assert excinfo.value.pool_size == 24

    # An out-of-range target is refused by pruning alone, not by the budget.
    assert solve_exact(pool, 10 ** 9, budget=50) == []


def test_solutions_are_deterministic_across_runs():
    nets = [7, -3, 12, 12, 5, -5, 9]
    first = solve_exact(pool_of(nets), 21, budget=BIG, max_solutions=ALL)
    second = solve_exact(list(reversed(pool_of(nets))), 21, budget=BIG, max_solutions=ALL)
    assert first == second        # sorted by (-abs(net), entity_id), tie-break 8.6
