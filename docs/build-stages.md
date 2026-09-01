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

## [ ] Stage 12 — detective

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

## [ ] Stage 13 — C3 pairwise split

> Read `@docs/spec.md` section 9.3, tier C3. For each unmatched settlement, test whether any
> two unmatched bank lines in the window jointly sum to its total.
>
> **This is first on the cut list.** If time is short, skip it and say so.

`git commit -m "stage 13: C3 pairwise split payout"`

---

## [ ] Stage 14 — regression and freeze

> Read `@docs/spec.md` section 11. Run ten seeds offline with **node budget only, no wall
> clock**, write `regression.json`, render it as a static table.
>
> Then stop building. Rehearse the live-seed run until it cannot fail.

**Done when:** `regression.json` shows mean ± σ recall across ten seeds, and three
consecutive live runs on judge-chosen seeds complete inside 60 s.

`git commit -m "stage 14: offline regression, freeze"`
