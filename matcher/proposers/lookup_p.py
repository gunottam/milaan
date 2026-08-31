"""Phase B — amount lookup, O(1) amortised. §9.2.

    B1  unclaimed settlement groups indexed by total; the bank target is a hash key
    B2  a single unclaimed transaction whose net equals the target exactly

**B1's ambiguity is finding 8.4's whole point.** Two unclaimed settlements with the
same total produce two candidates with no search involved, and v1.2's ambiguity
handling lived only in the search phase, so it would never have seen them. Nothing
special is needed here: the tier emits both claims, both balance by construction of
the index, and `matcher/uniqueness.resolve` refuses the pair. G5 arrives by the same
path a tied subset-sum takes, which is the point of keeping it set-level.

B2 takes the **signed** target (finding 8.1), so a chargeback posted as a bank debit
matches one `disp_*` with a negative net. No separate debit path.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from core.models import BankLine, GatewayTxn, target
from core.money import Paise
from matcher.proposers.base import Claim, Pool

SETTLEMENT_WINDOW_DAYS = 2      # §15, and the window B2's pool was built over


class LookupProposer:
    """B1 or B2 depending on `tier`. Both read the same settlement grouping, so one
    class holds it; tier-major ordering (§9.8) wants them as separate instances."""

    def __init__(self, tier: str, txns: Iterable[GatewayTxn],
                 window_days: int = SETTLEMENT_WINDOW_DAYS) -> None:
        self.name = tier
        self.window_days = window_days
        members: dict[str, list[GatewayTxn]] = defaultdict(list)
        for txn in txns:
            if txn.settlement_id is not None:
                members[txn.settlement_id].append(txn)

        self._members = {sid: tuple(sorted(t.entity_id for t in group))
                         for sid, group in members.items()}
        # total_paise -> {settlement_id}. Built once (§9.2); `release` removes on
        # claim in O(1) and nothing rebuilds it per pass.
        self._index: dict[Paise, set[str]] = defaultdict(set)
        self._total: dict[str, Paise] = {}
        for sid, group in members.items():
            total = sum(t.net for t in group)
            # §5.1: a settlement netting to zero produces no payout and therefore no
            # bank line, ever. It is not a candidate for anything.
            if total:
                self._index[total].add(sid)
                self._total[sid] = total

    def release(self, settlement_id: str) -> None:
        """Drop a claimed settlement from its bucket. O(1) — `_total` is what makes
        it a lookup rather than a scan over the index, and no pass rebuilds it."""
        total = self._total.pop(settlement_id, None)
        if total is not None:
            self._index[total].discard(settlement_id)

    def propose(self, line: BankLine, pool: Pool) -> list[Claim]:
        if self.name == "B1":
            return [self._group_claim(line, sid)
                    for sid in sorted(self._index.get(target(line), ()))]
        return [self._single_claim(line, txn) for txn in pool
                if txn.net == target(line)]

    def _group_claim(self, line: BankLine, settlement_id: str) -> Claim:
        # window_days=0: every cited entity is a member of the anchor settlement,
        # which G1 exempts from the window test, so no window is asserted.
        return Claim(line.bank_line_id, self._members[settlement_id],
                     anchor_settlement_id=settlement_id, window_days=0)

    def _single_claim(self, line: BankLine, txn: GatewayTxn) -> Claim:
        # No anchor: the transaction stands on its own, so G1 does apply the window
        # the pool was built over and the claim has to declare it.
        return Claim(line.bank_line_id, (txn.entity_id,),
                     anchor_settlement_id=None, window_days=self.window_days)
