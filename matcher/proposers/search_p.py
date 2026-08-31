"""Phase C — combinatorial search. §9.3.

    C1  anchored: seed a known settlement, search only the residual
    C2  unanchored over the window pool, filtered by G3

Both run §9.3's two passes: `solve_exact`, and only if that returned nothing, the
tolerance pass. Both emit ordinary `Claim`s and approve nothing — a subset that
sums correctly is a candidate, and the gate chain is what makes it a match (I8).
This is the first tier in the project that can propose an *arbitrary* subset, so it
is the first real test of whether G3 and G5 hold precision up.

**The asymmetry between the two tiers is the whole design.** C1 ignores the date
window for its anchor's own members — once the settlement id is known, membership
is a fact rather than an inference — which is what makes an on-hold release settled
outside the window recoverable at C1 and invisible to C2. C1 does not implement that
exemption; it declares the anchor on the claim and G1 applies it (`g1_exclusivity`).

**C2 refuses above `C2_MAX_POOL` rather than searching.** That is an
information-theoretic bound, not a budget: above it `2**len(pool)` exceeds the range
of attainable targets, so by pigeonhole every target has many representations and no
node budget can establish uniqueness. Searching anyway would produce answers whose
uniqueness is unprovable, which is not a match (§10.1).
"""

from __future__ import annotations

from collections.abc import Iterable

from core.coherence import is_plausible_payout
from core.models import BankLine, GatewayTxn, settlement_members, target
from core.subsetsum import (C2_MAX_POOL, TOLERANCE_PAISE, DeadlineExceeded,
                            SearchBudgetExceeded, solve_exact, solve_tolerance)
from matcher.proposers.base import Claim, Pool
from matcher.proposers.regex_p import RegexProposer

SETTLEMENT_WINDOW_DAYS = 2      # §15, and the window the ladder builds the pool over
SUBSET_NODE_BUDGET = 250_000    # §15. Not a performance knob: an exhausted budget
                                # means the tree was not exhausted, so uniqueness is
                                # unproven and the line is refused (§10.1).


class SearchProposer:
    """C1 or C2 depending on `tier`. Separate instances, because tier-major
    ordering (§9.8) runs every line through C1 before any line reaches C2."""

    def __init__(self, tier: str, txns: Iterable[GatewayTxn],
                 window_days: int = SETTLEMENT_WINDOW_DAYS) -> None:
        txns = list(txns)
        self.name = tier
        self.window_days = window_days
        self._txns = {t.entity_id: t for t in txns}
        # C1's anchors come from the same recovery Phase A uses. Re-running it here
        # rather than threading Phase A's trace through means C1 is self-contained
        # and testable on its own; the parse is a regex over one narration.
        self._recovery = ([RegexProposer(t, txns) for t in ("A1", "A2", "A3")]
                          if tier == "C1" else [])
        self._members = settlement_members(txns)
        # bank_line_id -> why nothing was searched. Read by the orchestrator into
        # the trace; stage 10's exception ledger is what types it. A refusal that
        # left no record would be indistinguishable from a search that found
        # nothing, and those are different facts.
        self.refusals: dict[str, str] = {}
        # The slice §9.10 hands the current line, an absolute `monotonic_ns`. The
        # orchestrator sets it before each `propose`; `None` is node budget only,
        # which is the reproducible mode §11 requires of the regression harness.
        # It is an attribute rather than a `propose` parameter because the
        # `Proposer` protocol is the boundary between the two layers (§7.2) and a
        # wall clock is not part of what a proposer is — the other three tiers are
        # O(1) and have nothing to time.
        self.deadline_ns: int | None = None

    def propose(self, line: BankLine, pool: Pool) -> list[Claim]:
        self.refusals.pop(line.bank_line_id, None)
        return self._c1(line, pool) if self.name == "C1" else self._c2(line, pool)

    # --- C1, anchored --------------------------------------------------------

    def _c1(self, line: BankLine, pool: Pool) -> list[Claim]:
        """One search per recovered anchor, over the residual only.

        The empty residual is not proposed: the group alone is A1's and B1's claim
        and has already walked the gate chain, G4 included. Re-proposing a set G2
        rejected changes nothing.
        """
        claims: list[Claim] = []
        for settlement_id in self._anchors(line):
            group = self._members[settlement_id]
            residual = target(line) - sum(self._txns[e].net for e in group)
            if residual == 0:
                continue
            rest = [t for t in pool if t.entity_id not in set(group)]
            # G3 judges the FULL composition. Filtering on the residual alone would
            # be a different rule than the gate that follows.
            keep = lambda c, g=group: is_plausible_payout(g + c, self._txns)  # noqa: E731
            for found in self._search(line, rest, residual, keep, base_size=len(group)):
                claims.append(Claim(line.bank_line_id, group + found,
                                    anchor_settlement_id=settlement_id,
                                    window_days=self.window_days))
        return claims

    def _anchors(self, line: BankLine) -> list[str]:
        """Settlement ids Phase A can recover from this line's narration, in a
        deterministic order (§8.6)."""
        return sorted({claim.anchor_settlement_id
                       for tier in self._recovery
                       for claim in tier.propose(line, ())
                       if claim.anchor_settlement_id is not None})

    # --- C2, unanchored ------------------------------------------------------

    def _c2(self, line: BankLine, pool: Pool) -> list[Claim]:
        if len(pool) > C2_MAX_POOL:
            self.refusals[line.bank_line_id] = (
                f"UNIQUENESS_UNPROVEN: pool of {len(pool)} exceeds C2_MAX_POOL "
                f"({C2_MAX_POOL}); above it uniqueness is not establishable at any "
                "node budget")
            return []
        keep = lambda c: is_plausible_payout(c, self._txns)  # noqa: E731
        return [Claim(line.bank_line_id, found, anchor_settlement_id=None,
                      window_days=self.window_days)
                for found in self._search(line, list(pool), target(line), keep)]

    # --- the two passes ------------------------------------------------------

    def _search(self, line: BankLine, pool: list[GatewayTxn], want: int,
                keep, base_size: int = 0) -> list[tuple[str, ...]]:
        """`solve_exact`, and the tolerance pass **only if it returned nothing**.

        That order is §9.3's and it is load-bearing at the top end too: if the exact
        pass returned *two* solutions the line is genuinely ambiguous, so the
        tolerance pass must not run — a wider band on an ambiguous line could
        manufacture a single answer to a question that has two.

        `keep` runs inside both searches rather than over their results. A candidate
        G3 would reject must not consume the two-solution cutoff, or a coherent
        second solution deeper in the tree is never reached and an ambiguous line is
        reported unique.
        """
        try:
            found = solve_exact(pool, want, SUBSET_NODE_BUDGET, keep=keep,
                                deadline_ns=self.deadline_ns)
            if found:
                return found
            # The delta is discarded: G2 recomputes it from the composition, and a
            # claim carrying its own arithmetic would be a claim that could lie
            # about it. What the pass is for is picking the minimum, not reporting.
            return [c for c, _ in solve_tolerance(pool, want, SUBSET_NODE_BUDGET,
                                                  TOLERANCE_PAISE, base_size, keep,
                                                  deadline_ns=self.deadline_ns)]
        except DeadlineExceeded as exc:
            # §10.1's other refusal, and the one that is not a property of the
            # data: the run's clock ran out on this line. It scores as FN exactly
            # like the node-budget refusal, and it is typed apart because a human
            # triages "give it more time" differently from "this is unprovable at
            # any budget" — and because this one moves with the machine (§11).
            self.refusals[line.bank_line_id] = (
                f"EXCEEDED_SEARCH_BUDGET: {exc} before the deadline for this line; "
                "no solution was found and none was ruled out")
            return []
        except SearchBudgetExceeded as exc:
            self.refusals[line.bank_line_id] = (
                f"UNIQUENESS_UNPROVEN: {exc} exhausted the {SUBSET_NODE_BUDGET} "
                "node budget; one answer may exist but a second was never ruled out")
            return []
