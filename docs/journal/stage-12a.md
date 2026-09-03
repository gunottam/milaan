# Stage 12a — swapping the vendor without teaching the code about vendors

`pytest -q`: **206 passed in 9 s.** `pytest -q -m slow`: 72 passed. Thirty-two new
tests in `tests/test_provider.py`; `tests/test_detective.py` rewritten to inject a
fake *provider* rather than a fake vendor client.

New file: `detective/provider.py`. Plus `.env.example`, and `.env` in `.gitignore`.

**Not run against either API.** The key arrives after this lands. What a dry run
does and does not exercise is the last section.

---

## The boundary, and why it is the whole change

One file knows which vendor is in use. `DetectiveProposer` calls

```python
provider.complete(messages, schema, effort=...) -> Completion
```

and gets back a parsed body, token counts, and a cost already in paise. It never
learns the vendor's name, its endpoint, its pricing, or which of the two routes to
structured output was taken. `DETECTIVE_PROVIDER` selects Groq (default) or
Anthropic, and nothing in `propose.py`, `matcher/`, the scoreboard or the API moves.

The test file split follows the boundary, and that split is itself an assertion:

- `tests/test_detective.py` injects a **fake provider**. None of its 26 tests could
  tell you which vendor was selected — because the proposer cannot either.
- `tests/test_provider.py` injects **fake vendor clients** and checks each
  translation: what Groq is sent, what Anthropic is sent, how each prices a call.

`effort` stayed in the protocol because it is genuinely neutral — "how hard should
this think". Anthropic maps it to `output_config.effort`; Groq accepts and ignores
it, because a temperature-0 chat completion has no equivalent knob and silently
mapping it to `max_tokens` or a prompt suffix would be inventing a vendor feature.

---

## Two providers, two routes to determinism

This is the row that mattered, and it is why the two are not interchangeable
implementations of one idea:

| | Anthropic | Groq |
|---|---|---|
| Determinism | `output_config.effort` — sampling parameters are **rejected with a 400** | **`temperature=0`**, which the endpoint accepts |
| Structured output | `output_config.format` + `json_schema`, enforced **server-side** | `response_format={"type": "json_object"}` — JSON, but *any* JSON |
| Schema guarantee | the API constrains the response | **`provider.py` validates it, locally** |

Stage 12 could not set `temperature=0` and said so; the Groq path can and does.
Same goal, different mechanism — and neither is byte-exact across runs, which is
why §11 keeps the reproducible harness on node budget regardless.

The Groq path uses the **OpenAI SDK with a `base_url` override** rather than
hand-rolled HTTP: retries, timeouts, connection pooling and error typing are
already solved there. `openai` was already installed, so this added no dependency.

---

## The risk, and what was built for it

Groq's JSON mode guarantees *parseable* JSON and nothing about its shape — no
closed objects, no required fields, no types, no enums. A hypothesis with a
misspelled key or a string where an integer belongs arrives as a perfectly valid
dict and then fails somewhere downstream with a `KeyError`.

So every Groq response is validated against **the same schema the Anthropic path
hands the server**, using `jsonschema` (already installed — Draft 2020-12 honours
`additionalProperties: false`, `required`, `enum` and `minimum`/`maximum`, which is
the entire job). What fails is **dropped and counted as `MALFORMED_HYPOTHESIS`,
never raised** (§9.6).

### Per-item salvage, and why not whole-body rejection

A batch of 25 readings with one misspelled `claim` would, under strict whole-body
validation, cost all 25. So `validate_or_salvage()` validates the wrapper, then each
item, keeps the good ones and counts the dropped:

```
malformed 18 of 32 hypotheses offered (56%) — schema-invalid or unusable,
dropped and counted, never raised
```

That is also what makes the rate *a rate*: the denominator is hypotheses offered,
not batches, so it compares across batch sizes and across vendors. (The 56% above
is a dry run with a deliberately-broken canned response — it demonstrates the line
renders, not a measurement of Groq.)

**One case is not salvageable and should not be.** A body carrying a top-level key
the schema does not allow is rejected outright rather than having the extra key
quietly stripped. My first implementation salvaged past it, and the test I had
already written caught the difference: an unexpected wrapper means the model
answered a different question, so the items inside it are suspect too. Reject and
count.

`finish_reason: "length"` is named separately, because a JSON body truncated
mid-object is the dangerous case — a parseable-looking prefix — and leaving it to
the decoder would mistake it for a short answer.

---

## Cost survives the swap

Rates moved into `provider.py`, per vendor **and per model**, in
**micro-dollars per MTok** — because published prices carry cents and Groq's input
rate is $0.59/MTok, which a whole-dollar table cannot hold. Conversion is integer
throughout (I1): `micros * USD_INR_PAISE // 1_000_000`, truncating.

`Usage` gained a `cost_paise` field the provider fills, because the cost is now a
fact about the call. Recomputing it from token counts anywhere else would require
knowing the vendor — exactly what the boundary exists to prevent. `cost_paise(usage)`
as a module function is gone; `cost_per_1k_records()` stays and reads the field.

The same 1 M input / 100 k output tokens, priced both ways:

| provider | model | cost |
|---|---|---|
| Groq | llama-3.3-70b-versatile | **₹58.87** |
| Anthropic | claude-opus-5 | **₹660.00** |

A test asserts `dear > cheap * 8`, because the swap is a real change in the cost
picture and a silently equal figure would mean the rates were not being read.

**An unpriced model reports zero rather than a guess.** Groq's catalogue rotates
faster than this repository does, so a model absent from `RATES` runs and prices at
₹0.00 visibly — a fabricated cost figure is worse than a missing one.

---

## Invariants, unchanged and now checked on both paths

**I9** — `test_the_identity_holds_whichever_provider_produced_the_claim()` runs
stage 12's load-bearing assertion **twice, once per vendor**, and compares both
against a hand-built `Claim`:

```python
for name, v in verdicts.items():
    assert (v.ok, v.delta_paise, v.gate) == (
        hand_built.ok, hand_built.delta_paise, hand_built.gate), name
```

Same composition, same verdict, whichever vendor produced it — and neither is
distinguishable from a regex hit, because `Claim` still carries no `source`.

**I10** — `notes` and `description` reach no prompt on either path. The grep test
is unchanged; a new test drives a poisoned transaction through the Groq provider end
to end and asserts the string appears nowhere in the outgoing request, because a
vendor that reformatted messages could in principle reintroduce what `prompt.py`
excluded.

**I3 caught me.** The word *truth* appearing in `detective/provider.py`'s docstring
— in prose, describing the containment analogy — failed
`test_detective_cannot_reach_truth`. The grep bans the bare word anywhere under
`detective/`, including comments, and it is right to: a comment that names the
answer key is one edit away from an import that reads it. Reworded.

---

## Two bugs my own tests found

**1. A shadowed exception class.** `propose.py` still defined its own
`class NoCredentials(RuntimeError)` after importing the one from `provider.py`, so
`except NoCredentials` in `prepare()` was catching a *different* class than the
provider raised. A missing key fell through to the generic handler and was reported
as `MALFORMED_HYPOTHESIS` instead of `DETECTIVE_UNAVAILABLE` — the exact conflation
stage 12 wrote a test to prevent, reintroduced by a refactor. The test failed;
the duplicate class is gone.

**2. A misconfigured provider tracebacked out of the CLI.** Found by dry-running
the board with `DETECTIVE_PROVIDER=gorq`. The `model` property's fallback path
called `selected_name()`, which re-raised — and `model` is read *precisely* when a
pass did not run. Now `model` never raises, and a selection error becomes
`NoCredentials`, so a typo degrades the board instead of losing it:

```
D1   misconfigured   0 calls   0 in   0 out   ₹0.00   malformed 0
!! D1, D2 never ran — DETECTIVE_PROVIDER='gorq' is not one of ['anthropic', 'groq']
   This board is the ablated configuration (§11).
```

`selected_name()` still raises for anyone asking for a provider by name — a typo
that quietly billed the wrong vendor would be discovered on an invoice.

The banner reads the **actual** refusal reason rather than assuming "no key": "no
key" and "misconfigured provider" both stop the pass, and a board that guessed
between them would send someone looking in the wrong place.

---

## Configuration

`.env` is read once at `provider.py` import via `python-dotenv`. `.env` is
gitignored; `.env.example` is committed with the variable names and **no values**:

```
DETECTIVE_PROVIDER=groq
GROQ_API_KEY=
GROQ_MODEL=
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=
```

Every one is optional. With none set, the ladder runs deterministically — §11's
ablated configuration, a reported outcome rather than a failure.

`jsonschema` and `python-dotenv` became **hard** dependencies: the local validator
is the guarantee JSON mode does not give, and it has to run whether or not a key is
present. The vendor SDKs stayed optional extras (`[detective]` → `openai`,
`[anthropic]` → `anthropic`).

Default model is `llama-3.3-70b-versatile`. Both passes are extraction against a
fixed schema rather than open-ended reasoning, which is what a 70B instruct model is
for; the 8B is in the rate table for anyone who wants to trade accuracy for cost.

---

## What the dry run exercises, and what it cannot

**Exercised, with no network:** provider selection from env and its failure modes ·
Groq's request shape (`temperature=0`, `json_object`, `base_url`, messages passed
through) · Anthropic's request shape (system turn lifted, `effort`, server-side
schema, no `temperature`) · JSON parsing · **the local validator on all five failure
modes** (extra key, missing field, wrong type, bad enum, out-of-range integer) ·
per-item salvage · wrapper rejection · truncation · API errors · refusals ·
per-provider cost arithmetic · the unpriced-model path · cache-read pricing ·
`Usage` accumulation across passes · `cost_per_1k_records` · batching at 25 and 5 ·
two propagation rounds · the anchor path from Pass A into C1 · `to_claims`'s four
malformed cases · G1/G2/G3 on model-produced claims · the identity test on both
vendors · I10 on both vendors · `DETECTIVE_UNAVAILABLE` for a missing key, a
missing SDK and a bad provider name.

A full 134-line board driven through a fake Groq client: **18 calls (4 Pass A, 14
Pass B), 75,600 input tokens, ₹4.14, ₹1.37 per 1,000 records** — every number on
the ablation line rendered from real accumulation.

**Not exercised, and only a key can:**

1. **Whether Groq's JSON mode actually holds the schema.** The validator is built
   and tested against synthetic malformed bodies; the *rate* at which
   `llama-3.3-70b-versatile` produces them is unmeasured. That figure is the point
   of the malformed line, and if it is high it is a finding about the provider.
2. **Whether the model reads a transposed UTR.** Stage 12 measured Pass A's
   population as four lines — all transpositions, all already closing
   deterministically — so this changes no recall number either way, but it is the
   one thing Pass A exists for.
3. **The ablation delta.** Still unmeasured. Ceiling is unchanged from stage 12:
   three addressable lines, 2.8 points of all-lines recall, with six of the nine FN
   waiting on C3.
4. **Wire-level surprises** — auth errors, rate limits, `max_tokens` behaviour,
   whether Groq's usage block is shaped as assumed. Each is handled as a *reported*
   failure rather than an exception, so the first live run degrades rather than
   crashes, but "degrades correctly" is a claim I have tested against a fake and
   not against Groq.

To run it: put `GROQ_API_KEY` in `.env`, then

```bash
python -m scoring.score --run data/runs/seed42 --detective
```
