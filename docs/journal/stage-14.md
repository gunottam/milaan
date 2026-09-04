# Stage 14 — ten seeds, and the two things one seed was hiding

`pytest -q`: **236 passed in 10 s.** `pytest -q -m slow`: **77 passed in 3 m 34 s.**
Both inside `.venv`, installed from `pyproject.toml`.
One new module (`scoring/regression.py`), one new census (`core.subsetsum.count_exact`),
one new board section, no new tier.

**Headline, and neither half of it is the one the brief expected.**

1. **Precision does not read 100.0% on every seed.** Nine of ten do. Three of ten carry
   exactly one false match each — seeds 7, 13 and 101 — and all three are the same break,
   `DUPLICATE_CREDIT`, failing the same way. `scoring/score.py` predicted this failure in a
   comment at stage 7 and seed 42 has been hiding it ever since, by sort order.
2. **§15's 60 s ceiling does not hold with Phase D answering.** On the six seeds where the
   model actually answered, the full run took **33.8 s to 80.7 s, mean 56.2 s**, breaching on
   two. The other four look fast only because the provider's daily token cap had been
   exhausted and every call came back 429 — a refused pass and a fast pass are not the same
   fact, and the harness was reporting them identically. Ablated — same data, same deadline,
   Phase D filtered out of the tier list — every seed lands inside the ceiling at
   **18.2 s ± 3.1 s**. And Phase D closed **zero** extra lines on all ten seeds.

Both are findings a single committed seed could not have produced, which is the argument for
the stage.

---

## What the harness is

`python -m scoring.regression` runs **two runs per seed** and they answer different
questions. They are kept apart in the file, in the table and on the board.

| | offline | live |
|---|---|---|
| deadline | **none** — `deadline_ms=None` | `MATCH_DEADLINE_MS`, armed |
| uniqueness budget | `40,000,000` (offline) | `5,000,000` (demo) |
| Phase D | **off** | on, where credentials resolve |
| what it is for | every accuracy figure | the wall clock, and nothing else |
| reproducible | **yes** — two machines, same bytes | no, by definition |

The live run's *recall* is deliberately not recorded. At the demo budget the buckets are
sized differently (§10.1), so printing a second recall figure beside the first would invite
exactly the comparison that section forbids. §11's ablation delta is measured on the
committed board, not here — a live model call cannot appear in a number whose whole claim is
reproducibility.

Seed 42 reads `data/runs/seed42` rather than a regenerated copy. Generation is deterministic
in the seed, so the copy would hold the same bytes — but the row a reader checks first is the
one the slow set pins, and pointing at that directory is the only thing that stops the two
drifting apart.

---

## The measurement

Ten seeds, node budget only, no wall clock:

| seed | lines | closed | all-lines recall | headline recall | precision | ambiguity | FP |
|---|---|---|---|---|---|---|---|
| 42 | 134 | 100 | 95.2% | 100.0% | 100.0% | 11.9% | 0 |
| 7 | 134 | 103 | 90.3% | 95.0% | **99.0%** | 6.0% | **1** |
| 99 | 134 | 101 | 93.5% | 99.0% | 100.0% | 9.7% | 0 |
| 2026 | 134 | 105 | 92.1% | 97.1% | 100.0% | 5.2% | 0 |
| 1 | 134 | 103 | 94.5% | 100.0% | 100.0% | 9.0% | 0 |
| 5 | 134 | 103 | 92.0% | 96.0% | 100.0% | 6.7% | 0 |
| 13 | 134 | 104 | 92.8% | 98.0% | **99.0%** | 7.5% | **1** |
| 23 | 134 | 99 | 90.8% | 94.9% | 100.0% | 9.0% | 0 |
| 101 | 134 | 108 | 90.7% | 95.4% | **99.1%** | 2.2% | **1** |
| 777 | 134 | 103 | 93.6% | 94.9% | 100.0% | 8.2% | 0 |

| figure | mean ± σ | range |
|---|---|---|
| all-lines recall | **92.6% ± 1.6%** | 90.3% – 95.2% |
| headline recall | **97.0% ± 2.0%** | 94.9% – 100.0% |
| precision | **99.7% ± 0.4%** | 99.0% – 100.0% |
| ambiguity rate | **7.5% ± 2.6%** | 2.2% – 11.9% |

σ is **population** σ over the ten seeds: they are the whole harness, not a sample drawn from
a larger population we are inferring about, and `stdev` would report a figure ~5% larger for
no reason anybody could defend.

**The spread is reported because the mean describes no board.** Stage 4 measured 4.5% to
11.9% on the ambiguity rate across five seeds and that spread was the finding; ten seeds
widen it to **2.2% – 11.9%** against `TARGET_AMBIGUOUS_RATE = 0.08`. The rate control hits
its target on average and misses it by 5.8 points on seed 101 — which is a fact about
`SHARED_WINDOW_RATE` and the rng, not about the matcher, and it is the reason seed 101 closes
the most lines of any seed (108) while scoring the *lowest* headline recall of the four
cleanest ones. Fewer ambiguous lines means fewer free true negatives and a harder board.

**The one figure that has no business varying is the one that did.** A missed match costs a
human minutes; a false match puts the books wrong silently and propagates to GST and revenue
(§1). Precision at `99.7% ± 0.4%` is not a slightly-worse 100% — it is three seeds where
Milaan booked a composition against a bank line that truth says has none.

---

## Finding 1 — the false matches are all one break, and seed 42 was lucky

All three are `DUPLICATE_CREDIT`. Seed 7, worked out in full:

```
bl_0106   2026-10-16   ₹36,525.73   IMPS/NHDFC261/RAZORPAY SOFTWARE PVT/SETTLEMENT
                                    ref NHDFC26101600193      pool 23
bl_9004   2026-10-17   ₹36,525.73   IMPS/NHDFC261/RAZORPAY SOFTWARE PVT/SETTLEMENT
                                    ref NHDFC26101600193      pool 22
bl_9005   2026-10-18  −₹36,525.73   REV-IMPS/NHDFC261/RAZORPAY S
```

The bank posted `setl_0106`'s payout twice and reversed the second on T+1. Truth records
`bl_0106` as the payout and `bl_9004` as `resolvable: false` — *"Duplicate posting of bl_0106,
reversed on T+1 by bl_9005. No transactions of its own."*

The duplicate carries a **byte-identical narration and ref_no**, so A1 recovers `setl_0106`
from either line, and the settlement's 22 transactions balance either credit exactly. §9.8
orders lines within a tier by ascending pool size then `bank_line_id`, and the duplicate's
window is one day later, so its pool holds 22 transactions against the original's 23:

```
A1 pass 1   bl_9004   pool 22   candidates 1   won      <- the duplicate goes first
A1 pass 1   bl_0106   pool 23   candidates 1   stale 1  <- G1: already claimed
```

**`bl_9004` closed at A1, exact, delta 0 paise, and it is a false match. `bl_0106` — the real
payout — scored FN.** One break, one FP and one FN.

And the thing that decides which of the two identical credits wins is the sort key. Every
seed carries three duplicate pairs; here is what §9.8's `(pool size, bank_line_id)` did with
them:

| seed | duplicate | pool | original | pool | who went first | outcome |
|---|---|---|---|---|---|---|
| 42 | `bl_9004` | 28 | `bl_0042` | 28 | **tie → `bl_0042` on id** | TP + TN ✓ |
| 42 | `bl_9006` | 27 | `bl_0010` | 27 | tie → `bl_0010` on id | TP + TN ✓ |
| 42 | `bl_9008` | 28 | `bl_0118` | 28 | tie → `bl_0118` on id | TP + TN ✓ |
| 7 | `bl_9004` | **22** | `bl_0106` | 23 | **the duplicate** | **FP + FN** |
| 13 | `bl_9008` | 25 | `bl_0118` | 25 | tie, and `bl_0118` is itself an unresolvable `SPLIT_PAYOUT` half | **FP** |
| 101 | `bl_9004` | **29** | `bl_0019` | 30 | **the duplicate** | **FP + FN** |

**Seed 42 is clean because `bl_0042` sorts before `bl_9004` and the pools happen to tie.**
The injector puts the duplicate posting one calendar day after the original, so its window is
shifted by a day; where that shift drops a transaction out of the pool the duplicate becomes
the *most constrained* line and §9.8 hands it the first attempt. Nothing about that ordering
is wrong — most-constrained-first is the right heuristic and §9.9 already says the assignment
is greedy and may be globally worse — but it is deciding a question it has no business
deciding, because **neither line should have been composed at all.**

Two of the three closed at **C1**, not A1, so this is not a tier's bug either. It is a
missing rule, and it is missing in front of every tier.

### It is a real hole, and the input does determine the answer

The distinguishing fact is in the statement: **`bl_9004` has a T+1 equal-and-opposite
reversal and `bl_0106` does not.** That is §3.2's reversal-pair rule verbatim — equal
magnitude, opposite sign, adjacent calendar day — and `matcher/ledger.py::reversal_pairs`
already implements it, to the letter, at stage 10. It runs **after** matching, over open
lines only, for exception *typing*. Nothing consults it before a tier proposes.

`scoring/score.py` wrote this down at stage 7 and the regression is what cashed it:

> `DUPLICATE_CREDIT` is the live case: §3.2's reversal-pair rule is unimplemented, so every
> one of its lines is a green. A table that reported one number would show six greens for
> code that does not exist, and **stage 14's regression would carry that forward silently.**

It did not carry it forward silently. It carried it forward as three false matches.

### Not fixed in this stage, deliberately

The fix is one rule and it reuses what is already here: a credit reversed on T+1 by an equal
and opposite debit is a duplicate posting, not a payout, so it is excluded from the ladder
before any tier proposes — `reversal_pairs` over all lines rather than open ones, called once
in `run_ladder`. It is monotonically restrictive (it can only remove candidates), so by §1's
taxonomy it can cost recall and cannot create a false match.

I did not build it, for the reason stage 13 refused to change the scoring rule in the same
commit as the tier that rule rewards: **a matcher change inside the measurement stage is not
a measurement.** Every figure in the table above would need re-deriving against a matcher
nobody had measured, and the pinned counts in the slow set sit on the committed board that
change touches. It is a stage of its own, it is small, and it is the highest-value thing left
in the repo.

**So the honest statement of where this stands: precision is 100.0% on nine of ten seeds and
99.0% on three lines across the other three, from one named break with one named fix.** That
is the number that goes on the slide, with the mechanism beside it.

---

## Finding 2 — the 60 s ceiling, measured instead of assumed

Per-seed wall clock for the full live run — the configuration a judge triggers, generation at
the demo budget with the deadline armed and Phase D on:

| seed | generate | match | audit+score | **total** | ablated total | Phase D | cost |
|---|---|---|---|---|---|---|---|
| 42 | 9.7 s | 48.4 s | 0.01 s | **58.1 s** | 17.6 s | answered | 54 p |
| 7 | 11.4 s | 56.0 s | 0.02 s | **67.4 s** ⚠ | 18.1 s | answered | 39 p |
| 99 | 9.9 s | 70.8 s | 0.02 s | **80.7 s** ⚠ | 17.7 s | answered | 92 p |
| 2026 | 11.3 s | 47.9 s | 0.02 s | **59.2 s** | 16.3 s | answered | 25 p |
| 1 | 11.2 s | 22.7 s | 0.01 s | **33.8 s** | 24.2 s | answered | 28 p |
| 5 | 13.1 s | 25.1 s | 0.01 s | **38.2 s** | 22.4 s | answered | 59 p |
| 13 | 11.9 s | 7.2 s | 0.02 s | 19.1 s | 17.7 s | **429** | 0 p |
| 23 | 11.0 s | 10.3 s | 0.01 s | 21.3 s | 19.7 s | **429** | 0 p |
| 101 | 9.8 s | 7.8 s | 0.02 s | 17.7 s | 16.4 s | **429** | 0 p |
| 777 | 7.0 s | 7.9 s | 0.02 s | 15.0 s | 12.5 s | **429** | 0 p |

| | mean ± σ | range | against §15's 60 s |
|---|---|---|---|
| full live run, Phase D **answering** (6 seeds) | **56.2 s** | 33.8 – 80.7 s | **breached on 2 of 6** |
| full live run, all ten as recorded | 41.1 s ± 22.5 s | 15.0 – 80.7 s | breached on 2 of 10 |
| ablated (no Phase D) | **18.2 s ± 3.1 s** | 12.5 – 24.2 s | inside on every seed |

### The bottom four rows are not fast runs, and the harness said they were

Groq's free tier caps **tokens per day at 200,000**, and the ten-seed live pass exhausted it
partway through. Seeds 13, 23, 101 and 777 got HTTP 429 on every batch:

```
D1  calls=4   in=912  out=1198  cost=8p   malformed=3   hypotheses=4
    MALFORMED_HYPOTHESIS: RateLimitError: 429 — rate limit reached ... tokens per day
    (TPD): Limit 200000, Used 198430, Requested 2407. Please try again in 6m1.584s.
D2  calls=14  in=0    out=0     cost=0p   malformed=14  hypotheses=0
```

The tier refuses honestly — the 429 is counted, the hypothesis is dropped, nothing is raised
(§9.6) — so the *board* was never wrong. **The harness was.** It reported
`detective_ran: true` off `usage.calls`, and a call that came back 429 is a call. A refused
pass and a fast pass rendered identically, at a third of the latency and no cost, which is
precisely the shape of mistake that would have let me write "the ceiling holds on eight of
ten seeds."

`detective_ran` now means **produced a hypothesis**, with `detective_hypotheses`,
`detective_malformed` and `detective_unavailable` recorded beside it. The committed
`regression.json` predates the fix and its four zero-cost rows are the rate-limited ones;
re-measuring needs a fresh token day or a paid tier, and I have not hand-edited a measurement
file to say what a later run would have said.

**So `297 paise` for ten runs is a floor, not the cost**, and the two ceiling breaches are two
out of six rather than two out of ten.

### And the pass that cost the clock closed nothing

`closed` is identical to `closed_ablated` on **all ten seeds**. Phase D spent 1.3 s to 63 s
and 297 paise of tokens to change the board by zero lines, which agrees with stage 12b's
measured ablation delta of 0.00 and is worth restating here because the clock makes it a
sharper trade: on this dataset the detective is currently the difference between a run that
fits §15's ceiling and one that does not, in exchange for nothing measurable. §9.1's amendment
still holds — Pass A's anchors are booked as C1 closures and the delta reads as a floor — but
a floor of zero across ten seeds is a result, not an artefact.

**Every live run reports `deadline_hit = True`** (nine of ten ablated do too), so §9.10's
banner is on for essentially every browser-triggered board: some lines are cut mid-search by
their per-line slice, and with Phase D on the run clock expires during a batch so the last
tier is never offered. That is disclosure working as designed, and the demo should expect the
banner rather than be surprised by it.

Stage 13 reported *"full live run 7.8 s of the 60 s ceiling"* and that figure was true, of
one seed, **without Phase D**. With the detective on, the ceiling is a coin flip.

Where the time goes, and it is not the search:

- §15 budgets **3 s for Detective A and 9 s for Detective B**, 12 s together. Measured, the
  two passes cost the difference between the two columns above: **9.7 s to 63.0 s on the six
  seeds where the model answered** — five of six over the 12 s allocation, one of them by
  5×. The four rate-limited seeds cost 1.3 s to 2.5 s, which is the price of four rounds of
  429 and not a measurement of the pass.
- **The run deadline cannot stop them.** `run_ladder` checks the clock before each tier's
  pool build and again before each line, which bounds every *search* tier. A batching tier
  does its work in `prepare()` — §9.6's 25 narrations and 5-hypothesis batches — and a batch
  already in flight is not interruptible. So the ladder can enter D1 at 21.9 s of a 22,000 ms
  deadline, legally, and return at 70 s.

That is a structural gap rather than a tuning error, and naming it is worth more than a
number that happened to fit. The fix is not a smaller budget: it is a *remaining-time* check
before a batching tier runs at all, plus a per-request timeout on the provider. Also not
built here, and for the same reason.

**What to do about the demo, today, with no code change:** the ablated clock is the honest
ceiling for a room with a projector and someone else's wifi — **12.5 s to 24.2 s, ten seeds,
no exceptions.** §11's ablated configuration is a legitimate board that says so on its face:
the API reports `detective_ran`, and `run_notes` already discloses an unavailable Phase D
rather than printing a number no model produced. With the agent on, quote the range and never
the mean — a mean of 41 s describes a run that finished in 15 s and a run that finished in
81 s equally badly.

---

## What the board says now

Two additions, both static, both below the fold of the run itself.

**The regression table.** Ten rows, ruled, tabular figures, one column per figure and the
four means with their ± σ and range under a single rule and above a double one. It renders
from `regression.json` through `GET /api/regression` — a file, not a computation, because the
whole claim of the figures is that no clock touched them and a browser-triggered run has a
clock in it by definition. The FP column is the only cell on the page that takes a colour.

**The refusals, with their reason.** `SPLIT_PAYOUT` halves leave the documentation table and
get a block of their own, one per pair rather than one per half, with the census sentence on
the page and nothing to expand:

> `setl_0048` · **bl_0048 + bl_9003** · ₹44,453.90 + ₹43,377.70
> *setl_0048 ties to this credit and bl_9003 jointly to the paisa, but **279 divisions of the
> payout balance against this credit**, and the statement does not say which of them this
> credit carried.*
> Blocked on: A bank advice naming the transactions behind each credit.

### The census had to be built, because the search deliberately cannot count

`solve_exact` stops at two solutions — two is already a refusal — so the number it hands back
says *"at least 2"* whatever the truth is. **"The solver found two and gave up" and "the input
does not contain the answer" are different findings and only the second one is true**, and a
board that printed the first would be describing a limitation of Milaan rather than a fact
about a bank statement.

`core.subsetsum.count_exact` counts them exactly: meet-in-the-middle, two halves of subset
sums collapsed by value, milliseconds. It returns a count and no compositions, so it cannot
propose anything and no gate can act on it — which is the only reason it is allowed to
enumerate past two. The DFS cannot answer this at any budget the run can afford:
`setl_0048`'s 30-transaction payout exhausts **5,000,000 nodes** without finishing the count.

It agrees with stage 13's hand-run meet-in-the-middle at **279**, by an independent route,
and `tests/test_subsetsum.py` checks it against the same brute force §6.3 uses for the
oracle. The census travels across seeds, which is the point of putting it on the board rather
than in a journal:

| seed | pair | what the census says |
|---|---|---|
| 42 | `bl_0048` + `bl_9003` | **279** divisions of the payout |
| 42 | `bl_0019` + `bl_9002` | 2 payouts of it, **6** divisions each |
| 42 | `bl_0101` + `bl_9001` | 2 payouts of it, **1** division each |
| 23 | `bl_0104` + `bl_9002` | **466** — the widest on any seed |
| 1 | `bl_0042` + `bl_9002` | **390** |
| 99 | `bl_0065` + `bl_9001` | **313** |
| 777 | `bl_0055` + `bl_9002` | **47** |
| 1 | `bl_0084` + `bl_9001` | **7** — the narrowest that still refuses |

**61 halves across ten seeds**, against seed 42's five. Two shapes only seed 42's board never
showed, and both changed code:

**A credit can tie out jointly against more than one settlement.** Seed 99's `bl_0041` ties
against `setl_0085` *and* `setl_0106`, with either `bl_9007` or `bl_9006` as the partner. The
tier held the first settlement and the first partner it found, so the refusal sentence named
`setl_0106` while the ledger row's `settlement_id` — a different derivation, off the trace —
named `setl_0085`. **Stage 13 fixed exactly this class of disagreement once, on `bl_9001`,
and pinned it with a test that only ever ran on seed 42.** `partners` and the anchors are
sets now, and the sentence reports per settlement:

> *2 settlements (setl_0085, setl_0106) tie to this credit and bl_9007 jointly to the paisa,
> but setl_0085 divides 42 ways, setl_0106 divides 130 and 130 ways, and the statement does
> not say which of them this credit carried.*

The census is grouped by settlement and **never summed** for the same reason: two payouts can
share a division, so a total would claim more distinct sets than exist.

**A division search can exhaust its node budget.** Seeds 7, 99, 5 and 101 each have one pair
whose payout runs 25–31 transactions, where `solve_exact` hits `SUBSET_NODE_BUDGET` before
the tree ends. Those refuse with a different sentence — *the division search exhausted the
250000 node budget* — and they are correctly a different finding: an unexhausted tree says
nothing about how many divisions balance, so no census is quoted. §10.1's distinction between
a refusal from the data and a refusal from a budget, arriving on its own.

---

## Pair-scoring `SPLIT_PAYOUT`: measured, and declined

Carried into this stage from stage 13 as required. **Declined**, and the measurement is the
reason rather than the cost: **1 TP → 2 TP on seed 42**, with `bl_0101` giving up the TP it
holds today.

The rule needs C3 to commit *some* balanced division wherever the payout is proved and the
division is not, because a refused line contributes no composition to any union. On this
board that means committing one of 279 for `setl_0048`, and on the two pairs where the payout
itself is undetermined it means guessing which of two identical refunds the bank netted — **a
false match half the time by construction.** One line of recall for a coin-flip on the
failure class §1 prices as severe.

Recorded in `docs/build-stages.md` (stage 14), in `docs/journal/stage-13.md` where the
question was raised, and in `scoring/regression.py::SCORING_RULE`, which travels inside
`regression.json` and prints on the table — so the declined change cannot later be mistaken
for a silent one.

The refusals above are what stage 14 reports instead. That claim is stronger than the recall
point it replaces and a reader can check it.

---

## What this cost

| | |
|---|---|
| new module | `scoring/regression.py`, 512 lines: two runs per seed, the aggregation, the table |
| new solver body | `count_exact`, 20 lines, meet-in-the-middle, counts only, proposes nothing |
| `split_p.py` | the refusal sentence quotes a census instead of a cutoff; `partners` and the anchors became sets; +2 fields |
| `ledger.py` | one evidence sentence reworded — it now says what the *search* did, beside the census that says what *balances* |
| API | `GET /api/regression`, 8 lines, serves a file |
| web | `Regression.jsx` (145 lines) static table, `Refused` block in the open column, 56 lines of CSS |
| tests | `tests/test_regression.py` (12), the census against brute force (3), the board census assertion (1) — 220 → **236** fast, 76 → **77** slow — plus 19 new structural checks in `web/check-strip.mjs` |
| harness wall clock | ~10 min for ten seeds with datasets cached, ~30 min cold |
| gates, `Claim`, `run.py`, truth | **untouched.** No tier, no gate and no truth field moved in this stage |

---

## Standing decisions for whoever picks this up

1. **The reversal-pair pre-match exclusion.** One rule, monotonically restrictive, kills three
   false matches across ten seeds and converts three FNs into closures. It is the only thing
   in this repo that improves the number that matters most.
2. **A remaining-time check before a batching tier.** §15's Phase D budget is not enforceable
   as written, and the ceiling is a demo-room risk rather than a paper one.
3. **The offline uniqueness budget is ~19 s of pure waste** — `generator/config.py` measured
   20M as indistinguishable from 40M at stage 11b, and it is still 40M because moving it
   regenerates the committed board and every pinned count with it.
4. **Do not re-roll a seed because its numbers are unflattering.** Seed 101 has a 2.2%
   ambiguity rate and the worst headline recall of the clean seeds; seed 23 closes the fewest
   lines. The set was fixed before the figures were read, and it stays fixed.
