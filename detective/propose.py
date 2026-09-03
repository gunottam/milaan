"""`DetectiveProposer` — the fourth proposer. §9.6.

**One proposer among four, with no privileged path.** It implements the same
`Proposer` protocol as regex, lookup and search, and emits the identical frozen
`Claim`. `verify.check()` cannot tell its claims from an A1 hash hit, because
`Claim` carries no provenance field (I9) and this module never touches the
verification layer. The answer to "but your LLM creates candidates" is: yes, and so
does a hash lookup; neither approves anything.

That is also what makes the ablation a one-line filter rather than a special case —
`build_tiers()` either includes this proposer or it does not, and nothing else in
the ladder changes.

**Two passes, and they are shaped differently on purpose (§9.6).** Pass A reads
narration strings with no candidate context, batched 25, concurrent — the ~30%
unparseable rate is a pure text problem and candidates add nothing to it. Pass B
takes the residue with structured amounts and entity ids, batched 5, concurrent,
two rounds.

**Malformed hypotheses are counted, not raised.** A model can cite an entity that
does not exist, one already claimed, or a window past §15's cap. `to_claims()`
drops those and counts them; G1 catches anything that slips through (§7.4). A
rising count is a prompt-quality signal, and a run that died on a bad hypothesis
would have converted a partial answer into no answer.

**Sampling parameters, and why there is no `temperature=0` here.** The brief asked
for temperature 0 and that parameter no longer exists: `temperature`, `top_p` and
`top_k` are rejected with a 400 on current Claude models, so setting it would break
every request rather than pin them. The determinism the setting was for comes from
two things instead — `output_config.effort` at the low end, and strict structured
outputs, which constrain the response to `schema.py`'s shapes rather than asking
the prose nicely. Neither guarantees byte-identical output across runs; nor did
`temperature=0`, which is why §11 keeps the reproducible harness on node budget and
reports the model's contribution separately.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor

from core.models import BankLine, GatewayTxn
from detective import prompt as prompts
from detective.schema import (MAX_WINDOW_OVERRIDE_DAYS, PASS_A_SCHEMA,
                              PASS_B_SCHEMA, Hypothesis, Usage)
from matcher.proposers.base import Claim, Pool

# §15's batch sizes and round count.
LLM_PASS_A_BATCH = 25
LLM_BATCH_SIZE = 5
LLM_ROUNDS = 2
MAX_CONCURRENCY = 8          # §15 budgets 3 s to Pass A and 9 s to Pass B; the
                             # batches are independent, so the wall clock is the
                             # slowest batch rather than their sum.

MODEL = "claude-opus-5"
MAX_TOKENS = 16_000

# Cost, in **integer paise per million tokens** (I1). Claude Opus 5 lists at
# $5.00 / $25.00 per million input / output tokens; at ₹88.00 to the dollar that is
# ₹440.00 and ₹2,200.00, or 44_000 and 220_000 paise.
#
# Integer arithmetic, and the FX rate stated rather than fetched: §11 asks for cost
# per 1,000 records in paise, and a figure that moved with the spot rate would make
# two runs of the same seed incomparable. `Decimal` is confined to `core/fees.py`
# (I1), so the multiply below is `tokens * paise_per_mtok // 1_000_000` — truncating,
# which under-reports by at most one paise per line item and is the honest direction
# for a cost figure to be wrong in.
USD_INR_PAISE = 88_00                    # ₹88.00, stated. Verify before demo day.
PRICE_IN_PAISE_PER_MTOK = 5 * USD_INR_PAISE
PRICE_OUT_PAISE_PER_MTOK = 25 * USD_INR_PAISE
CACHE_READ_DIVISOR = 10                  # cache reads bill at ~0.1x input


def cost_paise(usage: Usage) -> int:
    """What a pass cost, in `int` paise (I1)."""
    return (usage.input_tokens * PRICE_IN_PAISE_PER_MTOK // 1_000_000
            + usage.output_tokens * PRICE_OUT_PAISE_PER_MTOK // 1_000_000
            + usage.cache_read_tokens * PRICE_IN_PAISE_PER_MTOK
            // (1_000_000 * CACHE_READ_DIVISOR))


def cost_per_1k_records(usage: Usage, records: int) -> int:
    """§11's `cost per 1k records`, in paise. Zero records is zero cost, not a
    division error — an ablated run has no usage and must still render."""
    return cost_paise(usage) * 1_000 // records if records else 0


class NoCredentials(RuntimeError):
    """No way to reach the API.

    **Raised on first use, never at construction, and caught by `prepare()`.** The
    first draft raised in `__init__`, which meant a missing key killed the whole
    run — and a run without the detective is perfectly viable: it is the ablated
    configuration, and §11 asks for it by name. So the tier constructs, the pass
    records a refusal, and the board reports deterministic recall with the model
    absent rather than reporting nothing at all.
    """


def available() -> bool:
    """Can this process call the API at all?

    An unset `ANTHROPIC_API_KEY` does not mean there are no credentials — the SDK
    resolves an `ant auth login` profile too, so the only honest check is whether
    the package imports and a client constructs.
    """
    try:
        import anthropic
    except ImportError:
        return False
    try:
        anthropic.Anthropic()
    except Exception:                      # noqa: BLE001 — any auth failure is a no
        return False
    return True


class DetectiveProposer:
    """Phase D. `name` is `"D1"` for Pass A and `"D2"` for Pass B.

    Two names because §9.6 is two passes with different inputs, different batch
    sizes and different destinations — and because the scoreboard reports per tier,
    so folding them into one row would hide §9.6's claim that Pass A is nearly free
    and delivers most of the lift.
    """

    def __init__(self, tier: str, txns: Iterable[GatewayTxn],
                 window_days: int = 2, *, client=None,
                 model: str = MODEL) -> None:
        if tier not in ("D1", "D2"):
            raise ValueError(f"tier must be D1 or D2, not {tier!r}")
        self.name = tier
        self.window_days = window_days
        self.model = model
        self._txns = {t.entity_id: t for t in txns}
        self._utr_to_settlement = {
            t.settlement_utr: t.settlement_id for t in self._txns.values()
            if t.settlement_utr and t.settlement_id}
        self.usage = Usage()
        self.hypotheses: list[Hypothesis] = []
        # Per instance, emphatically. A class attribute here would let D1 and D2 —
        # and two runs in one process — share each other's claims.
        self._claims_by_line: dict[str, list[Claim]] = {}
        # bank_line_id -> settlement ids Pass A recovered. Read by the orchestrator
        # and handed to C1: §9.1's amendment is that Pass A's product is an anchor,
        # and the recall it enables is booked as a C1 closure.
        self.recovered_anchors: dict[str, set[str]] = {}
        # bank_line_id -> why the gates rejected the last hypothesis, fed back into
        # round two (§9.6). Set by the orchestrator, not read from any verdict here.
        self.rejected: dict[str, list[str]] = {}
        # Same field name the search tiers expose, so the trace and the exception
        # ledger read a declined detective pass exactly as they read a declined C2.
        self.refusals: dict[str, str] = {}
        # Deferred. Constructing a client here would make a missing API key fatal
        # to the whole ladder — see `NoCredentials`.
        self._client = client
        self._client_failed = False

    def _client_or_raise(self):
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _build_client(self):
        try:
            import anthropic
        except ImportError as exc:
            raise NoCredentials(
                "the anthropic SDK is not installed; run the ladder without the "
                "detective (that is the ablated configuration) or "
                "`pip install anthropic`") from exc
        try:
            return anthropic.Anthropic()
        except Exception as exc:           # noqa: BLE001
            raise NoCredentials(
                "no API credentials resolved — set ANTHROPIC_API_KEY or run "
                "`ant auth login`") from exc

    # --- the Proposer protocol ---------------------------------------------

    def propose(self, line: BankLine, pool: Pool) -> list[Claim]:
        """The protocol's per-line entry point.

        **Batching happens in `run()`, not here.** §9.6 batches 25 narrations and 5
        hypotheses per call, and a per-line protocol method cannot batch — so this
        returns claims the batched pass already produced for that line, and the
        orchestrator calls `run()` once before the tier sweeps. That keeps the
        protocol identical to the other three proposers' while still making one
        call per batch rather than one per line.
        """
        return list(self._claims_by_line.get(line.bank_line_id, ()))

    # --- Pass A ------------------------------------------------------------

    def run_pass_a(self, lines: Sequence[BankLine]) -> list[Hypothesis]:
        """Narration strings only, batch 25, concurrent. Output feeds Phase A.

        Pass A's product is an *identifier*, which §9.1's amendment is emphatic is
        not a composition: a recovered UTR unlocks C1's anchored residual search,
        and the recall it enables is booked under C1 as a deterministic closure. So
        read the ablation delta as this pass's floor and report anchors recovered
        beside lines closed.
        """
        batches = [lines[i:i + LLM_PASS_A_BATCH]
                   for i in range(0, len(lines), LLM_PASS_A_BATCH)]
        out: list[Hypothesis] = []
        for readings in self._fan_out(
                [(prompts.PASS_A_SYSTEM, prompts.pass_a_prompt(b), PASS_A_SCHEMA)
                 for b in batches], effort="low"):
            for r in readings.get("readings", ()):
                kind = r.get("claim")
                if kind == "nothing_recoverable":
                    continue
                out.append(Hypothesis(
                    bank_line_id=r.get("bank_line_id", ""),
                    kind=kind if kind in ("narration_parse", "direct_link") else "",
                    reasoning=r.get("reasoning", ""),
                    extracted_utr=r.get("extracted_utr"),
                    settlement_id=r.get("settlement_id")))
        self.hypotheses += out
        return out

    # --- Pass B ------------------------------------------------------------

    def run_pass_b(self, lines: Sequence[BankLine],
                   pools: dict[str, list[GatewayTxn]],
                   round_no: int = 1) -> list[Hypothesis]:
        """The residue after Pass A. Structured amounts and entity ids, batch 5."""
        batches = [lines[i:i + LLM_BATCH_SIZE]
                   for i in range(0, len(lines), LLM_BATCH_SIZE)]
        builder = (prompts.pass_b_prompt if round_no == 1
                   else lambda ls, ps: prompts.round_two_prompt(ls, ps, self.rejected))
        out: list[Hypothesis] = []
        for body in self._fan_out(
                [(prompts.PASS_B_SYSTEM, builder(b, pools), PASS_B_SCHEMA)
                 for b in batches], effort="high"):
            for h in body.get("hypotheses", ()):
                out.append(Hypothesis(
                    bank_line_id=h.get("bank_line_id", ""),
                    kind=h.get("claim", ""),
                    reasoning=h.get("reasoning", ""),
                    candidate_ids=tuple(h.get("candidate_ids") or ()),
                    extra_terms=tuple(h.get("extra_terms") or ()),
                    window_override_days=h.get("window_override_days"),
                    partner_bank_line_id=h.get("partner_bank_line_id"),
                    settlement_id=h.get("settlement_id"),
                    break_type=h.get("break_type"),
                    blocked_on=h.get("blocked_on")))
        self.hypotheses += out
        return out

    # --- hypothesis -> Claim ----------------------------------------------

    def to_claims(self, hypotheses: Sequence[Hypothesis],
                  claimed: frozenset[str] = frozenset()) -> list[Claim]:
        """Convert what survives. **This is where malformed ones are counted.**

        Four rejections happen here rather than at G1, and each is a fact the model
        got wrong about the *world* rather than about the arithmetic:

        - an `unresolvable` claim, which is not a composition at all (§9.6) and
          goes to the ledger instead
        - a cited entity that does not exist in the export
        - a cited entity another line already claimed
        - a window override past §15's cap

        G1 re-checks all but the first (§7.4) and would reject them anyway. Counting
        them here too is not redundant: a claim dropped at G1 is invisible in the
        `MALFORMED_HYPOTHESIS` counter unless the conversion records it, and §9.6
        asks for the count.
        """
        claims: list[Claim] = []
        malformed = 0
        for h in hypotheses:
            settlement_id = h.settlement_id
            if h.kind in ("narration_parse", "direct_link"):
                # Pass A's product is an anchor. A repaired UTR is resolved against
                # the export here — the model names a string, not a settlement, and
                # a string that matches nothing is a malformed hypothesis rather
                # than an anchor nobody can use.
                if settlement_id is None and h.extracted_utr:
                    settlement_id = self._utr_to_settlement.get(h.extracted_utr)
                if settlement_id is None or settlement_id not in self._settlements:
                    malformed += 1
                    continue
                members = tuple(sorted(
                    e for e, t in self._txns.items()
                    if t.settlement_id == settlement_id))
                composition = members
                window = 0            # anchor members are exempt from the window
            elif h.kind == "subset_sum":
                composition = tuple(h.candidate_ids)
                window = (self.window_days if h.window_override_days is None
                          else h.window_override_days)
            else:
                # `unresolvable` and `split_across_cycles` are not compositions this
                # proposer can hand to `check()`. The first is a ledger row (§9.6);
                # the second needs C3, which is stage 13.
                continue

            if not composition or len(set(composition)) != len(composition):
                malformed += 1
                continue
            if not all(e in self._txns for e in composition):
                malformed += 1
                continue
            if any(e in claimed for e in composition):
                malformed += 1
                continue
            if not 0 <= window <= MAX_WINDOW_OVERRIDE_DAYS:
                malformed += 1
                continue

            claims.append(Claim(
                bank_line_id=h.bank_line_id,
                composition=composition,
                anchor_settlement_id=settlement_id,
                window_days=window,
                extra_terms=tuple(h.extra_terms)))

        self.usage += Usage(malformed=malformed)
        return claims

    @property
    def _settlements(self) -> frozenset[str]:
        return frozenset(t.settlement_id for t in self._txns.values()
                         if t.settlement_id)

    # --- the API call ------------------------------------------------------

    def _fan_out(self, requests: Sequence[tuple[str, str, dict]],
                 effort: str) -> list[dict]:
        """Every batch concurrently; one parsed body per batch.

        A batch that fails returns `{}` and is counted, never raised — §9.6 wants
        malformed hypotheses counted, and a pass that died on one bad batch would
        lose the good ones alongside it.
        """
        if not requests:
            return []
        with ThreadPoolExecutor(max_workers=min(MAX_CONCURRENCY, len(requests))) as ex:
            return list(ex.map(lambda r: self._call(*r, effort=effort), requests))

    def _call(self, system: str, user: str, output_schema: dict,
              *, effort: str) -> dict:
        """One request. Strict structured outputs; adaptive thinking.

        `output_config.format` constrains the response to the schema rather than the
        prompt asking for JSON and a parser hoping — a malformed hypothesis becomes
        a named validation outcome instead of a `JSONDecodeError` mid-run.

        The system prompt carries a cache breakpoint: it is byte-identical across
        every batch in a pass, so the second and later batches read it rather than
        paying for it. That is the whole of the caching strategy — the batch body
        varies, so nothing after it is cacheable.
        """
        try:
            response = self._client_or_raise().messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=[{"type": "text", "text": system,
                         "cache_control": {"type": "ephemeral"}}],
                thinking={"type": "adaptive"},
                output_config={"effort": effort,
                               "format": {"type": "json_schema",
                                          "schema": output_schema}},
                messages=[{"role": "user", "content": user}],
            )
        except NoCredentials:
            raise                          # `prepare()` types this apart
        except Exception as exc:           # noqa: BLE001 — counted, never raised
            self.usage += Usage(calls=1, malformed=1)
            self.refusals.setdefault(
                "_pass", f"MALFORMED_HYPOTHESIS: {type(exc).__name__}: {exc}")
            return {}

        u = response.usage
        self.usage += Usage(
            calls=1,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0)

        # A refusal is a content outcome on current models, not an exception: the
        # request returns 200 with an empty or partial body. Reading content[0]
        # unconditionally would break on it.
        if response.stop_reason == "refusal":
            self.usage += Usage(malformed=1)
            return {}
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            self.usage += Usage(malformed=1)
            return {}

    # --- what the orchestrator drives --------------------------------------

    def prepare(self, lines: Sequence[BankLine],
                pools: dict[str, list[GatewayTxn]],
                claimed: frozenset[str] = frozenset(),
                round_no: int = 1) -> None:
        """Run this tier's pass over the whole open board, once, before the sweep.

        The ladder calls this via `hasattr` — the same way it sets `deadline_ns` on
        the search tiers and reads their `refusals`. It exists because §9.6 batches
        25 narrations and 5 hypotheses per call while the `Proposer` protocol is
        per-line: batching cannot happen inside `propose()`, so the batched work
        happens here and `propose()` hands back what this produced for each line.

        Never raises. A pass that cannot reach the API records a refusal and leaves
        the board exactly as the deterministic ladder left it, which is the ablated
        configuration and already a supported outcome.
        """
        if not lines:
            return
        try:
            if self.name == "D1":
                found = self.run_pass_a(lines)
                for h in found:
                    if h.settlement_id or h.extracted_utr:
                        sid = h.settlement_id or self._utr_to_settlement.get(
                            h.extracted_utr or "")
                        if sid:
                            self.recovered_anchors.setdefault(
                                h.bank_line_id, set()).add(sid)
            else:
                found = self.run_pass_b(lines, pools, round_no)
        except NoCredentials as exc:
            # Not a model failure and not a malformed hypothesis — the pass never
            # ran. Typed apart so the ledger can say "the agent was absent" rather
            # than "the agent had nothing to offer", which score identically and
            # are not the same fact.
            for line in lines:
                self.refusals[line.bank_line_id] = (
                    f"DETECTIVE_UNAVAILABLE: {exc}")
            return
        except Exception as exc:           # noqa: BLE001 — counted, never raised
            self.usage += Usage(malformed=1)
            for line in lines:
                self.refusals[line.bank_line_id] = (
                    f"MALFORMED_HYPOTHESIS: the {self.name} pass failed "
                    f"({type(exc).__name__}); the board is unchanged")
            return
        self.load(self.to_claims(found, claimed))

    def load(self, claims: Sequence[Claim]) -> None:
        """Stage claims for `propose()` to hand back per line."""
        by_line: dict[str, list[Claim]] = {}
        for c in claims:
            by_line.setdefault(c.bank_line_id, []).append(c)
        self._claims_by_line = by_line
