"""G1-G4. §7.3 and §8 of the spec.

**A gate returns a rejection reason, or `None` for pass. It cannot express
approval.** That is I2 made structural rather than aspirational: a passing verdict
is unconstructible from here, because `Verdict` is not imported here at all. Only
`verify.check()` assembles one, and it is the only thing that can.

G3's decision is `core.coherence.is_plausible_payout` — the same function the
generator's uniqueness oracle applies (`generator/uniqueness.py::classify`). If the
two ever diverged, a second solution the oracle counted and the matcher rejects
would mark a line unresolvable in truth and score the matcher's correct answer as a
false positive. One implementation, imported twice.
"""

from __future__ import annotations

from collections.abc import Mapping, Set

from core.coherence import is_plausible_payout
from core.models import BankLine, GatewayTxn, target
from core.money import Paise, in_window, ist_date, window_key
from matcher.proposers.base import Claim

TOLERANCE_PAISE = 100           # §8.2 — ₹1.00
MAX_WINDOW_OVERRIDE_DAYS = 5    # §15 — cap on a model-supplied window override


def g1_exclusivity(claim: Claim, line: BankLine, txns: Mapping[str, GatewayTxn],
                   claimed: Set[str] = frozenset()) -> str | None:
    """Every cited entity exists, is unclaimed, and lies within the permitted window.

    Also where a hypothesis is validated (§7.4): a claim can cite entities that do
    not exist or are already spent, and G1 catches that before any solver runs.

    **Entities of `anchor_settlement_id` skip the window test.** Once the settlement
    id is known, membership is a fact rather than an inference (§9.3), which is what
    makes an on-hold release settled outside the window recoverable at C1 at all.
    This is the one place G1 is deliberately less restrictive than the window rule.
    """
    composition = claim.composition
    if not composition:
        return "empty composition"
    if len(set(composition)) != len(composition):
        return "composition cites the same entity twice"
    if not 0 <= claim.window_days <= MAX_WINDOW_OVERRIDE_DAYS:
        return (f"window of {claim.window_days} days is outside the permitted "
                f"0-{MAX_WINDOW_OVERRIDE_DAYS}")

    anchor = window_key(line.value_date, line.txn_date)
    for entity_id in composition:
        txn = txns.get(entity_id)
        if txn is None:
            return f"unknown entity {entity_id}"
        if entity_id in claimed:
            return f"entity {entity_id} is already claimed"
        if (claim.anchor_settlement_id is not None
                and txn.settlement_id == claim.anchor_settlement_id):
            continue
        if txn.settled_at is None:
            return f"entity {entity_id} has not settled"
        if not in_window(ist_date(txn.settled_at), anchor, claim.window_days):
            return (f"entity {entity_id} settled outside the "
                    f"{claim.window_days}-day window ending {anchor}")
    return None


def g2_delta(claim: Claim, line: BankLine, txns: Mapping[str, GatewayTxn]) -> Paise:
    """`Σ net_contribution(composition) − target(line)`. Zero is a proof; anything
    else falls to G4 (§7.3), so this rejects nothing on its own.

    `extra_terms` is deliberately not summed. A deduction sits on the transaction
    that incurred it (I7) — a settlement-level term would let a claim invent money
    to close its own gap. The field carries the model's *account* of the difference
    for the exception ledger, never an addend.

    Assumes G1 passed: an unknown entity raises here rather than balancing.
    """
    return sum(txns[e].net for e in claim.composition) - target(line)


def g3_coherence(claim: Claim, txns: Mapping[str, GatewayTxn]) -> str | None:
    """Is the composition the shape of a real payout? §9.4.

    A prior, not a proof. If it is wrong it rejects correct answers and costs
    recall; it cannot admit a wrong one. The reason string counts groups only to
    say *why* — the decision is the shared function's.
    """
    if is_plausible_payout(claim.composition, txns):
        return None
    if not claim.composition:
        return "empty composition"
    groups = {txns[e].settlement_id for e in claim.composition} - {None}
    strays = sum(1 for e in claim.composition if txns[e].settlement_id is None)
    return (f"spans {len(groups)} settlements and {strays} unassigned items; "
            "not the shape of a payout")


def g4_tolerance(claim: Claim, delta: Paise) -> str | None:
    """§8.2's double cap, applied only when G2 came up non-zero.

    The sole non-monotonic gate: every other gate can only cost recall, this one
    can admit a wrong answer. Both conditions, never either — ₹0.87 across three
    transactions is within ₹1 and is still a wrong subset, not rounding.
    """
    if abs(delta) > TOLERANCE_PAISE:
        return f"delta of {delta} paise exceeds the {TOLERANCE_PAISE} paise tolerance"
    if abs(delta) > len(claim.composition):
        return (f"delta of {delta} paise over {len(claim.composition)} transactions "
                "is more than one paise each; that is a wrong subset, not rounding")
    return None
