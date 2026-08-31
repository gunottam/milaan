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
from core.subsetsum import (SearchBudgetExceeded, solve_exact,
                            solve_tolerance)

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


# --- the tolerance pass, §9.3 -------------------------------------------------


def brute_tolerance(pool: list[GatewayTxn], target: int, tol: int,
                    base_size: int = 0) -> tuple[set[frozenset[str]], int]:
    """Every non-empty subset inside §8.2's double cap, reduced to those at the
    minimum |delta|. Trivially correct at ≤18 items, which is the whole point."""
    best: set[frozenset[str]] = set()
    best_abs = tol + 1
    for r in range(1, len(pool) + 1):
        for combo in itertools.combinations(pool, r):
            delta = sum(t.net for t in combo) - target
            if abs(delta) > min(tol, base_size + r):
                continue
            if abs(delta) < best_abs:
                best, best_abs = {frozenset(t.entity_id for t in combo)}, abs(delta)
            elif abs(delta) == best_abs:
                best.add(frozenset(t.entity_id for t in combo))
    return best, best_abs


@pytest.mark.parametrize("max_size,iterations,seed", [(12, 120, 3), (16, 8, 4)])
def test_the_tolerance_pass_finds_the_same_minimum_brute_force_does(
        max_size, iterations, seed):
    """The pass exists to take the **minimum** |delta| across the whole tree, not
    the first node inside the band. Only brute force can check that it did."""
    rng = random.Random(seed)
    for _ in range(iterations):
        n = rng.randint(1, max_size)
        nets = [rng.choice([1, -1]) * rng.randint(1, 40) for _ in range(n)]
        pool = pool_of(nets)
        target = rng.randint(-60, 60)
        tol, base = rng.choice([(3, 0), (8, 0), (8, 4), (100, 0)])

        expected, best_abs = brute_tolerance(pool, target, tol, base)
        found = solve_tolerance(pool, target, BIG, tol, base)

        assert len(found) == min(2, len(expected)), (nets, target, tol, base)
        assert as_sets([c for c, _ in found]) <= expected
        for candidate, delta in found:
            assert abs(delta) == best_abs
            # The delta reported is G2's residual, `Σ net − target`, so a caller
            # can compare it with the gate that will judge the claim.
            assert delta == sum(pool_of(nets)[int(e[1:])].net for e in candidate) - target


def test_the_minimum_is_taken_not_the_first_node_inside_the_band():
    # Sorted by (-abs(net), entity_id), so {50} is reached long before {30, 19}.
    # Returning the first qualifying node gives delta 2; the minimum is 1.
    pool = pool_of([50, 30, 19])
    found = solve_tolerance(pool, 48, BIG, tol=5)
    assert len(found) == 1
    assert as_sets([c for c, _ in found]) == {frozenset({"e01", "e02"})}
    assert found[0][1] == 1


def test_two_sets_at_the_same_minimum_are_both_returned():
    # A tie inside the band is a G5 refusal, so both have to come back — returning
    # one would be an answer to a question with two.
    found = solve_tolerance(pool_of([11, 9, 4]), 10, BIG, tol=5)
    assert as_sets([c for c, _ in found]) == {frozenset({"e00"}), frozenset({"e01"})}
    assert {d for _, d in found} == {1, -1}


def test_base_size_widens_the_per_transaction_cap_to_the_full_composition():
    """§8.2's second cap counts the whole composition. C1 searches only the
    residual, so without `base_size` the solver would be stricter than the G4 that
    judges the claim and would discard candidates the gate admits."""
    pool = pool_of([100])
    # One residual item, delta 3: `min(tol, len(chosen))` is 1, so it is outside.
    assert solve_tolerance(pool, 97, BIG, tol=100) == []
    # The same claim with a 20-member anchor group seeded: the cap is 21, inside.
    assert solve_tolerance(pool, 97, BIG, tol=100, base_size=20) == [(("e00",), 3)]


def test_the_tolerance_pass_refuses_on_budget_rather_than_guessing():
    # The minimum is not known until the tree is exhausted, so a partial tree says
    # nothing about which candidate was best (§10.1).
    pool = pool_of([2 * i for i in range(1, 25)])
    with pytest.raises(SearchBudgetExceeded):
        solve_tolerance(pool, 101, budget=50, tol=100)


def test_a_wider_band_only_ever_admits_more():
    # Monotone in `tol`, which is what makes G4 the sole non-monotonic gate (§8.1):
    # widening cannot lose a candidate, only admit one strict arithmetic rejected.
    pool = pool_of([40, 25, 11, -7])
    assert solve_tolerance(pool, 39, BIG, tol=0) == []
    assert solve_tolerance(pool, 39, BIG, tol=1) == [(("e00",), 1)]
