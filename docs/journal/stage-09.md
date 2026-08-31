# Stage 9 — orchestration, and a loop that does nothing

Written for someone who knows `docs/spec.md` and has not read the code.

Spec sections read: **§9.8** (ordering and the loop), **§9.10** (deadlines), **§15** (budget).

`pytest -q`: **175 passed, 0 skipped.** Fourteen are new, all in `tests/test_orchestration.py`.

```
$ python -m scoring.score --run data/runs/seed42

  134 bank lines · 3009 transactions · 97 closed · 37 open
  by tier   A1 40  A2 0  A3 4  B1 16  B2 4  C1 25  C2 8
  propagation pass 2 closed 0 lines (nothing pass 1 had not already)
  !! deadline reached at 22,000 ms — 2 of 2 propagation passes run.
     EXCEEDED_SEARCH_BUDGET, 1 search stopped mid-tree by its per-line slice:
       bl_9001

HEADLINE — verified-unique lines, plus refusals on lines nobody rigged
  TP   90      FP    0      FN    2      TN   13
  precision 100.0%        recall  97.8%

  wall clock 5.0s  (deadline 22,000 ms, §15 allocates 22 s to Phase C)
```

**The board did not move.** TP 90 / FP 0 / FN 2 / TN 13, recall 97.8%, precision 100% — the
same numbers stage 8 measured. Everything in this stage is about *how* they were reached and
what it cost, which is the honest result for an ordering stage: if tier-major ordering and a
run-level deadline had changed recall, one of them would have been doing something other than
what §9.8 and §9.10 say they do.

---

## The wall clock — the number the stage was asked for

| Configuration | Wall clock (3+ runs) | Closed | Recall |
|---|---|---|---|
| Stage 8: `bank_line_id` order, one pass, no clock | **24.9 s** | 97 | 97.8% |
| Stage 9 ordering, one pass, no clock | **12.5 s** | 97 | 97.8% |
| Stage 9, two passes, no clock (`--deadline-ms 0`) | **14.6 – 15.6 s** | 97 | 97.8% |
| Stage 9, two passes, live deadline (default) | **5.0 – 10.3 s** | 97 | 97.8% |

Split, under the live configuration: A1–B2 **0.86 s**, C1 **7.5 s**, C2 **4.2 s**.

**Against §15.** The prompt for this stage cited a 28 s Phase C allocation; §15's table says
**22 s**, and 22 is what `MATCH_DEADLINE_MS` is set to. `run_ladder` spends that budget on the
whole ladder, not on Phase C alone, so A+B's 0.86 s comes out of it — Phase C effectively gets
21.1 s of its 22. Under budget either way, with the full run at **5–10 s against 22 s**, and
the unbounded run at 15 s still inside it.

The 24.9 s → 12.5 s halving is **ordering alone, not the clock**. Sorting a tier's lines by
ascending pool size (§9.8) means the cheap, tightly-constrained lines resolve first, and every
match they make shrinks the pools of the expensive lines still queued. Under stage 8's
`bank_line_id` order, `bl_0030` and `bl_0001` were searched early against pools of 28 and 27
and cost 9.1 s and 6.4 s between them — 62% of the run for two lines that both ended up
refused. Most-constrained-first is documented in §9.8 as a recall mitigation for greedy
assignment; on this data it turned out to be worth more as a cost control, and it was not
tuned for that.

---

## Propagation pass 2 closes nothing. Measured, on four seeds.

This was the question the stage was asked to answer honestly, and the answer is zero.

| Seed | Bank lines | Closed | Closed in pass 2 | Candidate counts that differed between the passes |
|---|---|---|---|---|
| 42 | 134 | 97 | **0** | **0 of 61** |
| 7 | 134 | 102 | **0** | 0 |
| 99 | 134 | 101 | **0** | 0 |
| 2026 | 134 | 105 | **0** | 0 |

Not "closed nothing new" — **pass 2 is a bit-for-bit replay**. Every open line is re-offered to
every tier and every tier proposes exactly the same candidates it proposed the first time. It
costs 4.0 s and returns the same board.

### Why, mechanically

§9.8's claim is sound in general: resolving one line shrinks every other pool, which can turn
an ambiguous line into a determined one. Two things stop it firing here.

**The generator's cycles do not overlap.** `generator.config.cycle_spacing` is
`window_days + 1`, so a bank line's window pool holds its own cycle's transactions and nothing
else — a deliberate stage-3 decision, because a pool that caught its neighbours would be ~75
items and cross §9.3's pigeonhole bound. A claim in one cycle therefore *cannot* shrink another
cycle's pool. The ~10% of cycles carrying a second payout (`SHARED_WINDOW_RATE`) are the only
place two lines share a pool at all.

**Tier-major ordering already collects the propagation that exists.** Where two lines do share
a window, both are offered the same tier in the same sweep, and the second one already sees
the first one's claims. The only propagation a *second pass* can catch is a claim that lands
after the beneficiary has had its last tier — which on this board means later in the C2 sweep
than the beneficiary, and C2's ordering puts a shared-window pair adjacent. So §9.8's second
pass is collecting an effect §9.8's first rule has already collected.

### It is still in the code, and here is the condition for deleting it

The one mechanism that a pool-size argument does not cover: **B1's index shrinks on claim.**
Two unclaimed settlements with the same total are a G5 tie in pass 1 (finding 8.4); if one of
them is claimed by another line later in the run, pass 2 sees one candidate and closes. That
path needs no pool change at all, so nothing measured above rules it out — it simply never
fired on four seeds.

That is not enough to keep a 4-second loop on faith, and it is not enough to delete a
frozen-spec behaviour on four seeds either. So: **kept, measured, and printed on the board
every run** — `propagation pass 2 closed 0 lines` is a permanent line of the scoreboard, not a
footnote. **Stage 14's 10-seed regression is the decision point.** If it is still zero across
ten seeds, `PROPAGATION_PASSES` goes to 1 and the loop comes out.

One thing that makes the cost tolerable in the meantime, and it is not a coincidence: pass 2
runs last, so when the deadline binds, pass 2 is what gets cut — and cutting a replay costs
nothing. The two features compose in the right direction.

---

## The deadline

### What it is

One clock for the run (`MATCH_DEADLINE_MS = 22_000`), and each line gets
`min(2000, remaining_ms / unmatched_count)` at the moment it is issued — §9.10 exactly. Per-line
timeouts do not compose: `134 lines × 2 s × 2 passes` is nine minutes, and the timeout is paid
*most* on lines with no solution, because proving zero solutions means exhausting the tree.

The fair share is deliberately fair rather than generous. Dividing by every unmatched line
rather than by the lines left in the current tier is what stops the first expensive line
spending the whole run. On seed 42 the share at C1 is ~285 ms, and that is the entire
difference between two lines consuming 15 of 25 seconds and all 134 getting a turn.

### What it cost: nothing, on this seed

The deadline cut three searches at the live budget — `bl_0001`, `bl_0030`, `bl_9001`, the three
most expensive on the board. **All three were already refusals at stage 8**, where they
exhausted the 250k node budget instead. The clock reached them first; the answer is the same,
and it arrives 9 seconds earlier.

That is luck about this dataset, not a guarantee, and the code does not present it as one. A
cut line is refused, scores FN (§11), and is named on the board.

### The typing, which §9.10 does not spell out

§10.1 has two refusals and they are not the same fact:

- `UNIQUENESS_UNPROVEN` — the node budget ran out. A property of **the problem**. Reproducible.
- `EXCEEDED_SEARCH_BUDGET` — the clock ran out. A property of **the machine**. Not reproducible.

Both score FN and a human triages them differently: "give it more time" against "unprovable at
any budget worth spending". So `DeadlineExceeded` is a separate exception, `SearchProposer`
catches it separately, and the refusal string types accordingly.

The uncomfortable consequence, stated rather than hidden: **a line's exception type is now
machine-dependent.** `bl_9001` reads `EXCEEDED_SEARCH_BUDGET` here and would read
`UNIQUENESS_UNPROVEN` on a faster box. That is the cost of §9.10 and it is why §11 insists the
regression harness runs on node budget only.

### Two populations, not one

§9.10 names one — lines the deadline never reached. There is a second, and it is the one that
actually fires on this data: lines that *were* reached and whose search was stopped mid-tree by
their slice. The banner reports them apart:

```
  !! deadline reached at 900 ms — 1 of 2 propagation passes run.
     EXCEEDED_SEARCH_BUDGET, 27 search stopped mid-tree by its per-line slice:
       bl_0019, bl_0025, bl_0026, bl_0038, bl_0039, bl_0040, bl_0041, bl_0046 (+19 more)
     Those lines score as FN. Nothing below was relaxed to fit the clock.
```

"27 unattempted" and "27 with no answer" score identically and are not the same sentence to a
human, which is §10.1's whole argument for typed exceptions applied one level up.

---

## Reproducibility — the acceptance condition, and where it does not hold

**`--deadline-ms 0` (node budget only): two runs render byte-identical boards and byte-identical
`--json`.** Asserted in `test_two_runs_on_one_seed_render_the_same_bytes`, which compares whole
rendered boards rather than a count — an ordering bug from set or dict iteration would be
intermittent, and a count would miss it most of the time.

**At the live deadline it does not hold, and it must not be claimed.** Eight live runs all
produced the same headline (97 closed, TP 90 / FP 0, recall 97.8%) but the cut-list varied
between one line and three, and the wall clock between 5.0 s and 10.3 s. A first pair of runs
compared identical and that was luck; the third disagreed. §11 says this in advance — *"wall-clock
deadlines make results machine-dependent"* — and the fix is not to make the clock reproducible,
it is to have a reproducible mode and say which one you are in. The board's banner is what says
so.

`elapsed_ms` is therefore **not** in the rendered report. It is printed on the line below it.
`test_the_elapsed_time_is_not_in_the_report` pins that, because the moment a duration is inside
the board, byte-identical is unachievable and someone deletes the assertion instead of the
duration.

## Graceful exhaustion

```
$ python -m scoring.score --run data/runs/seed42 --deadline-ms 900
  134 bank lines · 3009 transactions · 93 closed · 41 open
  !! deadline reached at 900 ms — 1 of 2 propagation passes run.
  TP   86      FP    0      FN    6      TN   13
  precision 100.0%        recall  93.5%
```

Exit 0. A partial board, four fewer lines closed, **precision still 100%** — the clock removes
answers, it never relaxes one. At `--deadline-ms 1` the run closes nothing, names all 134 lines
unattempted, flies the banner and still scores. `run_ladder` never raises: a deadline is a
normal outcome, and a reconciler that dies on its own timeout has converted a partial answer
into no answer.

---

## Files

### `matcher/run.py` — rewritten

`run_ladder` returns a frozen `Run` (`matched`, `trace`, `exceeded`, `passes_run`, `elapsed_ms`,
`deadline_ms`) instead of a `(matched, trace)` tuple. Four call sites moved. The tuple could
have carried the two new populations as a third and fourth element; the reason it does not is
that `deadline_hit` and `banner()` are *derived* from them and belong next to them, and the
alternative is every caller re-deriving "did the clock end this" from three fields and one of
them getting it wrong.

`build_tiers` is unchanged and stays public — isolated tier scoring is how stage 8's ablation
was measured and how stage 12's will be.

**Pools are built once per tier and filtered per line.** The sort needs every open line's pool
size before the sweep starts; the tier needs the pool as it stands when its line comes up.
Rebuilding per line would rescan 3,009 transactions 134 times a tier. Reusing the snapshot
unfiltered would let a tier cite a transaction claimed earlier in the same sweep — G1 rejects
it, so the answer stays correct, but it would cost recall and surface in the trace as
staleness rather than as the bug it is.

`trace["pool"]` is the size **the sort saw**, the tier's opening snapshot. The tier itself may
see fewer. The ordering claim is about the sort key, so that is the number recorded, and
`test_within_a_tier_the_most_constrained_line_goes_first` asserts on it exactly rather than
approximately.

The deadline is checked **before each tier's pool build**, not only before each line. The build
is a scan over every transaction for every open line and is the one place this loop could
overrun its own deadline.

### `core/subsetsum.py` — a deadline, checked every 4096 nodes

`solve_exact` and `solve_tolerance` take `deadline_ns: int | None`, an absolute
`time.monotonic_ns()`. `None` — the generator's oracle and the regression harness — is node
budget only, which is what makes those numbers reproducible.

Checked every 4096 nodes, not every node: the check costs more than the node it guards, and
4096 is ~1 ms on these pool sizes, finer than any slice the orchestrator hands out. It bounds
the overrun instead of leaving it open.

`DeadlineExceeded` **subclasses** `SearchBudgetExceeded` on purpose. The consequence is
identical — the tree was not exhausted, so uniqueness is unknown — so `generator/uniqueness.py`,
which catches the base class and never passes a deadline, stays correct without being touched.
Only the typing differs, and only `search_p` cares.

Everything here is integer nanoseconds. No float enters `matcher/` or `core/` for this (I1 is
about money, but there was no reason to introduce the first float in the codebase to hold a
timestamp).

### `matcher/proposers/search_p.py` — `deadline_ns` is an attribute, not a parameter

The orchestrator sets `tier.deadline_ns` before each `propose`, guarded by `hasattr` so only
the search tiers carry one — A and B are O(1) and have nothing to time.

An attribute rather than a `propose(line, pool, deadline)` parameter because the `Proposer`
protocol is the boundary between the two layers (§7.2), and a wall clock is not part of what a
proposer *is*. Widening the protocol for one tier's needs would put a timing concern in the
signature the detective will implement at stage 12. It follows the precedent `refusals` already
set: tier-local state the orchestrator reads through `getattr`, in the other direction.

### `scoring/score.py`

`render` takes the `Run` instead of `(matched, trace)`, prints `propagation pass 2 closed …`
every run, and prints `ladder.banner()` when the clock was in play. `--deadline-ms` was added,
where `0` means off — §11's reproducible mode from the CLI.

`search_summary` now dedupes by line. With two passes the raw trace holds each line twice and
the summary read double: "C1 proposed on 47" for 35 lines. One entry per line, last state wins.

---

## Deviated from the spec

**Nothing.** §9.8's ordering, §9.8's two passes and §9.10's formula are implemented as written.
The pass-2 finding is a measurement of the spec's behaviour, not a departure from it, and the
loop is still there.

## Deferred

**`PROPAGATION_PASSES = 2` is on probation.** Four seeds, zero closures, zero changed candidate
counts, 4.0 s. Stage 14's 10-seed regression decides. If it is still zero, delete the loop.

**Phase E still does not run on partial results.** §9.10 requires it and the stage prompt asked
for the audit; `matcher/audit.py` is stage 10 and does not exist yet. What exists is the
substitute the spec also names — scoring runs on the partial board and the banner declares it.
When the audit lands it needs no new hook: it consumes `Run.matched` like scoring does.

**The exception ledger still does not type any of this.** Both refusal strings are on the trace
with their §10.1 codes as a prefix; stage 10 reads them.

**`MATCH_DEADLINE_MS` covers the whole ladder, not Phase C.** §15 budgets Phase A+B and Phase C
separately (2 s and 22 s). One clock is simpler and A+B costs 0.86 s of the 22, so the split
buys nothing today. It would matter if A+B ever got expensive, and the constant is one number
in one file when it does.

**The live board is not reproducible and the regression harness must not use it.** Stage 14
runs `--deadline-ms 0`. This is written here because it is the kind of thing that gets
rediscovered as a flaky test.
