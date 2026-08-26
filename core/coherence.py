"""G3 coherence. §9.4 of the spec.

One rule, one implementation. The generator's uniqueness oracle and the matcher's
gate chain both import this function: if the oracle counted a second solution the
matcher's G3 would reject, truth would mark the line unresolvable and the
matcher's correct answer would score as a false positive — the one number that
must read zero.

Imports nothing from `matcher/` or `generator/`, so neither can drift from it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping

from core.models import GatewayTxn

MAX_STRAY_ITEMS = 2     # §9.4: "one complete settlement + 1–2 items"


def is_plausible_payout(composition: Iterable[str],
                        txns: Mapping[str, GatewayTxn]) -> bool:
    """Is this composition the shape of a real payout?

    A payout is a whole settlement group, possibly plus a stray cross-cycle item
    or two. Razorpay does not assemble payouts from partial slices of three
    settlements — that rejection falls out of the arithmetic below, since three
    partial groups contribute at least three items.

    This is a **prior**, not a proof: an empirical claim about how payouts are
    assembled. If it is wrong it rejects correct answers and costs recall. It
    cannot admit a wrong one.

    `txns` is the whole known universe, not just the composition — completeness
    of a settlement group cannot be judged from the group's members alone.
    """
    chosen = list(composition)
    if not chosen:
        return False

    picked: dict[str, set[str]] = defaultdict(set)
    strays = 0
    for entity_id in chosen:
        txn = txns[entity_id]            # an unknown entity is G1's business, not G3's
        if txn.settlement_id is None:
            strays += 1
        else:
            picked[txn.settlement_id].add(entity_id)

    sizes = Counter(t.settlement_id for t in txns.values() if t.settlement_id in picked)
    complete = {sid for sid, ids in picked.items() if len(ids) == sizes[sid]}
    partial = [sid for sid in picked if sid not in complete]
    extras = strays + sum(len(picked[sid]) for sid in partial)

    if len(complete) > 1:
        return False                     # two whole payouts is a split, not a payout
    if complete:
        return extras <= MAX_STRAY_ITEMS
    # No whole group: only a handful of unassigned cross-cycle items, which is how
    # a chargeback debit or a stranded refund reaches the bank on its own (B2).
    return not partial and strays <= MAX_STRAY_ITEMS
