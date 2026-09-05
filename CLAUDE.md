# Milaan — project memory

Settlement reconciliation agent. Given a bank statement, a Razorpay gateway ledger and an
order list, it determines what composes every bank line, proves it to the paisa, and refuses
honestly when it cannot.

Full spec: `docs/spec.md` — frozen v1.3, **amended v1.3.1 (§18.1) and v1.3.2 (§18.2)**.
Read both before quoting §6.2, §8.2, §9.9, §11 or §15's budget table. Narrative + worked example: `docs/workflow.md`.
Build stages: `docs/build-stages.md`. **Read only the spec sections a stage names.**

---

## Verify before claiming done

**Run the suite inside `.venv`, and install it from `pyproject.toml` first.** The
venv has drifted twice — both times on packages nothing in this repo imports by
name (`httpx2`, which `starlette.testclient` needs; `jsonschema`, which the Groq
validator needs), and both times three test modules failed at *collection*, which
reads as broken tests rather than a broken environment. Numbers measured on the
system interpreter and numbers measured in the venv are not comparable, and stage
14's are the ones that go on a slide.

```bash
source .venv/bin/activate
pip install -e '.[detective,anthropic,api,test]'   # the declaration is the truth
python -c "import dotenv, jsonschema, openai, anthropic, fastapi, httpx2"
```

There is no `groq` package. Groq speaks the OpenAI wire format, so its client is
the OpenAI SDK with a `base_url` override — installing one hides the fact.

```bash
pytest -q                        # 17 s fast sweep — green before any stage is complete
pytest -q -m slow                # ~6 min, the 134-line seed-42 board. See below
pytest tests/test_invariants.py  # the invariant enforcement, run it constantly
pytest tests/test_subsetsum.py   # includes the brute-force property test
```

```bash
python -m scoring.regression          # THIRTY seeds -> regression.json. ~20 min cached, ~60 cold
python -m scoring.regression --table  # re-render the committed file, runs nothing
(cd web && node check-strip.mjs)      # the JSX structural claims, no browser, no jsdom
```

**Thirty seeds, not ten, since v1.3.2.** The ten were clean and the eleventh was not: twenty
fresh seeds produced four false matches in four different mechanisms. A precision figure that
holds on ten and breaks on the eleventh was never a precision figure. Adding seeds after
seeing their numbers would be the cardinal sin, so the thirty are fixed and every one is
reported — including the ones that still fail.

The regression's accuracy columns are **node budget only, no wall clock** — reproducible, so
a differing figure is a real change. Its `live s` column is the only clock in the file and it
is a property of this box and of Groq's queue, not of the method.

`pyproject.toml` applies `-m 'not slow'`, so **`pytest -q` does not run the measurements.**
The `slow` set is every test whose assertion lives on the full board — pinned tier counts,
recall figures, the anchor census, the committed-board residue gap and ledger. Six of them
run an uncapped ladder at ~45 s each. `tests/conftest.py` marks them automatically from the
fixture closure, so a new test that uses a board fixture is marked without anyone
remembering to.

Run the fast sweep constantly. **Run `-m slow` before committing a stage, and always if you
touched `matcher/`, `generator/` or `scoring/`** — a change that moves a measured count is
invisible to the fast sweep. Stage 14's regression must run it (`docs/build-stages.md`).

Never report a stage complete without running these. If a command could not be run, say so.

---

## Money

- **All money is `int` paise.** `Paise = int`. No floats anywhere outside `core/fees.py`.
- `Decimal` is permitted **only** in `core/fees.py` for rate multiplication.
- One rounding function: `round_paise()`, `ROUND_HALF_UP`. Do not use `round()`.
- Rounding is **per transaction, never on an aggregate**.
- GST is computed on the **already-rounded** fee. This order is load-bearing — reversing it
  makes `ROUNDING_DRIFT` unfireable.
- Display uses Indian digit grouping: `₹4,61,938.80`, never `₹461,938.80`.

## Time

All IST (+05:30). Window comparisons are on the **IST calendar date**. Window key is
`value_date`, falling back to `txn_date`.

---

## The invariants

| # | Rule |
|---|---|
| I1 | Integer paise. No floats outside `core/fees.py` |
| I2 | Only `verify.check()` may return `Verdict(ok=True)` |
| I3 | `detective/` has no reference to `truth` |
| I4 | Proposers emit `Claim`, never a verdict |
| I5 | Composition comparison is set equality. No partial credit |
| I6 | Every verdict carries `delta_paise`. Nothing is silently absorbed |
| I7 | Every deduction sits on the transaction that incurred it. No settlement-level terms |
| I8 | No tier returns a match without a balanced proof. Tiers **select**; gates **approve** |
| I9 | `Claim` is frozen and has **no `source` field**. `source` is on `MatchResult` only |
| I10 | `notes` and `description` never enter a prompt |

---

## Architecture

Two layers. Do not blur them.

**Proposers** (`matcher/proposers/`) create candidates: regex, lookup, search, detective.
All four implement the same `Proposer` protocol and emit an identical frozen `Claim`.

**Gates** (`matcher/gates.py`) approve them, in order:
`G1` exclusivity → `G2` arithmetic → `G3` coherence → `G4` tolerance.

**One pre-match exclusion**, in front of both layers (§3.2, §9.8, stage 15): a bank line with
a T+1 equal-and-opposite counterpart is a duplicate posting and its contra, so no tier is
offered either half. It is **not a gate** — it never sees a candidate, it decides what may be
proposed on. `matcher/run.py` calls `matcher/ledger.py::reversal_pairs` with no second
argument (every line); §10's typing pass calls the same function over the lines still open.
Excluded lines land on `Run.excluded` and are **not** `EXCEEDED_SEARCH_BUDGET` — nothing ran
out of time on them, they were never work.

`check()` cannot tell which proposer produced a claim. That is the point — keep it that way.

`G5` uniqueness lives in `matcher/uniqueness.py`, **not** in `check()`. It operates on the
*set* of passing verdicts for a line and never approves anything; it withdraws approval when
two verdicts tie.

**G4 is the only gate that can admit a wrong answer.** Every other gate can only cost recall.
Treat changes to it with suspicion.

**G4 needs a named cause, not just a small delta** (v1.3.2). The two caps bound how wrong a
match may be and say nothing about why; a thirty-seed sweep found two false matches that were
a *missing record* absorbed inside the band. The residual must also match one of
`matcher/gates.py::G4_EXPLAINS` — a term `diagnose` can name. `likely_specific_missing_record`
is excluded on purpose: accepting because the gap is the size of an unclaimed transaction is
absorbing the missing record.

**Greedy assignment can manufacture a false match, not only cost recall** (§18.2). An earlier
commit can consume the transactions of a second composition, so G5 has nothing to tie against
and a genuinely ambiguous line looks determined. §9.9 states the recall direction only. Seed
10's `bl_0002` is the case; the mitigation is measured and not built.

---

## Do not

- **Do not return the first solution found.** Search continues until a second is found or the
  space is exhausted. Two solutions means refuse. This is not an optimisation target.
- **Do not treat the node budget as a performance knob.** It determines whether the
  uniqueness guarantee holds. Lowering it converts proven matches into `UNIQUENESS_UNPROVEN`.
- **Do not add `source` to `Claim`** (I9), however useful it looks.
- **Do not re-implement the reversal-pair rule, and do not move it into a gate.** One
  function, two scopes (`reversal_pairs(lines)` pre-match, `reversal_pairs(lines, open_ids)`
  for typing). As a gate it would sit downstream of a composition that should never have been
  proposed, and `check()` would have to know why a line is not a payout.
- **Do not skip arithmetic on an identifier match.** A clean UTR hit that does not balance is
  not a match (I8). `bl_06` in `docs/workflow.md` is the case.
- **Do not absorb a delta into a "rounding adjustment"** outside G4's double cap.
- **Do not build SSE.** Polling at 500 ms is the design.
- **Do not add SQLite.** `data/runs/` plus a directory glob is the store.
- **Do not pair-score `SPLIT_PAYOUT`.** Measured at stage 14: 1 TP → 2 TP on seed 42, and
  declined. It needs C3 to commit a division the source data does not determine — two
  identical refunds per pair, so the committed division is a false match half the time.
  `docs/journal/stage-14.md` and `scoring/regression.py::SCORING_RULE`.
- **Do not let a break injector assert `uniqueness: "verified"`.** It is a claim about an
  enumeration, and `generator/uniqueness.py::audit_verified` will now catch one that never
  ran. A forced record may say a line is *unresolvable* — that needs no search — but not that
  it is uniquely determined.
- **Do not widen an enumeration to make an assertion pass.** The uniqueness audit runs §9.3's
  exact-then-tolerance rule because that is what the matcher runs. Exact-only refuses 150
  working `ROUNDING_DRIFT` lines; anything wider certifies the one that is broken.
- **Do not scaffold future stages.** Build only the stage you were given.
- **Do not write excessive comments.** Docstrings on public functions; skip narration.

## Where the numbers stand (stage 15)

`regression.json` is measured against the current matcher. `docs/journal/stage-15.md` has the
arithmetic; stage 14's table is superseded and must not be quoted.

- **Precision is 100.0% ± 0.0% on all ten seeds, 0 false matches.** Stage 14's three FP were
  all `DUPLICATE_CREDIT` and the pre-match exclusion removed them. All-lines recall
  **92.82% ± 1.42%**, headline **97.33% ± 1.90%**. The exclusion withheld 6 lines per seed —
  exactly the injected pairs, no collateral on any seed — and recall *rose*, because the
  transactions the duplicate consumed went back to the line that earned them.
- **§15's Phase D budget is not enforceable as written** — amended in the spec (v1.3.1)
  rather than fixed. The run deadline is checked between tiers and before each line, so it
  bounds every search tier; a batching tier does its work in `prepare()` and a batch in
  flight cannot be interrupted. Measured at 33.8 – 80.7 s with the model answering against
  12.5 – 24.2 s ablated. **Phase D closed zero extra lines on all ten seeds, so the demo runs
  `use_llm: false`** and the 60 s ceiling is asserted for that configuration only.
- **Groq's free tier caps tokens per day at 200,000**, and a ten-seed live pass exhausts it.
  A 429 is counted as a call, so `usage.calls > 0` does not mean the pass ran — read
  `detective_hypotheses` and `detective_unavailable` (`scoring/regression.py`) or the D-tier
  refusal strings. Stage 15's `regression.json` runs the live pass ablated by default, so its
  `live s` column has no model in it at all.

## Open, measured, not fixed

- **Enforcing §15's Phase D allocation** would need a per-tier deadline and a cancellable
  client, so `prepare()` abandons in-flight batches. Not built: D closes nothing, so the
  budget it would enforce is one nobody wants to spend. §15's v1.3.1 amendment states both
  options and which one ships.

## Style

- Python 3.11 (`from __future__ import annotations` at the top of every module),
  type hints on all public functions, `@dataclass(frozen=True)` for value types.
- Tests use plain `pytest`, no fixtures framework beyond `tmp_path`.
- Frontend: Vite + React, plain CSS with the tokens in `docs/spec.md` §13. No UI library.
