"""Subset-sum. §9.3 of the spec, and the only implementation of it.

The generator's uniqueness oracle (§6.2) and the matcher's C1/C2 tiers run the
*same* solver. A solver bug that misses a second solution would make the oracle
miss it too, asserting a uniqueness never established — and the matcher would then
be scored against an answer key that agrees with its own bug.
`tests/test_subsetsum.py` is the only check that this is sound (§6.3).

Two bodies, both departing from §9.3's pseudocode where the pseudocode is wrong.
The departures are documented at the point they are made; do not "restore" either.

Lives in `core/` because both `generator/` and `matcher/` need it and neither may
import the other.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from core.models import GatewayTxn
from core.money import Paise

TOLERANCE_PAISE = 100   # §8.2 — ₹1.00, the outer cap of G4's double cap

C2_MAX_POOL = 35        # §9.3. Above this, unanchored subset-sum cannot establish
                        # uniqueness: 2**len(pool) exceeds the range of attainable
                        # targets, so by pigeonhole every target has many
                        # representations. An information-theoretic bound on the
                        # problem, not a budget knob — which is why it lives beside
                        # the solver rather than in either caller's config. The
                        # generator sizes its payouts against it; C2 refuses above
                        # it rather than searching.


class SearchBudgetExceeded(Exception):
    """The tree was not exhausted, so nothing about uniqueness is known."""

    def __init__(self, nodes: int, pool_size: int) -> None:
        super().__init__(f"{nodes} nodes over a pool of {pool_size}")
        self.nodes = nodes
        self.pool_size = pool_size


class DeadlineExceeded(SearchBudgetExceeded):
    """The run's clock ran out before the tree did (§9.10).

    A subclass because the consequence is identical — the tree was not exhausted,
    so uniqueness is unknown — but the *cause* is not, and §10.1 types the two
    differently: a node budget is a property of the problem and reproducible,
    a deadline is a property of the machine and is not. Any handler written for
    the base class stays correct; `search_p` distinguishes them for the ledger.
    """

    def __init__(self, nodes: int, pool_size: int) -> None:
        Exception.__init__(self, f"{nodes} nodes over a pool of {pool_size}")
        self.nodes = nodes
        self.pool_size = pool_size


# Checking the clock at every node would cost more than the node. Every 4096 is
# ~1ms of search on this pool size — finer than any slice the orchestrator hands
# out, and it bounds the overrun rather than leaving it open.
_CLOCK_EVERY = 4096


def _suffix_sum(pool: list[GatewayTxn], f: Callable[[Paise], Paise]) -> list[Paise]:
    out = [0] * (len(pool) + 1)
    for i in range(len(pool) - 1, -1, -1):
        out[i] = out[i + 1] + f(pool[i].net)
    return out


def solve_exact(pool: list[GatewayTxn], target_paise: Paise, budget: int,
                max_solutions: int = 2,
                keep: Callable[[tuple[str, ...]], bool] | None = None,
                deadline_ns: int | None = None) -> list[tuple[str, ...]]:
    """Every subset of `pool` whose nets sum to the target, up to `max_solutions`.

    Two solutions is all the caller ever needs — one is a match, two is a refusal —
    so the default stops there. The property test raises the cap to compare full
    enumerations against brute force.

    `keep` filters candidates as they are found, which is §9.3's "C2 ... filtered
    by G3". It has to run inside the search: a rejected candidate must not consume
    the two-solution cutoff, or a coherent second solution further down the tree
    is never reached.

    `deadline_ns` is an absolute `time.monotonic_ns()`, the slice §9.10 hands this
    line. `None` — the generator's oracle, and the regression harness — means node
    budget only, which is what makes those runs reproducible (§11).
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
        if (deadline_ns is not None and nodes % _CLOCK_EVERY == 0
                and time.monotonic_ns() > deadline_ns):
            raise DeadlineExceeded(nodes, len(pool))
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


def count_exact(pool: list[GatewayTxn], target_paise: Paise) -> int:
    """How many subsets of `pool` sum to the target. A census, not a search.

    It returns a count and no compositions, so it cannot propose anything and
    nothing downstream can act on it — which is the only reason it is allowed to do
    what `solve_exact` deliberately refuses to do and enumerate past two. C3 needs
    the figure for one sentence: *279 divisions of this payout balance against this
    credit, and the statement does not say which.* That claim is the finding, and
    "at least 2" is the same refusal wearing a weaker reason.

    Meet-in-the-middle, because the DFS cannot answer this at any budget the run
    can afford — `setl_0048`'s 30-transaction payout exhausts 5,000,000 nodes
    without finishing the count. Two halves, sums collapsed by value: milliseconds.
    The empty subset is never a solution (§8.3).

    ponytail: 2**(n/2) dicts, bounded by `C2_MAX_POOL` because C3 refuses above it
    before it ever asks. Past ~40 items this wants a different algorithm, not a
    bigger machine.
    """
    def sums(items: list[GatewayTxn]) -> dict[Paise, int]:
        out = {0: 1}
        for txn in items:
            nxt = dict(out)
            for total, count in out.items():
                nxt[total + txn.net] = nxt.get(total + txn.net, 0) + count
            out = nxt
        return out

    half = len(pool) // 2
    left, right = sums(pool[:half]), sums(pool[half:])
    found = sum(count * right.get(target_paise - total, 0)
                for total, count in left.items())
    return found - 1 if target_paise == 0 else found


def solve_tolerance(pool: list[GatewayTxn], target_paise: Paise, budget: int,
                    tol: Paise = TOLERANCE_PAISE, base_size: int = 0,
                    keep: Callable[[tuple[str, ...]], bool] | None = None,
                    deadline_ns: int | None = None
                    ) -> list[tuple[tuple[str, ...], Paise]]:
    """§9.3's tolerance pass. The candidates at the **minimum** |delta|, with that
    delta, capped at two — because two is already a G5 refusal.

    Runs only when `solve_exact` returned nothing; that rule belongs to the caller,
    which is the only place both results are in hand.

    Four things this does that the obvious implementation does not:

    - **It records at interior nodes and keeps searching.** Any node's `chosen` is
      a complete, legitimate candidate — you simply stop adding. Accepting the
      first one and returning is what §9.3 explicitly forbids, and it would return
      whichever near miss the sort order happened to reach first rather than the
      best one.
    - **The band is §8.2's double cap, over the FULL composition.** `base_size` is
      C1's pre-seeded anchor group. Computing `len(chosen)` over the residual alone
      would make the solver stricter than the G4 that judges the claim, discarding
      candidates the gate would have admitted.
    - **Pruning widens by `tol`.** `solve_exact`'s bounds ask whether the remainder
      is exactly attainable; here anything within the band is, so the same bounds
      would prune away every near miss before it was recorded.
    - **There is no solution-count cutoff.** The minimum is not known until the tree
      is exhausted. Only the node budget bounds this pass, and an exhausted budget
      raises — an unexhausted tree says nothing about which candidate was best.
    """
    pool = sorted(pool, key=lambda t: (-abs(t.net), t.entity_id))
    pos = _suffix_sum(pool, lambda n: max(n, 0))
    neg = _suffix_sum(pool, lambda n: min(n, 0))
    best: list[tuple[tuple[str, ...], Paise]] = []
    best_abs = tol + 1
    nodes = 0

    def record(candidate: tuple[str, ...], delta: Paise) -> None:
        nonlocal best, best_abs
        if keep is not None and not keep(candidate):
            return
        if abs(delta) < best_abs:
            best, best_abs = [(candidate, delta)], abs(delta)
        elif abs(delta) == best_abs and len(best) < 2:
            # Distinct by construction: each subset is recorded exactly once, so a
            # second arrival at the same |delta| is a genuinely different set.
            best.append((candidate, delta))

    def dfs(i: int, remaining: Paise, chosen: list[GatewayTxn]) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > budget:
            raise SearchBudgetExceeded(nodes, len(pool))
        if (deadline_ns is not None and nodes % _CLOCK_EVERY == 0
                and time.monotonic_ns() > deadline_ns):
            raise DeadlineExceeded(nodes, len(pool))
        if i >= len(pool):
            return
        if remaining > pos[i] + tol or remaining < neg[i] - tol:
            return

        # Recorded when the last element is taken, as in `solve_exact`, so each
        # subset is considered exactly once. `remaining` is the delta the claim
        # will carry: G2 computes `Σ net − target`, and this is `target − Σ net`,
        # so the sign is flipped on the way out.
        chosen.append(pool[i])
        rest = remaining - pool[i].net
        if abs(rest) <= min(tol, base_size + len(chosen)):
            record(tuple(t.entity_id for t in chosen), -rest)
        dfs(i + 1, rest, chosen)
        chosen.pop()
        dfs(i + 1, remaining, chosen)

    dfs(0, target_paise, [])
    return best
