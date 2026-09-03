"""The vendor boundary. Everything that knows *which* model provider is in use
lives in this file and nowhere else.

`DetectiveProposer` calls `LLMProvider.complete()` and never learns the vendor's
name, its endpoint, its pricing, or which of the two routes to structured output it
takes. That is the same containment the project applies to the answer key and to
`Claim`'s missing `source` field: a boundary is only real if the code on the other
side of it *cannot* see through, not merely if it currently does not look.

(The phrasing above is deliberate. I3's grep bans the bare word for the answer key
anywhere under `detective/` — including in prose — because a comment that names it
is one edit away from an import that reads it.)

**Two providers, reaching determinism by different routes.** Neither is a fallback
for the other; they are different bargains:

| | Anthropic | Groq |
|---|---|---|
| Determinism | `output_config.effort` — sampling parameters are **rejected with a 400** on current Claude models | `temperature=0`, which the endpoint accepts |
| Structured output | `output_config.format` with a `json_schema`, enforced server-side | `response_format={"type": "json_object"}` — JSON, but *any* JSON |
| Schema guarantee | the API constrains the response | **this module validates it, locally** |

The second row is the one that matters and it is why `GroqProvider` carries a
validator that `AnthropicProvider` does not need. Groq's JSON mode guarantees
parseable JSON and nothing about its shape: no `additionalProperties: false`, no
required fields, no types. A hypothesis with a misspelled key or a string where an
integer belongs would sail through as a dict and then fail somewhere downstream with
a `KeyError`. So every Groq response is checked against the same schema the
Anthropic path hands the server, and what fails is **counted as
`MALFORMED_HYPOTHESIS`, never raised** (§9.6).

If that count is high, it is a finding about the provider rather than a bug to
paper over, and `Usage.malformed` is where the board reports it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from dotenv import load_dotenv

# Read `.env` once, at import. `.env` is gitignored and `.env.example` carries the
# variable names with no values — a key in the repository is a key on the internet.
load_dotenv()

DEFAULT_PROVIDER = "groq"

# ₹ to the dollar, in paise, stated rather than fetched. §11 asks for cost per
# 1,000 records, and a figure that moved with the spot rate would make two runs of
# the same seed incomparable. Verify before demo day.
USD_INR_PAISE = 88_00


@dataclass(frozen=True)
class Rates:
    """Per-million-token prices in **micro-dollars**, converted to paise on use.

    Micro-dollars because published prices carry cents — Groq's input rate is
    $0.59/MTok, and a rate table in whole dollars could not hold it. Integers
    throughout (I1): `Decimal` is confined to `core/fees.py`, so the conversion is
    `micros * USD_INR_PAISE // 1_000_000`, truncating. That under-reports by at
    most a paise per term, which is the honest direction for a cost to be wrong in.
    """

    input_usd_micros_per_mtok: int
    output_usd_micros_per_mtok: int
    cache_read_divisor: int = 10

    def cost_paise(self, input_tokens: int, output_tokens: int,
                   cache_read_tokens: int = 0) -> int:
        def paise_per_mtok(micros: int) -> int:
            return micros * USD_INR_PAISE // 1_000_000
        return (input_tokens * paise_per_mtok(self.input_usd_micros_per_mtok)
                // 1_000_000
                + output_tokens * paise_per_mtok(self.output_usd_micros_per_mtok)
                // 1_000_000
                + cache_read_tokens * paise_per_mtok(self.input_usd_micros_per_mtok)
                // (1_000_000 * self.cache_read_divisor))


# Published list prices, per model. A model absent from its provider's table falls
# back to `UNKNOWN_RATES`, which prices at zero and says so on the board — a
# fabricated cost figure is worse than a visibly missing one.
RATES: dict[str, dict[str, Rates]] = {
    "anthropic": {
        # Claude Opus 5: $5.00 / $25.00 per MTok.
        "claude-opus-5": Rates(5_000_000, 25_000_000),
        "claude-sonnet-5": Rates(3_000_000, 15_000_000),
        "claude-haiku-4-5": Rates(1_000_000, 5_000_000),
    },
    "groq": {
        # Groq's catalogue and prices rotate faster than this repository does.
        # Treat every row as a config value to re-check, not a constant.
        "llama-3.3-70b-versatile": Rates(590_000, 790_000),
        "llama-3.1-8b-instant": Rates(50_000, 80_000),
        "openai/gpt-oss-120b": Rates(150_000, 750_000),
        "moonshotai/kimi-k2-instruct": Rates(1_000_000, 3_000_000),
    },
}
UNKNOWN_RATES = Rates(0, 0)

# Groq's default. A 70B instruct model is the right shape for this job: both passes
# are extraction against a fixed schema rather than open-ended reasoning, and the
# cheaper 8B model is measurably worse at holding a nested schema. Override with
# `GROQ_MODEL`.
GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
ANTHROPIC_DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 16_000


class NoCredentials(RuntimeError):
    """The selected provider cannot be reached.

    **Raised on first use, never at construction.** A run without the detective is
    §11's ablated configuration — a first-class, reported outcome — so a missing
    key degrades the board rather than killing the ladder. `prepare()` catches this
    and records `DETECTIVE_UNAVAILABLE` on every line, typed apart from
    `MALFORMED_HYPOTHESIS`: "the agent was absent" and "the agent had nothing to
    offer" score identically and are not the same fact.
    """


@dataclass(frozen=True)
class Completion:
    """One provider response, already parsed and already priced.

    `body` is `{}` when nothing usable came back. `failure` says why — an API
    error, an unparseable payload, a refusal — and the caller counts it.
    `dropped_items` is the schema-invalid items this module removed from an
    otherwise usable body, which is the Groq path's whole reason for existing.
    """

    body: dict
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_paise: int = 0
    failure: str | None = None
    dropped_items: int = 0


@runtime_checkable
class LLMProvider(Protocol):
    """One call, one parsed body, priced. The entire vendor surface.

    `effort` is a neutral "how hard should this think" hint, not a vendor parameter:
    the Anthropic path maps it to `output_config.effort`, and the Groq path ignores
    it because a temperature-0 chat completion has no equivalent knob. A protocol
    that exposed either vendor's spelling would leak the vendor.
    """

    name: str
    model: str

    def complete(self, messages: Sequence[dict], schema: dict, *,
                 effort: str = "medium") -> Completion:
        ...


# --- explicit schema validation, for the provider that needs it -------------


def _validator(schema: dict):
    from jsonschema import Draft202012Validator
    return Draft202012Validator(schema)


def _array_property(schema: dict) -> str | None:
    """The one top-level key holding the array of items, if there is one.

    Both pass schemas are a closed object wrapping a single array —
    `{"readings": [...]}` and `{"hypotheses": [...]}`. Finding it by shape rather
    than by name keeps the salvage below from knowing which pass it is validating.
    """
    props = schema.get("properties", {})
    arrays = [k for k, v in props.items() if v.get("type") == "array"]
    return arrays[0] if len(arrays) == 1 else None


def validate_or_salvage(body: dict, schema: dict) -> tuple[dict, int, str | None]:
    """`(body, dropped, failure)` — the Groq path's guarantee, applied locally.

    A whole-body rejection would throw away 24 good readings because the 25th had a
    misspelled key, so the body is salvaged per item: valid items are kept, invalid
    ones are dropped and counted. That is also what makes the malformed *rate*
    meaningful — it is per hypothesis, not per batch, so a rate is comparable
    across batch sizes.

    A body that is not even the right outer shape cannot be salvaged and comes back
    as a failure with an empty body.
    """
    if not isinstance(body, dict):
        return {}, 0, "response was not a JSON object"

    validator = _validator(schema)
    if not list(validator.iter_errors(body)):
        return body, 0, None

    key = _array_property(schema)
    if key is None or not isinstance(body.get(key), list):
        first = next(iter(validator.iter_errors(body)), None)
        reason = first.message if first is not None else "schema mismatch"
        return {}, 0, f"response does not match the schema: {reason}"

    # **An unexpected top-level key is not a batch with one bad item.** Salvaging
    # past it would silently discard whatever the model put there and proceed as
    # though the response were the one asked for — but a wrapper the schema does
    # not describe means the model answered a different question, so the items
    # inside it are suspect too. Reject the response and count its items.
    if schema.get("additionalProperties") is False:
        extra = set(body) - set(schema.get("properties", {}))
        if extra:
            return {}, len(body[key]), (
                "response carries top-level keys the schema does not allow: "
                + ", ".join(sorted(extra)))

    item_schema = schema["properties"][key].get("items", {})
    item_validator = _validator(item_schema)
    kept = [item for item in body[key] if not list(item_validator.iter_errors(item))]
    dropped = len(body[key]) - len(kept)

    salvaged = {key: kept}
    if list(validator.iter_errors(salvaged)):
        # Anything still wrong after salvage is structural, so there is nothing to
        # hand back even though some items were fine.
        return {}, len(body[key]), "response wrapper does not match the schema"
    return salvaged, dropped, None


# --- Groq -------------------------------------------------------------------


class GroqProvider:
    """Groq's OpenAI-compatible endpoint, via the OpenAI SDK with a `base_url`.

    The SDK rather than hand-rolled HTTP: retries, timeouts, connection pooling and
    error typing are already solved there, and a bespoke `requests` loop would be
    re-solving them worse.

    **`temperature=0`, which the Anthropic path cannot have.** Sampling parameters
    are rejected with a 400 on current Claude models, so that route reaches
    determinism through `output_config.effort` and a strict server-side schema
    instead. Same goal, different mechanism — see the module docstring's table.
    """

    name = "groq"

    def __init__(self, *, client=None, model: str | None = None) -> None:
        self.model = model or os.environ.get("GROQ_MODEL") or GROQ_DEFAULT_MODEL
        self.rates = RATES["groq"].get(self.model, UNKNOWN_RATES)
        self._client = client

    def _client_or_raise(self):
        if self._client is not None:
            return self._client
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            raise NoCredentials(
                "GROQ_API_KEY is not set — put it in .env (see .env.example) or "
                "export it. Without it the ladder runs deterministically, which is "
                "§11's ablated configuration")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise NoCredentials(
                "the openai SDK is not installed; `pip install -e '.[detective]'`"
            ) from exc
        self._client = OpenAI(api_key=key, base_url=GROQ_BASE_URL)
        return self._client

    def complete(self, messages: Sequence[dict], schema: dict, *,
                 effort: str = "medium") -> Completion:
        """One chat completion, JSON mode, then validated against `schema` here.

        `effort` is accepted and ignored: a temperature-0 completion has no
        equivalent knob, and silently mapping it to `max_tokens` or a prompt suffix
        would be inventing a vendor feature.
        """
        client = self._client_or_raise()
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=list(messages),
                max_tokens=MAX_TOKENS,
                temperature=0,
                response_format={"type": "json_object"},
            )
        except Exception as exc:           # noqa: BLE001 — counted, never raised
            return Completion({}, failure=f"{type(exc).__name__}: {exc}")

        usage = getattr(response, "usage", None)
        in_tok = getattr(usage, "prompt_tokens", 0) or 0
        out_tok = getattr(usage, "completion_tokens", 0) or 0
        priced = self.rates.cost_paise(in_tok, out_tok)

        choice = response.choices[0] if response.choices else None
        text = getattr(getattr(choice, "message", None), "content", None) or ""
        if getattr(choice, "finish_reason", None) == "length":
            # Truncated mid-JSON. Parseable-looking prefixes are the dangerous
            # case, so this is named rather than left to the decoder.
            return Completion({}, in_tok, out_tok, 0, priced,
                              failure="response hit max_tokens mid-JSON")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            return Completion({}, in_tok, out_tok, 0, priced,
                              failure=f"unparseable JSON: {exc}")

        body, dropped, failure = validate_or_salvage(raw, schema)
        return Completion(body, in_tok, out_tok, 0, priced,
                          failure=failure, dropped_items=dropped)


# --- Anthropic --------------------------------------------------------------


class AnthropicProvider:
    """Claude via the Anthropic SDK. Kept, and currently not the default.

    Retained rather than deleted because it is the other half of the comparison the
    module docstring makes: it is the path where the *server* enforces the schema
    and no local validator is needed, and having both in the tree is what makes
    that claim checkable instead of remembered.
    """

    name = "anthropic"

    def __init__(self, *, client=None, model: str | None = None) -> None:
        self.model = (model or os.environ.get("ANTHROPIC_MODEL")
                      or ANTHROPIC_DEFAULT_MODEL)
        self.rates = RATES["anthropic"].get(self.model, UNKNOWN_RATES)
        self._client = client

    def _client_or_raise(self):
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as exc:
            raise NoCredentials(
                "the anthropic SDK is not installed; "
                "`pip install -e '.[anthropic]'`") from exc
        try:
            self._client = anthropic.Anthropic()
        except Exception as exc:           # noqa: BLE001
            raise NoCredentials(
                "no Anthropic credentials resolved — set ANTHROPIC_API_KEY or run "
                "`ant auth login`") from exc
        return self._client

    def complete(self, messages: Sequence[dict], schema: dict, *,
                 effort: str = "medium") -> Completion:
        """One request. Strict structured outputs; adaptive thinking.

        No `temperature`: it is rejected with a 400 on current Claude models. The
        determinism it was for comes from `effort` at the low end plus
        `output_config.format`, which constrains the response server-side — so
        nothing here needs `validate_or_salvage`.
        """
        client = self._client_or_raise()
        system = "\n\n".join(m["content"] for m in messages
                             if m.get("role") == "system")
        turns = [m for m in messages if m.get("role") != "system"]
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=[{"type": "text", "text": system,
                         # Byte-identical across every batch in a pass, so batches
                         # 2..n read it rather than paying for it. The batch body
                         # varies, so nothing after it is cacheable.
                         "cache_control": {"type": "ephemeral"}}],
                thinking={"type": "adaptive"},
                output_config={"effort": effort,
                               "format": {"type": "json_schema", "schema": schema}},
                messages=turns,
            )
        except Exception as exc:           # noqa: BLE001 — counted, never raised
            return Completion({}, failure=f"{type(exc).__name__}: {exc}")

        u = response.usage
        in_tok = u.input_tokens
        out_tok = u.output_tokens
        cached = getattr(u, "cache_read_input_tokens", 0) or 0
        priced = self.rates.cost_paise(in_tok, out_tok, cached)

        # A refusal is a content outcome on current models, not an exception: 200
        # with an empty or partial body. Reading content[0] unconditionally breaks.
        if response.stop_reason == "refusal":
            return Completion({}, in_tok, out_tok, cached, priced,
                              failure="the model declined the request")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return Completion(json.loads(text), in_tok, out_tok, cached, priced)
        except json.JSONDecodeError as exc:
            return Completion({}, in_tok, out_tok, cached, priced,
                              failure=f"unparseable JSON: {exc}")


# --- selection --------------------------------------------------------------

PROVIDERS = {"groq": GroqProvider, "anthropic": AnthropicProvider}


def selected_name() -> str:
    """`DETECTIVE_PROVIDER`, defaulting to Groq.

    An unknown value is an error rather than a silent fall back to the default: a
    typo that quietly billed the wrong vendor would be discovered on an invoice.
    """
    name = (os.environ.get("DETECTIVE_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    if name not in PROVIDERS:
        raise ValueError(
            f"DETECTIVE_PROVIDER={name!r} is not one of {sorted(PROVIDERS)}")
    return name


def build_provider(name: str | None = None, **kwargs) -> LLMProvider:
    """The only place a provider is constructed."""
    return PROVIDERS[name or selected_name()](**kwargs)


def available(name: str | None = None) -> bool:
    """Can the selected provider actually be reached?

    Construction is cheap and credential-free by design, so this has to go as far
    as building the client — which is the only honest test. It never raises: an
    unknown `DETECTIVE_PROVIDER` is reported as unavailable here and as a
    `ValueError` to anyone who asks for it by name.
    """
    try:
        provider = build_provider(name)
        provider._client_or_raise()
    except Exception:                      # noqa: BLE001 — any failure is a no
        return False
    return True
