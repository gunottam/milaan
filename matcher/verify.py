"""`check()` — the only thing in the codebase that may approve a claim. I2.

The gate chain of §7.3, in order: G1 exclusivity, G2 arithmetic, G3 coherence, G4
tolerance. `check()` takes a frozen `Claim` and returns a `Verdict`; it cannot alter
the composition it was handed, and it cannot tell which proposer produced it. A hash
lookup and a model hypothesis walk the same four gates (I8) — a clean UTR hit that
does not balance is not a match.
"""

from __future__ import annotations

from collections.abc import Mapping, Set
from dataclasses import dataclass
from typing import Literal

from core.models import BankLine, GatewayTxn, target
from core.money import Paise
from core.proof import Proof, build_proof
from matcher.gates import (g1_exclusivity, g2_delta, g3_coherence, g4_outcome,
                           g4_tolerance)
from matcher.proposers.base import Claim


@dataclass(frozen=True)
class Verdict:
    """§7.2. Every field is explicit at every construction — `delta_paise` in
    particular has no default, because I6 is that no difference is ever silently
    absorbed, and a defaulted zero is exactly how one would be.

    `delta_paise` is G2's residual and `tolerance` is G4's verdict on it. They are
    separate fields because `gate="G4"` conflates two different facts: that the sum
    did not close, and that tolerance declined to rescue it. A residual of 4 paise
    across 3 transactions and one of ₹198 are both G4 rejections and only one is a
    near miss — stage 10 cannot diagnose a residual it cannot see, and stage 7
    cannot report exact against tolerance without it.

    `tolerance` is `None` when G4 was never consulted: either an earlier gate
    rejected the claim, or G2 closed exactly and there was nothing to relax.
    """

    ok: bool
    gate: str | None
    reason: str | None
    proof: Proof | None
    confidence: Literal["exact", "tolerance"] | None
    delta_paise: Paise
    tolerance: Literal["applied", "over_rupee_cap", "over_per_txn_cap"] | None


def _reject(gate: str, reason: str, delta: Paise,
            tolerance: str | None = None) -> Verdict:
    return Verdict(ok=False, gate=gate, reason=reason, proof=None,
                   confidence=None, delta_paise=delta, tolerance=tolerance)


def check(claim: Claim, line: BankLine, txns: Mapping[str, GatewayTxn],
          claimed: Set[str] = frozenset()) -> Verdict:
    """Run the gate chain. The only passing verdict in the codebase.

    G2 does not reject: a non-zero delta falls through to G4 (§7.3), which is the
    sole gate that can admit a wrong answer and therefore the only one whose
    approvals are stamped `confidence="tolerance"` and counted separately (§8.3).
    """
    reason = g1_exclusivity(claim, line, txns, claimed)
    if reason:
        return _reject("G1", reason, 0)

    delta = g2_delta(claim, line, txns)

    reason = g3_coherence(claim, txns)
    if reason:
        return _reject("G3", reason, delta)

    confidence: Literal["exact", "tolerance"] = "exact"
    outcome = None
    if delta != 0:
        outcome = g4_outcome(claim, delta)
        reason = g4_tolerance(claim, delta, txns)
        if reason:
            return _reject("G4", reason, delta, outcome)
        confidence = "tolerance"

    return Verdict(ok=True, gate=None, reason=None,
                   proof=build_proof(claim.bank_line_id, claim.composition, txns,
                                     target(line)),
                   confidence=confidence, delta_paise=delta, tolerance=outcome)
