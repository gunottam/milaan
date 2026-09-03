"""The five claim types, as strict JSON schemas. §9.6.

The model is handed a taxonomy that contains unsolvable break types, so it needs a
way to say "this cannot be composed" — that is the fifth claim, `unresolvable`, and
it is why the list is five rather than four. An accepted `unresolvable` is still not
a match (I4), so nothing here can approve anything.

**Strict JSON, not "please return JSON".** Every schema below sets
`additionalProperties: false` and lists its `required` fields, and `propose.py`
passes them through `output_config.format` — the API constrains the response to the
schema rather than the prompt asking nicely and a parser hoping. A malformed
hypothesis is then a *validation* failure with a name, not a `JSONDecodeError` in
the middle of a run.

**No field here carries a verdict.** A claim names entities, an identifier or a
break type; it never carries a delta, a confidence or an approval. I4 is enforced by
what these schemas cannot express.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# §9.6's five claim kinds, and where each one's output goes.
CLAIM_KINDS = ("narration_parse", "direct_link", "subset_sum",
               "split_across_cycles", "unresolvable")

RETURNS_TO = {
    "narration_parse": "Phase A",
    "direct_link": "Phase A",
    "subset_sum": "Phase C",
    "split_across_cycles": "C3",
    "unresolvable": "the exception ledger, typed",
}

# §15's cap. The detective may propose a wider window than the run's default; G1
# rejects anything past this, and the rejection is counted as MALFORMED_HYPOTHESIS
# (§7.4) rather than raised. Mirrored from `matcher.gates` rather than imported:
# `detective/` must not depend on the verification layer, or the two layers stop
# being separable and the ablation stops being a filter over `proposer.name`.
MAX_WINDOW_OVERRIDE_DAYS = 5


def _obj(properties: dict, required: list[str]) -> dict:
    """A closed object schema. `additionalProperties: false` and a complete
    `required` list are what `strict` structured outputs need to be enforceable."""
    return {"type": "object", "properties": properties,
            "required": required, "additionalProperties": False}


# --- Pass A: narration text only --------------------------------------------

# One entry per bank line in the batch. `extracted_utr` and `settlement_id` are
# both nullable because the honest answer to a blank narration is "nothing here",
# and a schema that forced a string would make the model invent one.
PASS_A_SCHEMA = _obj({
    "readings": {
        "type": "array",
        "items": _obj({
            "bank_line_id": {"type": "string"},
            "claim": {"type": "string", "enum": ["narration_parse", "direct_link",
                                                 "nothing_recoverable"]},
            "extracted_utr": {
                "type": ["string", "null"],
                # The model repairs the fragment; it does not get to invent one.
                # A UTR is `N` + bank code + yymmdd + sequence (§9.5).
            },
            "settlement_id": {"type": ["string", "null"]},
            "reasoning": {"type": "string"},
        }, ["bank_line_id", "claim", "extracted_utr", "settlement_id", "reasoning"]),
    },
}, ["readings"])


# --- Pass B: structured amounts and entity ids only -------------------------

PASS_B_SCHEMA = _obj({
    "hypotheses": {
        "type": "array",
        "items": _obj({
            "bank_line_id": {"type": "string"},
            "claim": {"type": "string",
                      "enum": ["subset_sum", "split_across_cycles", "unresolvable"]},
            "candidate_ids": {"type": "array", "items": {"type": "string"}},
            # §9.6 lists `extra_terms` on the subset_sum claim. It is carried to the
            # ledger and **never summed** (I7, and `g2_delta` says so at the point
            # it ignores the field): a settlement-level term would let a hypothesis
            # invent money to close its own gap.
            "extra_terms": {"type": "array", "items": {"type": "string"}},
            "window_override_days": {
                "type": ["integer", "null"],
                "minimum": 0, "maximum": MAX_WINDOW_OVERRIDE_DAYS,
            },
            "partner_bank_line_id": {"type": ["string", "null"]},
            "settlement_id": {"type": ["string", "null"]},
            "break_type": {"type": ["string", "null"]},
            "blocked_on": {"type": ["string", "null"]},
            "reasoning": {"type": "string"},
        }, ["bank_line_id", "claim", "candidate_ids", "extra_terms",
            "window_override_days", "partner_bank_line_id", "settlement_id",
            "break_type", "blocked_on", "reasoning"]),
    },
}, ["hypotheses"])


@dataclass(frozen=True)
class Hypothesis:
    """One parsed model claim, before it becomes a `Claim` or a ledger row.

    Frozen, and deliberately *not* a `Claim`: a hypothesis can be malformed —
    citing an entity that does not exist, a window past §15's cap, an empty
    composition — and the conversion is where those are counted (§7.4). A type that
    could only hold valid claims would have to raise on the invalid ones, and §9.6
    requires them counted rather than raised.
    """

    bank_line_id: str
    kind: str
    reasoning: str
    extracted_utr: str | None = None
    settlement_id: str | None = None
    candidate_ids: tuple[str, ...] = ()
    extra_terms: tuple[str, ...] = ()
    window_override_days: int | None = None
    partner_bank_line_id: str | None = None
    break_type: str | None = None
    blocked_on: str | None = None

    @property
    def returns_to(self) -> str:
        return RETURNS_TO.get(self.kind, "nowhere")


@dataclass(frozen=True)
class Usage:
    """Token accounting for one pass. Cost is `int` paise (I1).

    Kept as a value type rather than a running counter so the two passes can be
    reported apart: §9.6 claims Pass A is "nearly free" and delivers most of the
    lift, and a single total cannot show whether that held.
    """

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    malformed: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            calls=self.calls + other.calls,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            malformed=self.malformed + other.malformed,
        )


Pass = Literal["A", "B"]
