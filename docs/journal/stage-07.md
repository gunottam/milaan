# Stage 7 — scoring, and the baseline before Phase C

Written for someone who knows `docs/spec.md` and has not read the code.

Spec sections read: **§11** (scoring), plus stage 4's deferred list and §9.1's amendment.

`pytest -q`: **139 passed, 0 skipped.** Twenty-seven are new.

```
$ python -m scoring.score --run data/runs/seed42

MILAAN — scoreboard    data/runs/seed42    seed 42  noise high
══════════════════════════════════════════════════════════════════════════════
  134 bank lines · 3009 transactions · 64 closed · 70 open
  by tier   A1 40  A2 0  A3 4  B1 16  B2 4
  anchors recovered 93 (true anchor present 71, wrong 0, no true anchor 22) · lines closed 64
  uniqueness verified at 40,000,000 nodes  (the offline budget — comparable)

HEADLINE — verified-unique lines, plus refusals on lines nobody rigged
──────────────────────────────────────────────────────────────────────────────
  TP   57      FP    0      FN   35      TN   13
  precision 100.0%        recall  62.0%
```

**Precision 100.0%, recall 62.0%, on Phase A and Phase B alone.** No matcher change was
made to improve either number, which is the whole instruction for this stage.

---

## The composed finding

Stage 4: identifier recovery has to carry the load. Stage 6: an identifier is an anchor, not
a composition. Stage 7 scores both claims, and the FN population is the argument:

```
  35 headline false negatives, by the shape of the composition truth records
    one settlement group + 1 cross-cycle stray            23     (18 already anchored)
    one settlement group + 2 cross-cycle strays            9     ( 5 already anchored)
    two settlement groups, no strays                       3     ( 2 already anchored)
                                                          ──
                                                          35     (25 anchored)
```

**Every single missed line is C1's shape.** Not one is a parse failure, a wrong subset or an
arithmetic near-miss — the residual is always "this settlement, plus the one or two
cross-cycle items the payout netted". Stage 6 predicted 42 such lines from the trace; scoring
against truth says 35 of them are in the headline and 6 more are `SPLIT_PAYOUT` halves waiting
on C3.

And **25 of the 35 already have the anchor C1 needs.** The remaining 10 have no recoverable
identifier, which is exactly the population §9.6's Pass A exists for. So the recall gap
partitions into two tiers that do not yet exist, in a known ratio, with no residual category
of "we do not know why this failed". That is a better thing to have measured than a higher
number.

### The prediction, recorded before stage 8 is written

Because the gap is known rather than residual, the endpoint is predictable. Writing it down
now is the point: a number predicted from stage-7 measurements and then hit is evidence the
system is understood, and one that is missed is evidence worth more than the number would have
been.

**Prediction 1 — C1 alone takes headline recall to ~89%.** The 25 anchored FN need no
identifier work and no search over an unknown pool: the settlement is known, so C1 seeds it and
searches only the residual, which is one or two cross-cycle strays. Closing all 25:

```
  headline now      TP 57   FP 0   FN 35   TN 13     recall 62.0%
  headline after    TP 82   FP 0   FN 10   TN 13     recall 89.1%      <- prediction
```

**Prediction 2 — the remaining 10 are Pass A's, and 2 of them are Pass A's alone.** All ten
have no recoverable identifier. Eight have their true composition inside the window pool, so
C2 could in principle reach them; two do not — `TIMING_SHIFT` and `ONHOLD_RELEASE` put a member
outside the window, and §9.3 is explicit that only an anchor makes membership a fact rather
than an inference. No amount of unanchored search reaches those two.

**Prediction 3 — C2 will attempt all 35 and close few.** Every one of these lines has a window
pool of 23–32, under `C2_MAX_POOL = 35`, so C2 does not refuse them by rule. Stage 4's
pigeonhole finding says what happens instead: at a pool of ~28 over a ~₹3 lakh spread there are
vastly more subsets than attainable sums, so most targets have several representations and G5
refuses. **The expected C2 outcome on this data is refusals, not closures** — visible as a jump
in G5 refusals with recall barely moving. If C2 closes a large share of the 35 instead, stage
4's finding is wrong and should be revisited rather than quietly enjoyed.

**What that does to the pitch's ablation claim.** The original pitch guessed 71% deterministic
→ 94% with the agent. The measured shape is different and less flattering to the model:
deterministic gets to about **89%**, and the model's territory is the last ten lines, ~11
points, of which two are reachable by nothing else. §9.1's amendment already said the ablation
delta understates Pass A because its recall books as C1 closures under a deterministic tier —
this is that effect sized before the detective exists. The honest claim is *"deterministic
reconciliation gets to ~89%; the model recovers identifiers on the lines where the narration
was destroyed, and C1 does the arithmetic."*

**Two things that will move these numbers and are not being predicted.** Stage 9 replaces the
single-pass ladder with tier-major ordering and two propagation passes, and assignment is
greedy (§9.9) — a C1 closure consumes transactions another line needed. Read 89.1% as the
prediction for C1's reach, not as a forecast of the stage-9 board.

### What precision at 100% does and does not say

Zero false positives across all 134 lines, including the 16 `AMBIGUOUS_SUBSET` lines where a
match would be a fabricated answer to a question truth says has two. That is the number the
design exists to protect and it should be read with §11.1 next to it: on real data this is
unmeasurable, because a merchant with an answer key would not need the tool.

It is also a number Phase A and B make easy. Both propose whole settlement groups by
construction, so the gate chain has had very little that is wrong to reject — G3 has fired
once in two stages. **C2 in stage 8 is the first tier that can propose an arbitrary subset,
and it is the first real test of whether precision survives.** Reporting 100% now without
saying that would be setting up a regression to look like a failure.

### Two numbers that flatter the agent, named rather than left to be found

A caveat under a table is not enough — a regression table two stages from now will show a green
and nobody will read the caveat. So the manifest carries the distinction as data, and the board
prints it as a column:

```
  code                        inj lines match refuse   recall         at risk  note
  DUPLICATE_CREDIT              3     6     0      6   100.0%               —  refusal-only
  WITHHELD_RECORD               4     4     0      4   100.0%               —  refusal-only
  TIMING_SHIFT                  6     6     0      1    16.7%    ₹3,49,640.61  refusal-only
  NET_ZERO_SETTLEMENT           2     0     0      0        —               —  no bank line
  ORPHAN_ORDER                  6     0     0      0        —               —  no bank line
```

`caught` now splits into **`caught_by_match`** — a composition proved to the paisa — and
**`caught_by_refusal`** — a line truth calls unresolvable that nothing proposed. Both score
identically under §11 and only one of them is a rule doing work.

- **`DUPLICATE_CREDIT` scores 6 of 6, entirely by refusing.** §3.2's reversal-pair detection is
  unimplemented; truth marks both halves `resolvable: false`; refusing them scores TN. **The
  absence of the rule scores exactly as well as its success would.**
- **`WITHHELD_RECORD` is also refusal-only, and that one is correct.** §5 says it must remain an
  exception; there is nothing to compose. Scoring cannot tell the two cases apart — that needs
  exception typing, which is stage 10 — so `scored_by_refusal` flags both and the footnote names
  which is which. A flag that silently forgave `WITHHELD_RECORD` would be a judgement encoded in
  the scorer.
- **`TIMING_SHIFT` reads 16.7% and its one caught line is a refusal.** The split turns that row
  from "nearly all missed" into "not one composition proved" — a stronger and more useful
  statement, and it is only visible because match and refuse are separate columns.
- **`NET_ZERO_SETTLEMENT` and `ORPHAN_ORDER` produce no bank line at all** — 2 and 6 injections,
  0 lines each, flagged `no_bank_line`. Their recall is `—`, not 0% and not 100%: §5.1's whole
  point is that a net-zero settlement has no payout to reconcile, and `ORPHAN_ORDER` is §3.3's
  order tie-out, which is stage 10's. A dash alone reads as a miss; the flag says why there is
  nothing there.

---

## Files

### `scoring/score.py` — §11

Four public functions and a `Report`. `outcome()` is six lines and is the entire §11 rule:

```python
if record["resolvable"]:
    if composition is None: return "FN"
    return "TP" if set(composition) == set(record["composition"] or ()) else "FP"
return "FP" if composition is not None else "TN"
```

`EXCEEDED_SEARCH_BUDGET` and `UNIQUENESS_UNPROVEN` both score FN with **no special case**, and
that is the point rather than an economy: both are states in which no composition was
approved, so both arrive here as `None`. An answer whose uniqueness was never established is
not a match, and a scorer that needed to name the exception type to get that right would be a
scorer that could be taught to forgive one.

`score()` takes `bank_line_id -> composition` and nothing else. Not the tier, not the
confidence, not the proof. Which proposer produced an answer cannot change whether it is right
(I9), so it is not an input to the thing that decides.

### The five buckets, and why nothing is "excluded"

§11 says `excluded_from_scoring` lines leave every denominator. Stage 4 removed that flag from
the generator, because the lines it hid — the ones whose uniqueness the solver could not settle
— are the *hardest* lines, and dropping the hardest lines inflates recall. So every line is
scored, and the ones outside the headline are named:

| bucket | seed 42 | outcome |
|---|---|---|
| `headline` | 105 | TP 57 · FP 0 · FN 35 · TN 13 |
| `unproven` | 3 | TP 3 — composition known, uniqueness is not |
| `by_construction_c3` | 6 | FN 6 — `SPLIT_PAYOUT` halves, until stage 13 |
| `by_construction_single` | 4 | TP 4 — the `DISPUTE_DEBIT` singles B2 closes |
| `emergent` | 16 | TN 16 — `AMBIGUOUS_SUBSET`, refused 16 / matched 0 |
| `excluded_from_scoring` | 0 | the path stays proven; the flag is gone |

`bucket()` is total: every line lands in exactly one, and a test asserts the six sum to 134.
The headline holds `uniqueness: "verified"` lines **and** the 13 unresolvable lines nobody
rigged — the withheld records, the duplicate credits, the contaminated settlements. Those are
where the headline's TN come from, and without them precision would be measured over resolvable
lines alone, where a fabricated match on an unresolvable line would cost nothing.

The 16 ambiguous lines are held out of the headline because stage 4 put them there, but they
are the **true-negative class**: 16 refusals on data nobody rigged is the only evidence G5 does
anything. Folding them into the headline would raise TN to 29 and make precision look better
for a reason that has nothing to do with precision.

### Per-break recall, and three numbers that are not one number

`break_manifest`'s `caught` and `missed` are filled per **bank line**, not per injection:

```
  code                        inj lines match refuse   recall         at risk  note
  TIMING_SHIFT                  6     6     0      1    16.7%    ₹3,49,640.61  refusal-only
  SETTLEMENT_CONTAMINATION      3     6     0      3    50.0%    ₹2,62,321.17  refusal-only
  ONHOLD_RELEASE                4     8     5      2    87.5%      ₹44,570.29
  SPLIT_PAYOUT                  3     6     0      0     0.0%    ₹1,74,891.40
  NET_ZERO_SETTLEMENT           2     0     0      0        —               —  no bank line
```

`inj` counts injections; `lines` counts bank lines carrying the code. One
`SETTLEMENT_CONTAMINATION` injection breaks two lines (stage 4). One `SPLIT_PAYOUT` injection
makes two halves. `ONHOLD_RELEASE` reads 8 lines against 4 injections because two of its lines
also carry `AMBIGUOUS_SUBSET`, which the generator records on the line. A single number would
have had to pick one of these to be wrong about.

`match` and `refuse` are the two ways a line is scored right, and separating them is what stops
the table rewarding absent code — the section above. It also sharpens rows that were merely
bad: `SETTLEMENT_CONTAMINATION` at 50% has composed **nothing**; its three greens are the three
lines truth calls unresolvable, and the three the break leaves merely flagged are all missed.

`at risk` is the bank amount of the lines the code got wrong, so the table reads by consequence
rather than by count. `TIMING_SHIFT` is the largest exposure on the board — ₹3.5 lakh across six
lines, none of them composed — and it is one tier away from closing.

### `matcher/run.py` — moved, not written

Stage 6's ladder lived in `tests/test_phase_ab.py`, and the journal said two drivers would
exist until stage 9. The scoreboard would have made three. It is now one function in
`matcher/run.py` with the same body — single pass, `bank_line_id` order, no deadline — imported
by both callers. Stage 9 replaces the body with tier-major ordering, propagation and the
run-level deadline; the signature is what scoring reads.

Each trace entry now also records the settlement ids the tier proposed as anchors, which is
what §9.1's amendment needs and what nothing was recording.

### `core/models.py` — `window_pool` and `read_csv`

`window_pool` moved out of `generator/uniqueness.py`. Stage 6 deferred that move to "stage 9,
when `run.py` becomes the second caller" — `run.py` is now the second caller, so it moved. It
is pure domain logic over `BankLine` and `GatewayTxn` and `matcher/` importing `generator/` was
the wrong direction.

`read_csv` is the inverse of `generate._cell`, ~15 lines, and it is why the scoreboard reads
`data/runs/seed42/` rather than regenerating. That matters — see the next section.

A test round-trips both CSVs through `emit()` and asserts equality with the dataclasses that
wrote them. A column parsed to the wrong type is a silently different dataset.

### The node budget is part of the run's identity

`truth.json`'s config now records `uniqueness_node_budget`, the scoreboard prints it under the
header, and it prints a `!!` banner when it is not the offline budget.

This is not bookkeeping. §10.1 is explicit that the budget is not a performance knob — it
decides whether the uniqueness guarantee holds, which decides how many lines truth calls
`verified` rather than `unproven`, which decides the denominators. Two truth files at 2M and
40M describe **the same CSVs**, and the matcher cannot tell them apart:

```
  40,000,000 nodes    verified 92   unproven  3   ambiguous 16     headline 105 lines
   2,000,000 nodes    verified 80   unproven 15   ambiguous  8     headline 101 lines
```

Twelve lines move between `unproven` and `verified`, eight between `emergent` and the rest.
Recall computed across that boundary compares two different denominators and the difference
looks exactly like a regression — which is the shape of bug that costs an evening in stage 8
while the matcher is being changed constantly. Recording the budget is two lines in the
generator; the banner is ten in the scoreboard, and `report.json` carries the number so stage
14's regression table can refuse to compare runs that are not comparable.

Three tests cover it: the offline budget says so quietly, any other budget says so loudly, and
a truth file predating this stage is comparable with nothing.

### `tests/test_scoring.py` — §11

Twenty-seven tests. Each of TP, FP, FN and TN is asserted on a hand-built truth record, because
a scorer measured only against a run it agrees with is a scorer nobody has checked. FP gets
three cases — one element swapped, one missing, one extra — since I5 is the invariant that a
composition right about twenty-eight transactions and wrong about one is a false match.

The seed-42 cases run at the **2M** budget rather than the committed 40M one, so the suite
stays under 30 seconds. The fixture asserts that budget rather than assuming it — every bucket
size below it is a function of the number, so a change to it should break loudly rather than
shift the pinned counts. What those cases pin is FP = 0, the buckets partitioning all 134 lines,
and TP summing to lines closed.

---

## Deviated from the spec

**`caught` / `missed` are filled in the report, not in `truth.json`.** Stage 4 left the keys
null and said only scoring could fill them, which is true, and the tempting reading is that
scoring writes them back. It does not: truth is the answer key, and a scorer that edits the
answer key is the one direction this design should never allow. `--json` writes
`data/runs/<run>/report.json` with the manifest filled — the same shape, in the file §12's API
already globs.

**The headline is not §11's population.** §11 defines precision and recall over
`truth.resolvable`, with `excluded_from_scoring` removed. Stage 4 replaced exclusion with
disclosure, so the headline is `uniqueness: "verified"` lines plus unrigged refusals, and the
other three populations are printed beside it with their own TP/FP/FN/TN. The alternative —
one number over everything — would fold six lines that are FN *by construction until stage 13*
into a recall figure that is supposed to measure the matcher.

**Anchors recovered is a scoreboard line, not a secondary metric.** §11's table does not list
it; §9.1's amendment requires it. `anchors_recovered()` reports 93 recovered against 64 closed,
with **0 wrong** — wherever a fragment resolved, the true settlement was among the candidates.
The 22 lines with no true anchor are the unresolvable ones, which have no settlement to be
right about.

## Deferred

**No ablation number.** §11's ablation delta needs a model to ablate; the detective is stage 12.
The scoreboard prints `by tier` instead, which is the deterministic half of that comparison
already broken out.

**No exception typing accuracy.** §11 scores the fraction of exceptions whose type matches the
injected break. Nothing types exceptions yet — the exception ledger is stage 10. The per-break
table is the part of §11 that was measurable this stage.

**No residue gap, no cost per 1k records, no multi-seed variance.** Phase E is stage 10, token
accounting is stage 12, the ten-seed regression is stage 14. Every number in this file is a
single-seed measurement.

**The 2M / 40M split is disclosed, not removed.** The scoreboard scores the committed 40M
artifact and the test suite regenerates at 2M so the suite stays under 30 seconds. The budget
is now recorded in truth, printed on the board, carried into `report.json` and asserted in the
fixture — so a number from the wrong one announces itself instead of being chased. What is
still deferred is picking **one** budget for everything published, which is stage 14's call
when the regression harness decides what it is regressing against.

**Precision has not been tested against a tier that can be wrong.** Phase A and B propose whole
settlement groups; G3 has fired once across two stages. The 100% is real and it is also
untested in the sense that matters. Read stage 8's precision as the first measurement of it.
