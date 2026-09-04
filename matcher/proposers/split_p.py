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
from core.subsetsum import C2_MAX_POOL, SearchBudgetExceeded, solve_exact
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
        # bank_line_id -> the other half, and -> the settlement behind the pair.
        # Kept on the tier rather than on the `Claim`: they are how the refusal and
        # the ledger name the finding, and I9's discipline is that the claim carries
        # only what the gates read.
        self.partners: dict[str, str] = {}
        self._anchors: dict[str, str] = {}

    def prepare(self, order: Sequence[BankLine], pools: Mapping[str, Pool],
                claimed: frozenset[str], pass_no: int) -> None:
        """Plan every pair, then decide which lines it actually determined."""
        self.plan, self.refusals = {}, {}
        self.partners, self._anchors = {}, {}
        lines = sorted(order, key=lambda b: b.bank_line_id)
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
                self.refusals[bank_line_id] = self._sentence(bank_line_id,
                                                             len(distinct))

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

    def _claim(self, line: BankLine, partner: BankLine, sid: str,
               mine: tuple[str, ...], theirs: tuple[str, ...]) -> None:
        self.plan.setdefault(line.bank_line_id, []).append(
            Claim(line.bank_line_id, mine, anchor_settlement_id=sid,
                  window_days=self.window_days, joint_with=theirs))
        self.partners.setdefault(line.bank_line_id, partner.bank_line_id)
        self._anchors[line.bank_line_id] = sid

    def _refuse(self, first: BankLine, second: BankLine, sid: str, size: int,
                why: str) -> None:
        for line, partner in ((first, second), (second, first)):
            self.partners.setdefault(line.bank_line_id, partner.bank_line_id)
            self._anchors[line.bank_line_id] = sid
            self.refusals.setdefault(
                line.bank_line_id,
                f"SPLIT_PAYOUT: {sid} ties to this credit and "
                f"{partner.bank_line_id} jointly across {size} transactions, but "
                f"{why}")

    def _sentence(self, bank_line_id: str, alternatives: int) -> str:
        """§10's bar: name the missing input in one sentence.

        "Sets of its transactions", not "divisions of the payout", because two
        things can be undetermined and the count covers both: the division of one
        payout across the two credits, and — where two identical strays each
        compose the residual — which payout it was. `bl_9001` on seed 42 is the
        second kind and `bl_0019` the first.
        """
        return (f"SPLIT_PAYOUT: {self._anchors[bank_line_id]} ties to this credit "
                f"and {self.partners[bank_line_id]} jointly to the paisa, but "
                f"{alternatives} different sets of its transactions balance "
                f"against this credit and the statement does not say which of "
                f"them this credit carried")
