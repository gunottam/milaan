"""The proposal layer's whole vocabulary. §7.2 of the spec.

Anything may propose a candidate — regex, hash lookup, subset-sum, a model. They
all emit this one frozen type, so `verify.check()` cannot tell them apart. That is
I9, and it is enforced here by what the dataclass does *not* have: no provenance
field of any kind. Add one and someone will eventually write a gate that trusts
deterministic claims more than model ones, and the guarantee evaporates silently.

Provenance is stamped on the match result the orchestrator emits — output only.

Adding a proposer requires touching nothing in the verification layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from core.models import BankLine, GatewayTxn

Pool = Sequence[GatewayTxn]


@dataclass(frozen=True)
class Claim:
    """A candidate composition for one bank line. Frozen: the verification layer
    is handed this and cannot alter it, so "turn an invalid candidate into a valid
    one" is not an operation that layer can perform.

    `anchor_settlement_id` is set when the composition was reached through a known
    settlement. G1 reads it: once membership is a fact rather than an inference,
    the date window no longer applies to that settlement's own transactions (§9.3).

    `joint_with` is the other half of a `SPLIT_PAYOUT` (§5, tier C3): the entity ids
    the *partner* bank line consumes. It exists because a split payout is the one
    composition whose coherence cannot be judged from one bank line. `composition`
    stays what it always was — what **this** line consumes, and what G1's
    exclusivity test and G2's arithmetic run on — while G3 asks its question of
    `composition + joint_with`, because the shape a payout has to have is a
    property of the payout and not of either credit the bank split it into. A half
    on its own is a partial slice of a settlement and G3 refuses it by design; that
    refusal is correct and `joint_with` is what makes the pair expressible without
    weakening it.

    Like `anchor_settlement_id`, it is an assertion the claim makes and G1 checks
    what it can — the entities exist, sit in the window, and do not overlap
    `composition`. Neither field can create money: G2 sums `composition` alone.
    """

    bank_line_id: str
    composition: tuple[str, ...]
    anchor_settlement_id: str | None = None
    window_days: int = 0
    extra_terms: tuple[str, ...] = ()
    joint_with: tuple[str, ...] = ()


class Proposer(Protocol):
    """Creates candidates. Approves nothing."""

    name: str

    def propose(self, line: BankLine, pool: Pool) -> list[Claim]:
        ...
