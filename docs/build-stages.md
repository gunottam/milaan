# Milaan — build stages

One stage per Claude Code session. `/clear` between stages. Commit after each.

Paste the prompt verbatim. Each names the spec sections to read — do not hand over the whole
spec, it is 1068 lines and most of it is irrelevant to any single stage.

Mark `[x]` when the stage's tests are green.

---

## [ ] Stage 1 — money and fees

> Read `@docs/spec.md` sections 2 and 4. Write `core/money.py` and `core/fees.py`, plus IST
> date helpers.
>
> **Write `tests/test_fees.py` first.** Include golden cases for: 2% card MDR with 18% GST on
> the rounded fee, 0% UPI, 3% international with FX markup folded into `fee_paise`, TDS at
> 0.1%, and the §4.3 allocation remainder being dropped by integer division. Assert
> `fmt_inr` produces Indian digit grouping.
>
> Then implement until green. Do not build anything else.

**Done when:** `pytest tests/test_fees.py` green, and a card payment of ₹12,000 yields
`fee=24000, tax=4320, tds=1200, net=1170480` paise.

`git commit -m "stage 1: money, fees, IST helpers"`

---

## [ ] Stage 2 — invariant enforcement

> Read `@docs/spec.md` section 0 and section 14. Write `tests/test_invariants.py` exactly as
> specified in §14 — five grep-based tests enforcing I1, I2, I3, I9, I10.
>
> These will fail for the modules that do not exist yet. Make them skip cleanly on a missing
> path rather than error, so they stay runnable through every later stage.

**Done when:** `pytest tests/test_invariants.py` green, and adding `x = float(1)` to
`core/money.py` makes it fail.

`git commit -m "stage 2: invariant grep tests"`

---

## [ ] Stage 3 — generator, uniqueness gate, property test

> Read `@docs/spec.md` sections 3, 4.3, 5.1, 6. Build `generator/` — entities, narration
> templates with degradation, `allocate.py`, and `generate.py` with the CLI flags in §15.
> Emit the three CSVs plus `truth.json` per §6.1.
>
> Then `generator/uniqueness.py` per §6.2, and `tests/test_subsetsum.py` containing the
> **brute-force property test from §6.3**: for pools of ≤18 items, random targets, assert the
> DFS and `itertools.combinations` return identical solution sets.
>
> No break injectors yet — clean data only.
> Also: `tests/test_fees.py` currently asserts against a local stand-in dataclass.
> Re-point every golden case at the real `core/models.py` type and confirm all 17
> still pass. A golden test asserting against a mock is worse than none.

**Done when:** `--seed 42` reproduces byte-identical output twice, the property test is green,
and `truth.json` records `uniqueness` for every resolvable line.

`git commit -m "stage 3: generator, truth, uniqueness gate, property test"`

---

## [ ] Stage 4 — break injectors

> Read `@docs/spec.md` section 5. Implement all 18 break injectors in `generator/breaks.py`.
> Each records itself in `truth.json.break_manifest`.
>
> Add a test asserting manifest counts match what was actually injected — a break that claims
> to fire but does not is worse than one that is missing.
>
> Pay attention to `ROUNDING_DRIFT` (§4.3 allocation, not "natural") and
> `NET_ZERO_SETTLEMENT` (§5.1, produces no bank line at all).

**Done when:** manifest counts verified, and `TARGET_AMBIGUOUS_RATE` lands near 0.08 across
five seeds.

`git commit -m "stage 4: 18 break injectors"`

---

## [ ] Stage 5 — protocol and gates

> **Use plan mode first.** Read `@docs/spec.md` sections 7 and 8. This stage sets the
> architecture; get the shapes right before writing bodies.
>
> Build `matcher/proposers/base.py` (`Proposer` protocol, frozen `Claim`), `matcher/gates.py`
> (G1–G4), `matcher/verify.py` (`check()`), `matcher/uniqueness.py` (G5, set-level).
>
> `tests/test_gates.py`: each gate rejects what it should. G1 rejects a stale entity, G2
> rejects a delta of 1 paise, G3 rejects a composition spanning three partial settlements, G4
> accepts 2 paise across 3 transactions and rejects 87 paise across 3.

**Done when:** `pytest tests/test_gates.py` green, `Claim` is frozen with no `source` field,
and `test_invariants.py` still passes.

`git commit -m "stage 5: proposer protocol, gates G1-G4, G5 uniqueness"`

---

## [ ] Stage 6 — Phase A and Phase B

> Read `@docs/spec.md` sections 9.1, 9.2, 9.5. Build `matcher/proposers/regex_p.py` (A1, A2,
> A3, prefix cascade) and `matcher/proposers/lookup_p.py` (B1 with the incremental index, B2
> including negative targets for debit lines).
>
> B1's index is `total_paise -> [settlement_id]`, built once, with O(1) removal on claim. No
> per-pass rebuild. B1 must apply G5 — two unclaimed settlements with the same total is an
> ambiguity with no search involved.

**Done when:** on clean stage-3 data, Phase A + B close most lines; the prefix cascade
resolves a collision via the exclusivity filter; a chargeback debit line matches at B2.

`git commit -m "stage 6: phase A identifier recovery, phase B amount lookup"`

---

## [ ] Stage 7 — scoring

> Read `@docs/spec.md` section 11. Build `scoring/score.py` and a CLI scoreboard printing
> precision, recall, TP/FP/FN/TN, and per-break recall.
>
> `excluded_from_scoring` lines are removed from all denominators.
> `EXCEEDED_SEARCH_BUDGET` and `UNIQUENESS_UNPROVEN` both score as FN.
>
> **Measure before optimising.** Print the baseline and stop.

**Done when:** a baseline number exists for Phase A + B only, and `tests/test_scoring.py`
covers each of TP, FP, FN, TN.

`git commit -m "stage 7: scoring against truth, baseline measured"`

---

## [ ] Stage 8 — Phase C search

> **Use plan mode first.** Read `@docs/spec.md` section 9.3 and 9.4. The longest stage.
>
> Build `matcher/proposers/search_p.py`: C1 anchored (window-independent), C2 unanchored with
> G3, and the tolerance second pass.
>
> The pseudocode in §9.3 is exact — reproduce it, including the sort tie-break on
> `entity_id`, the `len(solutions) >= 2` guard at the top of `dfs`, the pos/neg suffix arrays,
> and `remaining == 0 and chosen` so the empty subset never solves a zero target.
>
> The tolerance pass **records at interior nodes and keeps searching**, then takes the minimum
> `|delta|`. It does not accept the first qualifying node.

**Done when:** the property test still green, recall rises measurably over stage 7's baseline,
and a deliberately ambiguous line refuses instead of matching.

`git commit -m "stage 8: phase C anchored and unanchored subset-sum"`

---

## [x] Stage 9 — orchestration

> Read `@docs/spec.md` sections 9.8, 9.10, 15. Build `matcher/run.py`: tier-major ordering,
> sort by ascending pool size then `bank_line_id`, two propagation passes, run-level deadline
> with per-line `min(2000, remaining/unmatched)`.
>
> On deadline exhaustion: stop issuing work, mark unattempted lines
> `EXCEEDED_SEARCH_BUDGET`, still run the audit, and set a banner flag on the report. Never
> hang, never raise to the caller.

**Done when:** two runs on the same seed produce byte-identical reports, and an artificially
tiny deadline produces a partial report rather than a crash.

`git commit -m "stage 9: tier-major ordering, propagation, deadlines"`

---

## [x] Stage 10 — audit and diagnostics

> Read `@docs/spec.md` sections 9.7, 10, 10.2. Build `matcher/audit.py` (Phase E residue gap
> with the four-way partition, coherence audit) and `matcher/diagnose.py` (the six delta
> diagnostics).
>
> Then the exception ledger per §10, including the `AMBIGUOUS_EQUIVALENT` /
> `AMBIGUOUS_CONSEQUENTIAL` split and `UNIQUENESS_UNPROVEN`.

**Done when:** on data with one `WITHHELD_RECORD` injected, the residue gap equals that
record's net exactly. That single assertion is the strongest test in the suite.

`git commit -m "stage 10: phase E audit, delta diagnostics, exception ledger"`

---

## [x] Stage 11 — scoreboard UI

> Read `@docs/spec.md` section 13 and `@docs/spec.md` section 12 for the API. Build
> `api/main.py` (FastAPI, polling only) and `web/` (Vite + React).
>
> Ledger aesthetic, not dashboard: ruled rows, greenbar alternating tint, IBM Plex Mono
> tabular figures aligned on the decimal, no cards, no shadows. Light mode only.
>
> The proof strip expands **in place**, no modal, with a single rule above the total and a
> double rule below.

**Done when:** a run is triggerable from the browser, the residue gap shows in the header,
and clicking a closed row expands the arithmetic.

`git commit -m "stage 11: scoreboard, proof strip"`

---

## [x] Stage 12 — detective

> Read `@docs/spec.md` section 9.6. Build `detective/`: Pass A (narration strings only, batch
> 25, concurrent), Pass B (structured amounts and IDs, batch 5, 2 rounds), five claim types
> including `unresolvable`.
>
> I10: `notes` and `description` must not appear anywhere in `detective/`. Temperature 0,
> strict JSON. Malformed hypotheses are counted, not raised.
>
> Record token counts and cost **in paise**.

**Done when:** the ablation number appears on the scoreboard (deterministic vs full), and
`test_invariants.py` still passes.

`git commit -m "stage 12: detective pass A and B, ablation"`

---

## [x] Stage 13 — C3 pairwise split

> Read `@docs/spec.md` section 9.3, tier C3. For each unmatched settlement, test whether any
> two unmatched bank lines in the window jointly sum to its total.
>
> **This is first on the cut list.** If time is short, skip it and say so.

`git commit -m "stage 13: C3 pairwise split payout"`

---

## [x] Stage 14 — regression and freeze

> Read `@docs/spec.md` section 11. Run ten seeds offline with **node budget only, no wall
> clock**, write `regression.json`, render it as a static table.
>
> **Run `pytest -q -m slow` as part of this stage, not `pytest -q`.** Stage 11c split the
> suite: `pytest -q` is a 17 s sweep with `-m 'not slow'` applied from `pyproject.toml`, and
> the 72 tests it deselects are the ones whose assertions live on the full 134-line seed-42
> board — every pinned tier count, every measured recall figure, the anchor census, the
> committed-board residue gap and ledger. Those are exactly the numbers a regression exists
> to defend. A stage-14 run that shells `pytest -q` and sees green has checked the gates and
> the solver and none of the measurements.
>
> `regression.json` and the slow set answer different questions and both are required: the
> regression measures **variance across seeds**, the slow set pins **the committed seed at
> the offline budget**. A change that moves seed 42 and nothing else passes the first and
> fails the second.
>
> **Run the suite inside `.venv`, installed from `pyproject.toml`** — see CLAUDE.md. The venv
> has drifted twice and both times three test modules failed at *collection*, on packages
> nothing in the repo imports by name. Stage 14's numbers are the ones that go on a slide, and
> a number from the system interpreter is not the same number.
>
> **Pair-scoring a `SPLIT_PAYOUT`: MEASURED AND DECLINED.** Carried into this stage from
> stage 13 as required. It was measured first and then declined, and the measurement is the
> reason rather than the cost of building it — this entry stays here so somebody reading in
> order sees a decision instead of a vanished item.
>
> The proposal: for a line whose truth record has `split_partner`, TP iff the agent's
> composition **unioned with its composition for the partner** equals truth's union of the
> two. Stricter than the per-line rule on paper — every wrong composition is still FP and the
> union is exact — and it stops scoring the one thing the statement never recorded. It needs
> one change in C3 to be worth anything: where the payout is proved and the division is not,
> C3 must **commit some balanced division** rather than refuse, because a refused line
> contributes no composition to any union.
>
> **That change is the reason it is declined.** Measured on the committed board:
>
> | pair | distinct payouts C3 proposes | divisions of it | union rule reads |
> |---|---|---|---|
> | `bl_0048` + `bl_9003` | **1** | 279 | **2 TP** — the union is determined |
> | `bl_0019` + `bl_9002` | **2** | 6 | refuse — `rfnd_00560` and `rfnd_00567` both net −₹499.00, so *which* stray the payout netted is undetermined and the two unions differ |
> | `bl_0101` + `bl_9001` | **2** | 1 | refuse — same, `rfnd_02558` vs `rfnd_02564` at −₹999.00 |
>
> **The whole change is worth 1 TP → 2 TP on seed 42** — and `bl_0101` *loses* the TP it has
> today, because the pair it belongs to is undetermined at the payout level even though its
> own half is not. One line of recall, bought by making C3 commit a division that the three
> CSVs do not contain: two identical refunds sit behind each of the two ambiguous pairs, so
> the committed division is **a false match half the time by construction**. §1 prices those
> two outcomes and they are not close — a missed match costs a human minutes, a false match
> puts the books wrong silently and propagates to GST and revenue. §17: Milaan does not
> invent distinctions to break ties.
>
> `regression.json` and the scoreboard both name the rule that produced their numbers
> (`scoring/regression.py::SCORING_RULE`), so the declined change cannot be mistaken for a
> silent one later.
>
> **Ship the refusals instead, on the board, with their reason.** The claim is stronger than
> the recall point and it is checkable: `bl_0048` + `bl_9003` — *279 divisions of `setl_0048`'s
> payout balance against this credit, and the statement does not say which of them this
> credit carried.* `core.subsetsum.count_exact` censuses that exactly rather than reporting
> the two `solve_exact` stops at, because "the solver found two and gave up" and "the input
> does not contain the answer" are different findings and only one of them is true.
>
> Then stop building. Rehearse the live-seed run until it cannot fail.

**Done when:** `pytest -q` and `pytest -q -m slow` are green **inside `.venv`** (~6 min),
`regression.json` shows mean ± σ for all-lines recall, headline recall, precision and the
ambiguity rate across ten seeds with the per-seed spread visible beside the mean, the
`SPLIT_PAYOUT` refusals are on the board with their census, and the per-seed live wall clock
is measured against §15's 60 s ceiling on all ten seeds rather than assumed from seed 42.
Pair-scored `SPLIT_PAYOUT` is **declined**, recorded above and in
`docs/journal/stage-13.md`.

**Measured, and two of those criteria did not pass — see `docs/journal/stage-14.md`:**

- all-lines recall **92.6% ± 1.6%** (90.3% – 95.2%), headline recall **97.0% ± 2.0%**,
  ambiguity **7.5% ± 2.6%** (2.2% – 11.9%) across ten seeds, node budget only.
- **precision is 99.7% ± 0.4%, not 100.0% on every seed.** Seeds 7, 13 and 101 each book one
  false match and all three are `DUPLICATE_CREDIT`: the duplicate posting carries an
  identical narration, ref_no and amount, so whichever of the two credits §9.8's sort reaches
  first composes the settlement. Seed 42 is clean by a `bank_line_id` tie-break. One rule
  fixes it, it reuses `matcher/ledger.py::reversal_pairs`, and it is **not built here** — a
  matcher change inside the measurement stage is not a measurement.
- **§15's 60 s ceiling holds ablated and not with Phase D answering.** Ablated: 18.2 s ± 3.1 s,
  12.5 – 24.2 s, ten of ten inside. With the model answering (six seeds — the other four hit
  Groq's 200k daily token cap and returned 429 on every batch): 33.8 – 80.7 s, mean 56.2 s,
  **breaching on two of six**. The run deadline is checked between tiers and before each
  line, so it bounds every search tier and cannot interrupt a batch already in flight. Phase
  D closed **zero** extra lines on all ten seeds, for 297 paise — a floor, since four passes
  were refused.

`git commit -m "stage 14: offline regression, freeze"`

---

## [x] Stage 15 — the reversal-pair exclusion, and two amendments

**Read:** §1 (the monotonicity table), §3.2, §9.8, §15. `docs/journal/stage-14.md`.

One matcher change and two spec amendments. Nothing else — stage 14 left three findings and
this stage closes all three, two of them by writing down what is true rather than by building.

**The change.** `matcher/ledger.py::reversal_pairs` is promoted to a **pre-match exclusion**
in `run_ladder`: a bank line with a T+1 equal-and-opposite counterpart is a duplicate posting
and its contra, not a payout, so no tier is offered either half.

- **Reuse the existing rule.** One implementation, called with `open_lines=None` for the
  pre-match scope and with an explicit set by §10's typing pass. A second implementation is
  how the ledger and the matcher drift apart, which is what nearly happened between the
  generator and the matcher over coherence.
- **It is an exclusion, not a gate.** It runs in front of the ladder, decides only what may
  be proposed on, and never sees a candidate. G1–G4 and `check()` are untouched. By §1 it is
  monotonically restrictive, so a wrong pairing costs recall and cannot approve a wrong
  answer — which is the whole reason it is allowed to be a heuristic at all.
- **An excluded line is not `EXCEEDED_SEARCH_BUDGET`.** Nothing ran out of time on it; it was
  never work. It must not enter §9.10's banner.

**The amendments.** §15's 3 s + 9 s Phase D allocation is **not enforceable** by §9.10's
mechanism: there is one clock, it is checked between tiers and before each line, and a
batching tier does its work in `prepare()` where a batch in flight cannot be interrupted.
Record that in §15 rather than pretending the budget binds. And record that Phase D closed
**zero** extra lines on all ten seeds, so the demo runs `use_llm: false` — already the
default in `api/main.py` and `web/src/App.jsx`, now a measured decision rather than a
convenience.

**Then regenerate `regression.json` and the board.** Stage 14's committed numbers were
measured against a matcher with a known false match and must not be presented.

**Done when:** `pytest -q` and `pytest -q -m slow` are green inside `.venv`, precision reads
**100.0% on every one of the ten seeds**, recall is reported before and after so the
exclusion's cost is visible, and the real payout closes on seeds 7, 13 and 101 rather than
scoring FN.

**Measured — all three criteria pass:**

| | stage 14 | stage 15 |
|---|---|---|
| precision | 99.71% ± 0.44%, **3 FP** on seeds 7, 13, 101 | **100.0% ± 0.0%, 0 FP, ten of ten** |
| all-lines recall | 92.55% ± 1.59% (90.27 – 95.24) | **92.82% ± 1.42%** (90.83 – 95.24) |
| headline recall | 97.03% ± 1.97% (94.90 – 100.0) | **97.33% ± 1.90%** (94.90 – 100.0) |
| lines withheld | — | 60 across 10 seeds, **0 of them resolvable** |

- **The exclusion cost zero recall and bought some.** It withheld 6 lines per seed — exactly
  the three injected `DUPLICATE_CREDIT` pairs, on every seed, with no collateral — and recall
  *rose* on the three seeds that carried the false match: the transactions the duplicate had
  consumed went back to the line that earned them, so each of seeds 7, 13 and 101 turned one
  FN into a TP. `closed` is unchanged on all ten seeds, because the duplicate stopped closing
  and the real payout started.
- **Seed 42 is byte-identical**: 100 closed, 95.24% / 100.0%, 0 FP. It was clean before by a
  `bank_line_id` tie-break and it is clean now by a rule, which is the actual result — the
  headline was not earned at stage 14 and is earned now.
- **Nine `SPLIT_PAYOUT` refusals were about nothing, and this removed them.** Halves went
  61 → 52 across the ten seeds, on five of them, including two with no false match: C3 had
  been pairing a real credit with a duplicate posting, which ties out to the paisa because it
  is the same amount, and refusing the division. Nine of the halves under the board's refusal
  block were divisions of a settlement against a bank line that was never a payout. Nothing
  on the board would have surfaced that. `docs/journal/stage-15.md`.
- **§15's 60 s ceiling holds on all ten seeds in the shipped configuration** — Phase D off,
  which is what `use_llm: false` runs: **19.2 s ± 3.2 s, range 12.1 – 24.4 s**. Stage 14's
  with-model table stands as the reason it is asserted for that configuration only.

`git commit -m "stage 15: reversal-pair exclusion, precision 100% on ten seeds"`
