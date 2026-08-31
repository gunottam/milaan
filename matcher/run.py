"""The ladder: tier-major ordering, propagation, and the run-level deadline. §9.8, §9.10.

Three rules, and each of them exists because the obvious alternative silently
decides outcomes:

**Tier-major (§9.8).** Every line attempts A1 before any line attempts A2. Matching
is exclusive, so under line-major ordering a speculative C2 search on `bl_0001`
could consume transactions `bl_0002` had a hard UTR for, and the answer would depend
on the sort order of the bank file. Strongest evidence first, for the whole board.

**Ascending pool size, then `bank_line_id` (§9.8).** Most-constrained-first within a
tier. A line with a pool of 3 has fewer ways to be wrong than one with a pool of 30,
and resolving it shrinks the other pools. The `bank_line_id` tie-break is what makes
the order total, and a total order is what makes the run reproducible.

**A run-level deadline, not per-line timeouts (§9.10).** Per-line timeouts do not
compose: `134 lines x 2s x 2 passes` is nine minutes. The run holds one clock and
hands each line `min(2000, remaining_ms / unmatched)`. When it runs out the ladder
stops issuing work, the lines it never reached are named, and scoring runs on what
was proved. A partial run that reports itself is the thesis; a hang is not.

The system is greedy (§9.9): matches are committed and never revoked, so a line
matching early can consume transactions a later line needed. Ordering mitigates it
and Phase E surfaces the damage. It is not claimed to be optimal.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass

from core.models import BankLine, GatewayTxn, window_pool
from matcher.proposers.base import Claim
from matcher.proposers.lookup_p import LookupProposer
from matcher.proposers.regex_p import RegexProposer
from matcher.proposers.search_p import SearchProposer
from matcher.uniqueness import resolve
from matcher.verify import Verdict, check

MATCH_DEADLINE_MS = 22_000   # §15's Phase C allocation, and the whole ladder's clock
PER_LINE_CAP_MS = 2_000      # §9.10's `min(2000, ...)`
PROPAGATION_PASSES = 2       # §9.8

Matched = dict[str, tuple[str, Claim, Verdict]]


@dataclass(frozen=True)
class Run:
    """What the ladder proved, and what it did not get to.

    `exceeded` is §9.10's `EXCEEDED_SEARCH_BUDGET` population: open lines the
    deadline stopped before they had been offered every tier. They score as FN
    (§11) and they are named rather than counted, because "12 lines unattempted" is
    a different fact from "12 lines had no answer" and the scoreboard has to say
    which one it is.

    `elapsed_ms` is deliberately not part of the rendered report. §11: wall-clock
    deadlines make results machine-dependent, so the reproducible artifact carries
    the node budget and the timing is printed beside it, not inside it.
    """

    matched: Matched
    trace: list[dict]
    exceeded: tuple[str, ...] = ()
    passes_run: int = 0
    passes_asked: int = PROPAGATION_PASSES
    elapsed_ms: int = 0
    deadline_ms: int | None = None

    @property
    def cut(self) -> tuple[str, ...]:
        """Open lines whose search the per-line slice stopped mid-tree.

        The deadline's other population, and the one §9.10 does not name: not
        unattempted, but not exhausted either. Same FN, different sentence to a
        human — "give it more time" rather than "there is nothing here".
        """
        return tuple(sorted(
            {s["line"] for s in self.trace if s["unproven"]
             and s["unproven"].startswith("EXCEEDED_SEARCH_BUDGET")}
            - set(self.matched)))

    @property
    def deadline_hit(self) -> bool:
        """True when the clock, not the data, ended something."""
        return (self.passes_run < self.passes_asked
                or bool(self.exceeded) or bool(self.cut))

    def banner(self) -> list[str]:
        """§9.10's explicit banner. Empty when the run completed on the data.

        Two populations, named apart, because "12 lines unattempted" and "12 lines
        with no answer" score identically and are not the same fact — and because
        both of these are properties of the machine (§11), so a reader comparing
        this board with another needs to know the clock was in play.
        """
        if not self.deadline_hit:
            return []
        out = [f"  !! deadline reached at {self.deadline_ms:,} ms — "
               f"{self.passes_run} of {self.passes_asked} propagation passes run."]
        for label, lines in (("unattempted, never offered the full ladder",
                              self.exceeded),
                             ("search stopped mid-tree by its per-line slice",
                              self.cut)):
            if lines:
                shown = ", ".join(lines[:8])
                more = f" (+{len(lines) - 8} more)" if len(lines) > 8 else ""
                out.append(f"     EXCEEDED_SEARCH_BUDGET, {len(lines)} {label}:")
                out.append(f"       {shown}{more}")
        out.append("     Those lines score as FN. Nothing below was relaxed to fit "
                   "the clock.")
        return out


def build_tiers(txns: Sequence[GatewayTxn], window_days: int = 2) -> list:
    """The ladder, in order. Separate from `run_ladder` so a caller can measure one
    tier's reach by handing back a prefix of it — which is how stage 8 scores C1
    alone against the prediction stage 7 registered for it."""
    return [RegexProposer("A1", txns), RegexProposer("A2", txns),
            RegexProposer("A3", txns), LookupProposer("B1", txns, window_days),
            LookupProposer("B2", txns, window_days),
            SearchProposer("C1", txns, window_days),
            SearchProposer("C2", txns, window_days)]


def run_ladder(txns: Sequence[GatewayTxn], bank_lines: Sequence[BankLine],
               window_days: int = 2, tiers: Sequence | None = None, *,
               deadline_ms: int | None = MATCH_DEADLINE_MS,
               passes: int = PROPAGATION_PASSES) -> Run:
    """A1 → A2 → A3 → B1 → B2 → C1 → C2, twice, under one clock.

    `deadline_ms=None` disables the clock and leaves the node budget as the only
    bound. That is the reproducible mode: §11 requires the regression harness to
    use node budget only, because a wall clock makes the result a property of the
    machine. The live run passes a number and reports which lines it consumed.

    Never raises. A deadline is a normal outcome, not an error, and a reconciler
    that dies on its own timeout has converted a partial answer into no answer.
    """
    by_id = {t.entity_id: t for t in txns}
    tiers = build_tiers(txns, window_days) if tiers is None else tiers
    b1 = next((t for t in tiers if t.name == "B1"), None)
    last = tiers[-1].name if tiers else None

    claimed: set[str] = set()
    matched: Matched = {}
    trace: list[dict] = []
    walked: set[str] = set()      # offered every tier at least once
    started = time.monotonic_ns()
    ends_at = None if deadline_ms is None else started + deadline_ms * 1_000_000
    passes_run = 0
    stopped = False

    for pass_no in range(1, passes + 1):
        if stopped:
            break
        for tier in tiers:
            if stopped:
                break
            if ends_at is not None and time.monotonic_ns() >= ends_at:
                # Checked before the pool build, not just before each line: the
                # build is a scan over every transaction for every open line, and
                # paying for a sweep the clock cannot afford to use is the one place
                # this loop could overrun its own deadline.
                stopped = True
                break
            open_lines = [b for b in bank_lines if b.bank_line_id not in matched]
            # Pools are built once per tier, for the sort, and filtered against the
            # live `claimed` set at each line. Rebuilding per line would rescan
            # every transaction 134 times a tier for a set membership test; reusing
            # the unfiltered list would let a tier cite a transaction claimed
            # earlier in this same tier, which G1 rejects — correct, but it would
            # cost recall and show up in the trace as staleness rather than as the
            # bug it is.
            frozen = frozenset(claimed)
            pools = {b.bank_line_id: window_pool(b, txns, window_days, frozen)
                     for b in open_lines}
            order = sorted(open_lines,
                           key=lambda b: (len(pools[b.bank_line_id]), b.bank_line_id))

            for line in order:
                now = time.monotonic_ns()
                if ends_at is not None and now >= ends_at:
                    stopped = True
                    break
                # §9.10's `min(2000, remaining_ms / unmatched_count)`, as an
                # absolute instant. A *fair* share, not a generous one: dividing by
                # every unmatched line rather than by the ones left in this tier is
                # what stops the first expensive line from spending the whole run.
                # Only the search tiers carry a clock; A and B are O(1) and have
                # nothing to time.
                if hasattr(tier, "deadline_ns"):
                    tier.deadline_ns = None if ends_at is None else now + 1_000_000 * min(
                        PER_LINE_CAP_MS,
                        (ends_at - now) // 1_000_000 // max(len(bank_lines) - len(matched), 1))
                if tier.name == last:
                    walked.add(line.bank_line_id)

                pool = [t for t in pools[line.bank_line_id]
                        if t.entity_id not in claimed]
                claims = tier.propose(line, pool)
                refusal = getattr(tier, "refusals", {}).get(line.bank_line_id)
                if not claims:
                    if refusal:
                        # A tier that declined to search is not a tier that searched
                        # and found nothing (§10.1). Stage 10's ledger types this;
                        # the trace is what stops it being invisible in the meantime.
                        trace.append({"line": line.bank_line_id, "tier": tier.name,
                                      "pass": pass_no,
                                      "pool": len(pools[line.bank_line_id]),
                                      "candidates": 0, "won": False,
                                      "stale": 0, "refused": True, "anchors": [],
                                      "unproven": refusal})
                    continue
                verdicts = [(claim, check(claim, line, by_id, claimed))
                            for claim in claims]
                won, verdict = resolve(verdicts)
                trace.append({
                    "line": line.bank_line_id, "tier": tier.name, "pass": pass_no,
                    # The size the sort saw — this tier's opening snapshot. The
                    # tier itself may see fewer, because a line matched earlier in
                    # this same sweep removes its composition from every later pool.
                    "pool": len(pools[line.bank_line_id]),
                    "candidates": len(claims),
                    "won": won is not None,
                    "stale": sum(1 for _, v in verdicts if v.gate == "G1"
                                 and "already claimed" in (v.reason or "")),
                    "refused": won is None and verdict is not None,
                    "anchors": sorted({c.anchor_settlement_id for c in claims
                                       if c.anchor_settlement_id}),
                    "unproven": refusal,
                })
                if won is None:
                    continue
                matched[line.bank_line_id] = (tier.name, won, verdict)
                claimed |= set(won.composition)
                if b1 is not None and won.anchor_settlement_id:
                    b1.release(won.anchor_settlement_id)
        if not stopped:
            passes_run = pass_no

    return Run(
        matched=matched, trace=trace,
        exceeded=tuple(sorted(b.bank_line_id for b in bank_lines
                              if b.bank_line_id not in matched
                              and b.bank_line_id not in walked)),
        passes_run=passes_run, passes_asked=passes,
        elapsed_ms=(time.monotonic_ns() - started) // 1_000_000,
        deadline_ms=deadline_ms,
    )
