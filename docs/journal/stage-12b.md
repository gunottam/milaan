# Stage 12b — the first live run, and an ablation delta of zero

`pytest -q`: **211 passed in 9 s.** Four new tests. The detective ran against Groq
for the first time.

**Headline: the ablation delta is 0.00 points. Precision stayed 100%.**

| | closed | all-lines recall | precision | FN |
|---|---|---|---|---|
| deterministic (ablated) | 99 | 91.7% | 100.0% | 9 |
| with the detective | **99** | **91.7%** | **100.0%** | **9** |

Cost of the model run: **₹0.66 total, ₹0.21 per 1,000 records.**

That is the number stage 12 predicted — three addressable lines, six of nine FN
waiting on C3 — and the model closed none of the three. What the run bought instead
was four wire-level findings, three of which were bugs in my own code.

---

## What the mechanism actually did

It engaged. It did not silently no-op:

```
D1 anchors recovered            : 17 lines
   fed into C1.extra_anchors    : 17 lines
D1 claims that reached the gates: 3
D2 claims that reached the gates: 0
lines closed by D1/D2           : none
D2 hypothesis kinds             : {'unresolvable': 10}
```

Pass A recovered 17 settlement anchors and all 17 reached C1 through the
`extra_anchors` path §9.1's amendment asked for. Three became claims that walked
G1–G4. None closed a line, because the lines they anchored were already closed or
already refused for arithmetic reasons.

Pass B returned ten hypotheses and **every one was `unresolvable`** — the model
declining rather than guessing. Its reasons were correct on their own terms:

```
bl_9004  missing_transactions: unclaimed_pool is empty, no transaction IDs to match target
bl_9005  missing_transactions: unclaimed_pool is empty, no transaction IDs to match negative target
```

Those are the `DUPLICATE_CREDIT` reversal pairs, whose window pool genuinely is
empty. A refusal there is the right answer. **Zero fabricated compositions across
64 hypotheses** is the result I care about most: the gates were never asked to
reject a confident wrong answer, because none was offered.

---

## Four findings, in the order they surfaced

### 1. The default model 404s

```
NotFoundError: 404 — The model `llama-3.3-70b-versatile` does not exist
or you do not have access to it.
```

`GET /openai/v1/models` on this account serves 14 models and no Llama chat model
among them. The rate table's comment — *"Groq's catalogue and prices rotate faster
than this repository does"* — turned out to be describing the present, not a risk.

Default is now `openai/gpt-oss-120b`, chosen from what the account actually serves
and already priced in the table. `.env` had `GROQ_MODEL` pinned to the dead model;
I repointed it.

**The degradation worked.** A 404 was reported as `MALFORMED_HYPOTHESIS`, the board
rendered complete, and the deterministic result was untouched. That was the untested
claim from stage 12a and it now has a real failure behind it.

### 2. Groq rejects JSON mode unless the messages say "json"

```
400 — 'messages' must contain the word 'json' in some form,
to use 'response_format' of type 'json_object'.
```

An OpenAI-compatible quirk. Fixing it properly meant confronting something I had
underweighted: **JSON mode sends the server no schema at all.** The Anthropic path
hands `output_config.format` a real `json_schema` and the API constrains the
response; on Groq the only way the model can know the shape is to be told.

So `GroqProvider._messages_with_schema()` appends the serialised schema to the
system turn. `validate_or_salvage()` is the *enforcement*; the prompt is what gives
it something valid to accept. A validator that rejects everything is not a feature.

`AnthropicProvider` deliberately does not do this, and a test asserts it: passing a
schema twice — once properly, once as prose — is how prompts and contracts drift
apart.

### 3. `settlement_id` held a UTR, and my precedence was positional

This one cost 37 correct readings and is the most interesting.

`openai/gpt-oss-120b` copies the UTR into `settlement_id`:

```
bl_0000  utr=NHDFC26010100001  settlement_id=NHDFC26010100001
         utr_resolves=setl_0000   sid_real=False
```

Schema-valid, semantically confused. And my stage-12 `to_claims()` trusted
`settlement_id` and fell back to the UTR only when it was `null` — so the bogus id
won over the good UTR sitting beside it, and **every reading became a malformed
hypothesis.** The board showed 49% malformed on the first live run.

The fix resolves *both* fields and prefers whichever lands on a real settlement.
That is tolerance without a hole: an anchor still has to be a settlement present in
the export, and a test asserts an invented string in either field is still
malformed.

**The duplication was the actual bug.** The same precedence existed in two places —
`to_claims()` and `prepare()`'s anchor collection — so my first fix repaired the
symptom in one and left `recovered_anchors` handing C1 the bogus string. My own new
test caught it. Both now call one `_as_settlement()` resolver.

Malformed fell from **49% → 31%** on the fix.

### 4. Groq's JSON mode held the schema perfectly — 0 drops

The risk stage 12a was built around did not materialise on this model:

```
D1 batches                     : 4
D1 readings returned           : 70
dropped by the local validator : 0
```

Zero across every live batch. All 20 remaining malformed hypotheses are
`to_claims()` rejections — semantic, not structural.

**The validator stays**, and not out of sentiment: it is the reason I can state
"zero drops" as a measurement rather than an impression. A weaker model, a `.env`
pointing at `gpt-oss-20b`, or next quarter's catalogue could all change that number,
and the line on the board is where it would show up.

---

## The malformed rate, decomposed

31% of 64 hypotheses, and the split is the finding:

| kind | count | what it means |
|---|---|---|
| dropped by the local validator | **0** | Groq's JSON mode held the schema |
| `to_claims()` rejections | 20 | the model named something that does not resolve |

A rate reported as one number would have sent someone to fix the validator. It is
worth keeping the two apart on the board.

---

## Did the model read a transposed UTR?

Stage 12 identified Pass A's real population: four lines carrying a **transposed**
UTR, the one degradation §9.5's prefix cascade structurally cannot survive
(`startswith`, and a swap at position 6 breaks the prefix at position 6).

On a 7-line probe — 4 transpositions, 3 with the UTR dropped — the model got **3 of
4 transpositions and all 3 blanks**:

```
bl_0049 'NEFT-...-NHDFC62051600091-...' -> NHDFC26051600091  OK
bl_0052 'INSTSETL RZP NHDFC62052500097' -> NHDFC26052500097  OK
bl_0095 'IMPS/NHDFC26091900157/...'     -> NHDFC26091900175  OK
bl_0007 'MMT/IMPS/NHDFC26012200051/...' -> NHDFC26012200051  MISS (returned unrepaired)
```

So yes — the capability is real, and it is exactly the capability regex cannot have.
It changes no recall number, because all four of those lines already close at B1 or
C1. Stage 12 measured that and it still holds.

One observation worth recording: **batch size moved the answer.** At 7 lines the
model repaired transpositions; at 25 lines over the same population it returned
`nothing_recoverable` for 31 of 33. §15 sets `LLM_PASS_A_BATCH = 25`, and on this
model that is past where it stops doing the work. I have not changed the constant —
the spec sets it, the population it would help already closes, and re-tuning a spec
constant to improve a number that does not move recall would be tuning for its own
sake. Recorded as a finding for whoever revisits §15.

---

## What I did not wire, and why

§9.6 routes an `unresolvable` claim to the exception ledger, typed. It currently
stops at `to_claims()`, which returns no claim for it — so `break_type` and
`blocked_on` are discarded.

I left it, deliberately. The model typed those ten lines
`missing_transactions`; the ledger types them `DUPLICATE_CREDIT` on its own, via
§3.2's reversal-pair rule, and **the ledger is right**. Feeding the model's typing
in would have made exception typing accuracy worse on a metric §11 scores. The wire
is a small addition when the model's typing beats the ledger's on some population;
on this one it does not.

---

## Cost, live

18 calls, 8,899 input tokens, 8,740 output tokens:

```
D1   groq:openai/gpt-oss-120b    4 calls   4,125 in   7,098 out   ₹0.51   malformed 8
D2   groq:openai/gpt-oss-120b   14 calls   4,774 in   1,642 out   ₹0.15   malformed 12
cost ₹0.66 total, ₹0.21 per 1,000 records (§11, in paise)
```

For comparison, the same token counts on `claude-opus-5` would be **₹23.13** — a
factor of 34. The rate tables predicted an order of magnitude and a test asserts at
least 8×; the realised gap is wider because this board's output tokens outnumber its
input tokens, and output is where the two vendors diverge most.

Pass A cost 3.4× Pass B despite a third of the calls: it emitted 7,098 output tokens
against Pass B's 1,642, because it writes a `reasoning` string per bank line and
Pass B mostly declined in one sentence. §9.6 calls Pass A "nearly free"; on this
model and this board it is the expensive half. Worth knowing before anyone budgets
from the spec's prose.

---

## What is still unmeasured

- **Whether Pass B can close a line at all.** It offered ten refusals and zero
  compositions, so the subset-reasoning path has not been exercised on a line it
  could actually solve. The three addressable FN are all `unproven` lines whose
  window pools exceed `C2_MAX_POOL`; the model saw them and declined.
- **A second model.** Every number here is `openai/gpt-oss-120b`. `gpt-oss-20b` and
  the two qwen models are on the account and untried; the malformed rate in
  particular is a per-model figure.
- **The Anthropic path, live.** `ANTHROPIC_API_KEY` is set in `.env` but
  `DETECTIVE_PROVIDER=groq`, and the SDK is not installed. Switching providers is a
  one-line `.env` change plus `pip install -e '.[anthropic]'`.
