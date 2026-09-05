"""C3 — the pairwise split. §9.3, finding 8.5.

    For each unmatched settlement, test whether any two unmatched bank lines in the
    window jointly sum to its total. O(n²) over a residue of ~10 lines.

`SPLIT_PAYOUT` is the one break in §5 where a bank line is not a payout. The bank
took one settlement and posted it as two credits, so **neither credit is a
composition any other tier can propose**: C1 and C2 search for a subset that sums
to *this* line, and any such subset is a partial slice of a settlement, which G3
refuses by design. That refusal is correct. C3 exists because the coherent unit is
the pair.

**Three things are searched, in this order, and each can refuse.**

1. **The pairing.** Two open lines in the window and one settlement whose members
   are all unclaimed. `joint − group total` is the residual, and it is the same
   residual C1 searches for: a payout is a settlement group plus whatever
   cross-cycle items it nets (§9.1's amendment), so the residual is rarely zero.
   It is composed from **unassigned strays only**, up to G3's cap of two. That is
   narrower than G3, which also permits items from another group — deliberately:
   admitting a partial slice of a second settlement into a payout that is itself
   only half-observed stacks two speculative structures, and on seed 42 it was the
   sole source of spurious pairings. A proposer may be as narrow as it likes; the
   gate is what approves.

2. **The payout.** `is_plausible_payout` on the whole thing, before any split
   search runs, so a shape G3 would reject never costs a node.

3. **The division.** Which transactions sit behind which of the two credits. This
   is an unanchored subset-sum over the payout's own members, and it is where C3
   usually stops. On seed 42 the payout of `setl_0019` admits 6 divisions and the
   payout of `setl_0048` admits 279, so `resolve` withdraws approval and four of
   the six halves are refused. **That is not a limitation of the search — the input
   does not contain the answer.** A statement line records a credit, not which of
   the settlement's transactions the bank put into it, and two payments of the same
   net are interchangeable between the halves. Truth's `by_construction` uniqueness
   is an assertion about how the generator cut the payout, not a fact recoverable
   from the CSVs — the bank-line side of finding 8.4, and
   `docs/journal/stage-13.md` measures it.

   Step 1 can be undetermined the same way and independently: `setl_0101`'s
   residual of −₹999.00 is composed by either of two identical refunds, so *two*
   payouts are proposed. `bl_0101`'s half is the same under both and closes;
   `bl_9001`'s holds the stray, differs, and is refused. One pair, two outcomes,
   and both of them correct.

   The tempting move is a tie-break prior — "the first credit carries the earlier
   transactions" — and it was measured rather than argued about: ordering the payout
   by `settled_at` recovers truth's division on 1 of the 3 pairs, and by
   `created_at` on none. The only ordering that recovers all three is `entity_id`,
   which is the order the generator emitted them in and carries no accounting
   meaning whatever. §17: Milaan does not invent distinctions to break ties.

**Cost.** The pair loop is O(n²) over open lines, filtered to pairs inside the
window; the stray index is O(m²) over the *strays* in the joint pool, which is a
handful; the split search is bounded by `SUBSET_NODE_BUDGET` and refused outright
above `C2_MAX_POOL`, by §9.3's own information-theoretic argument — a division that
cannot be established at any node budget is not worth a search.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Mapping, Sequence

from core.coherence import MAX_STRAY_ITEMS, is_plausible_payout
from core.models import BankLine, GatewayTxn, settlement_members, target
from core.money import Paise, window_key
from core.subsetsum import (C2_MAX_POOL, SearchBudgetExceeded, count_exact,
                            solve_exact)
from matcher.proposers.base import Claim, Pool
from matcher.proposers.search_p import SETTLEMENT_WINDOW_DAYS, SUBSET_NODE_BUDGET


class SplitProposer:
    """C3. Emits ordinary `Claim`s and approves nothing.

    The whole search happens in `prepare`, once per tier sweep, because a pair is
    not a property of one line and the `Proposer` protocol is per-line (§7.2).
    `propose` then hands each line the claims the sweep planned for it — one if the
    division was determined, several if it was not, and `resolve` refuses those.
    """

    def __init__(self, txns: Iterable[GatewayTxn],
                 window_days: int = SETTLEMENT_WINDOW_DAYS) -> None:
        txns = list(txns)
        self.name = "C3"
        self.window_days = window_days
        self._txns = {t.entity_id: t for t in txns}
        self._members = settlement_members(txns)
        self._totals = {sid: sum(self._txns[e].net for e in group)
                        for sid, group in self._members.items()}
        self.plan: dict[str, list[Claim]] = {}
        # bank_line_id -> why the pair was found and not resolved. Typed
        # `SPLIT_PAYOUT` in the ledger (§10.1), which is the point of the tier even
        # on the lines it cannot close: the five it refuses on seed 42 were wearing
        # `UNIQUENESS_UNPROVEN` and `WITHHELD_RECORD` before it existed, and a
        # refusal with the wrong label sends a human looking for a missing record
        # that is not missing.
        self.refusals: dict[str, str] = {}
        # bank_line_id -> the other halves, and -> the settlements behind the pair.
        # Kept on the tier rather than on the `Claim`: they are how the refusal and
        # the ledger name the finding, and I9's discipline is that the claim carries
        # only what the gates read.
        #
        # **Sets, not single values, and the ten-seed regression is why.** One credit
        # can tie out jointly against more than one settlement and with more than one
        # partner — seed 99's `bl_9007` pairs with either `bl_0041` or `bl_9006`
        # across `setl_0085` and `setl_0106`. Holding the first of each made the
        # refusal sentence name one settlement while the ledger row named another,
        # and a refusal that misnames its own settlement is the failure stage 13
        # fixed once already on `bl_9001`.
        self.partners: dict[str, set[str]] = {}
        self._anchors: dict[str, set[str]] = {}
        # bank_line_id -> `(settlement_id, payout)` for every payout C3 proved
        # against this credit and its partner, and -> this credit's own target. Both
        # exist for one purpose: the refusal sentence names how many divisions
        # balance, and a number the search stopped counting at 2 is not that number
        # (`count_exact`).
        self._payouts: dict[str, set[tuple[str, tuple[str, ...]]]] = {}
        self._targets: dict[str, Paise] = {}
        # The census behind the refusal sentence, kept as numbers rather than only
        # as prose: `bank_line_id -> [(settlement_id, [divisions per payout])]`.
        # §13 sets the census as a *figure* on the board — "279" at display size
        # with the sentence under it — and a UI that had to regex it back out of
        # `evidence[0]` would be parsing three different sentence shapes to recover
        # a number this class already computed.
        self.census: dict[str, list[tuple[str, list[int]]]] = {}

    def prepare(self, order: Sequence[BankLine], pools: Mapping[str, Pool],
                claimed: frozenset[str], pass_no: int) -> None:
        """Plan every pair, then decide which lines it actually determined."""
        self.plan, self.refusals = {}, {}
        self.partners, self._anchors = {}, {}
        self._payouts, self._targets = {}, {}
        self.census = {}
        lines = sorted(order, key=lambda b: b.bank_line_id)
        self._targets = {b.bank_line_id: target(b) for b in lines}
        anchors = [(sid, group) for sid, group in sorted(self._members.items())
                   if not set(group) & claimed]
        for i, first in enumerate(lines):
            for second in lines[i + 1:]:
                if self._same_window(first, second):
                    self._pair(first, second, pools, anchors)

        # A refusal is recorded exactly where the division was *not* determined.
        # Set unconditionally it would say "unresolved" on the lines C3 closed, and
        # `unproven` in the trace is read as "this line has no answer" (§10.1).
        for bank_line_id, claims in self.plan.items():
            distinct = {frozenset(c.composition) for c in claims}
            if len(distinct) == 1:
                self.refusals.pop(bank_line_id, None)
            else:
                self.refusals[bank_line_id] = self._sentence(bank_line_id)

    def propose(self, line: BankLine, pool: Pool) -> list[Claim]:
        return self.plan.get(line.bank_line_id, [])

    # --- the pair search -----------------------------------------------------

    def _same_window(self, first: BankLine, second: BankLine) -> bool:
        """Could one payout have produced both credits? §2's window, on IST dates."""
        gap = (window_key(first.value_date, first.txn_date)
               - window_key(second.value_date, second.txn_date)).days
        return abs(gap) <= self.window_days

    def _pair(self, first: BankLine, second: BankLine, pools: Mapping[str, Pool],
              anchors: Sequence[tuple[str, tuple[str, ...]]]) -> None:
        joint = target(first) + target(second)
        strays = {t.entity_id: t
                  for t in (*pools.get(first.bank_line_id, ()),
                            *pools.get(second.bank_line_id, ()))
                  if t.settlement_id is None}
        reach = self._reach(sorted(strays.values(), key=lambda t: t.entity_id))
        seen: set[tuple[str, ...]] = set()
        for sid, group in anchors:
            for extras in reach.get(joint - self._totals[sid], ()):
                payout = tuple(sorted((*group, *extras)))
                if payout in seen:
                    continue
                seen.add(payout)
                if is_plausible_payout(payout, self._txns):
                    self._divide(first, second, sid, payout)

    def _reach(self, strays: Sequence[GatewayTxn]) -> dict[Paise, list[tuple[str, ...]]]:
        """`residual -> the stray subsets that compose it`, sizes 0 to G3's cap.

        Two identical refunds both compose the same residual, and that is a real
        ambiguity rather than an artefact — which of them the payout netted is not
        determined, so both payouts are proposed and `resolve` sees the tie.
        """
        out: dict[Paise, list[tuple[str, ...]]] = {0: [()]}
        for size in range(1, MAX_STRAY_ITEMS + 1):
            for combo in itertools.combinations(strays, size):
                out.setdefault(sum(t.net for t in combo), []).append(
                    tuple(t.entity_id for t in combo))
        return out

    def _divide(self, first: BankLine, second: BankLine, sid: str,
                payout: tuple[str, ...]) -> None:
        """Which of the payout's transactions each credit carried.

        Refused above `C2_MAX_POOL`: §9.3's bound is about unanchored subset-sum
        over a pool, and this is one. Above it every target has many
        representations, so a search would return a division whose uniqueness is
        unestablishable — not a match (§10.1).
        """
        if len(payout) > C2_MAX_POOL:
            self._refuse(first, second, sid, len(payout),
                         f"a division across {len(payout)} transactions cannot be "
                         f"established at any node budget (C2_MAX_POOL "
                         f"{C2_MAX_POOL}, §9.3)")
            return
        pool = [self._txns[e] for e in payout]
        try:
            halves = solve_exact(pool, target(first), SUBSET_NODE_BUDGET)
        except SearchBudgetExceeded as exc:
            self._refuse(first, second, sid, len(payout),
                         f"the division search exhausted the "
                         f"{SUBSET_NODE_BUDGET} node budget ({exc})")
            return
        for half in halves:
            rest = tuple(sorted(set(payout) - set(half)))
            # A division that gives one credit everything is not a division, and
            # the empty side would be rejected by G1 anyway.
            if not rest:
                continue
            self._claim(first, second, sid, tuple(sorted(half)), rest)
            self._claim(second, first, sid, rest, tuple(sorted(half)))
            for line in (first, second):
                self._payouts.setdefault(line.bank_line_id, set()).add((sid, payout))

    def _claim(self, line: BankLine, partner: BankLine, sid: str,
               mine: tuple[str, ...], theirs: tuple[str, ...]) -> None:
        self.plan.setdefault(line.bank_line_id, []).append(
            Claim(line.bank_line_id, mine, anchor_settlement_id=sid,
                  window_days=self.window_days, joint_with=theirs))
        self.partners.setdefault(line.bank_line_id, set()).add(partner.bank_line_id)
        self._anchors.setdefault(line.bank_line_id, set()).add(sid)

    def _refuse(self, first: BankLine, second: BankLine, sid: str, size: int,
                why: str) -> None:
        for line, partner in ((first, second), (second, first)):
            self.partners.setdefault(line.bank_line_id, set()).add(partner.bank_line_id)
            self._anchors.setdefault(line.bank_line_id, set()).add(sid)
            self.refusals.setdefault(
                line.bank_line_id,
                f"SPLIT_PAYOUT: {sid} ties to this credit and "
                f"{partner.bank_line_id} jointly across {size} transactions, but "
                f"{why}")

    def _census(self, bank_line_id: str) -> list[tuple[str, list[int]]]:
        """`[(settlement_id, divisions per payout)]` — how many sets balance, exactly.

        Not how many the search stopped at. `solve_exact` returns two and stops,
        because two is already a refusal, so the count it hands back says "at least
        2" whatever the truth is. The truth on seed 42 is that **279 divisions of
        `setl_0048`'s payout balance against `bl_0048`'s credit**, and that figure is
        the finding rather than a detail of it: it is the difference between "the
        search gave up" and "the source data does not contain the answer".
        `count_exact` is a census and proposes nothing, so counting past two costs no
        guarantee.

        Grouped by settlement and never summed. Two payouts can share a division, so
        a total would claim more distinct sets than exist; and a credit that ties out
        against two *different* settlements is a different finding again, which the
        sentence has to say rather than average over.
        """
        found: dict[str, list[int]] = {}
        target_paise = self._targets[bank_line_id]
        for sid, payout in sorted(self._payouts.get(bank_line_id, ())):
            found.setdefault(sid, []).append(
                count_exact([self._txns[e] for e in payout], target_paise))
        return [(sid, sorted(counts, reverse=True))
                for sid, counts in sorted(found.items())]

    def _sentence(self, bank_line_id: str) -> str:
        """§10's bar: name the missing input in one sentence.

        Three things can be undetermined, independently, and the sentence names
        whichever ones are: the **division** of one payout across the two credits;
        **which payout** it was, where two identical strays each compose the
        residual; and **which settlement or partner**, where a credit ties out
        jointly more than one way. `bl_0019` on seed 42 is the first, `bl_9001` the
        second, seed 99's `bl_0041` the third.
        """
        census = self._census(bank_line_id)
        self.census[bank_line_id] = census
        joint = " or ".join(sorted(self.partners.get(bank_line_id, ())))
        if len(census) == 1:
            sid, counts = census[0]
            who = f"{sid} ties to this credit and {joint}"
            what = (f"{counts[0]} divisions of the payout balance against this "
                    f"credit" if len(counts) == 1 else
                    f"{len(counts)} payouts of it tie out that way, dividing "
                    f"{' and '.join(str(c) for c in counts)} ways")
        else:
            who = (f"{len(census)} settlements "
                   f"({', '.join(sid for sid, _ in census)}) tie to this credit "
                   f"and {joint}")
            what = ", ".join(
                f"{sid} divides {' and '.join(str(c) for c in counts)} ways"
                for sid, counts in census)
        return (f"SPLIT_PAYOUT: {who} jointly to the paisa, but {what}, and the "
                f"statement does not say which of them this credit carried")
