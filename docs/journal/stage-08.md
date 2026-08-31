# Stage 8 — Phase C, and two predictions scored

Written for someone who knows `docs/spec.md` and has not read the code.

Spec sections read: **§9.3** (Phase C), **§9.4** (G3 coherence).

`pytest -q`: **161 passed, 0 skipped.** Twenty-two are new.

```
$ python -m scoring.score --run data/runs/seed42

MILAAN — scoreboard    data/runs/seed42    seed 42  noise high
══════════════════════════════════════════════════════════════════════════════
  134 bank lines · 3009 transactions · 97 closed · 37 open
  by tier   A1 40  A2 0  A3 4  B1 16  B2 4  C1 25  C2 8
  C1 proposed on  35   closed  25   G5 refused  10   declined to search   4
  C2 proposed on  14   closed   8   G5 refused   6   declined to search  16
  anchors recovered 93 (true anchor present 71, wrong 0, no true anchor 22) · lines closed 97
  uniqueness verified at 40,000,000 nodes  (the offline budget — comparable)

HEADLINE — verified-unique lines, plus refusals on lines nobody rigged
──────────────────────────────────────────────────────────────────────────────
  TP   90      FP    0      FN    2      TN   13
  precision 100.0%        recall  97.8%
```

---

## Prediction 1 — hit, to the line

Stage 7 registered this before any of the code below existed:

```
  headline now      TP 57   FP 0   FN 35   TN 13     recall 62.0%
  headline after    TP 82   FP 0   FN 10   TN 13     recall 89.1%      <- prediction
```

Measured, C1 only, same 40M artifact:

```
  A+B          TP 57   FP 0   FN 35   TN 13     recall 61.96%   closed 64
  A+B+C1       TP 82   FP 0   FN 10   TN 13     recall 89.13%   closed 89
```

**TP 82, FN 10, recall 89.13% against a predicted 89.1%.** C1 closed 25 lines — exactly the
25 that stage 7 counted as already carrying an anchor.

The prediction was not "recall will improve". It named the population (25 anchored FN), the
mechanism (the settlement is known, so the search is over one or two cross-cycle strays rather
than a pool), and the resulting counts. All three held. The value of that is not the number:
it is that the stage-7 FN partition — *every* miss is one settlement group plus one or two
strays, no residual "we don't know why" category — was a correct description of the data
rather than a plausible story about it.

## Prediction 3 — confirmed on mechanism, and it needed checking properly

Stage 7:

> **C2 will attempt all 35 and close few.** Every one of these lines has a window pool of
> 23–32, under `C2_MAX_POOL = 35`, so C2 does not refuse them by rule. […] **The expected C2
> outcome on this data is refusals, not closures.** […] If C2 closes a large share of the 35
> instead, stage 4's finding is wrong and should be revisited rather than quietly enjoyed.

Measured. C1 leaves 45 lines open; C2 reaches a verdict on 30 of them:

```
  closed                     8
  refused, G5 tie            6
  declined, node budget     16
  declined, pool cap         0        <- every pool was 22-32, under the cap of 35
  searched, found nothing   15        (6 of them had a pool of 0 — all claimed)
```

**Refusals outnumber closures 22 to 8.** Stage 4's pigeonhole finding predicted refusals and
got them. But the sixteen came through `SearchBudgetExceeded`, not the pool cap, and that
distinction is exactly the kind of thing that reads as "our budget is too small" and gets
quietly raised. So it was checked rather than assumed: each of the sixteen was re-run at
**60,000,000 nodes — 240× the live budget:**

| At 240× the budget | lines | truth says |
|---|---|---|
| two solutions found — genuinely ambiguous | 9 | `resolvable: false` |
| zero solutions — nothing coherent in the pool | 5 | 3 unresolvable, 2 outside the window |
| still unexhausted at 60M | 2 | `resolvable: true`, unprovable |

**Not one of the sixteen becomes a correct match at 240× the budget.** The budget is not what
is stopping C2 — nine of them have two answers and G5 would refuse them anyway, five have no
answer in the pool at all, and two cannot be exhausted at any budget worth spending. §9.3's
claim that this is an information-theoretic limit rather than a performance one survives its
first real test, and `UNIQUENESS_UNPROVEN` turns out to be the *correct* verdict on all
sixteen rather than a hedge.

### Where the prediction was wrong, stated plainly

"Closes few" was right about the count and wrong about the consequence. Those 8 closures took
the headline from 89.1% to 97.8% — they are not marginal, they are almost the entire remaining
gap. The reason is that stage 7's **prediction 2** had already named them: it said 8 of the
10 remaining FN had their true composition inside the window pool and 2 did not. C2 closed 8
and the 2 survivors are both `TIMING_SHIFT` — `bl_0083` and `bl_0102` — where the break puts a
member outside the window and, per §9.3, only an anchor makes membership a fact.

So predictions 2 and 3 were making compatible claims about the same 8 lines and stage 7 wrote
them up as if only the pessimistic one mattered. The honest summary is: **C2's closure rate is
27% of the lines it reaches a verdict on and 100% of the lines that were reachable at all.**
Stage 4 does not need revisiting; stage 7's framing of prediction 3 does, and this is it.

## Precision — the number that was actually at risk

**100.0%. Zero false positives, across all 134 lines and every bucket.**

Stage 7 said this measurement was the point of stage 8, so it should not be reported as a
green tick:

> Phase A and B propose whole settlement groups, so the gate chain has had very little that is
> wrong to reject — G3 has fired once in two stages. **C2 in stage 8 is the first tier that
> can propose an arbitrary subset, and it is the first real test of whether precision
> survives.**

It survived, and the 16 `AMBIGUOUS_SUBSET` lines are still refused 16 / matched 0 — those are
the lines where a match would be a fabricated answer to a question truth says has two, and C2
is the first tier with the machinery to fabricate one. What did the work was not C2's
arithmetic. It was G3 rejecting incoherent subsets *inside* the search and G5 refusing ties,
neither of which knows where a candidate came from.

---

## Files

### `core/subsetsum.py` — the solver moved, not rewritten

`solve_exact` was in `generator/uniqueness.py` because stage 3 was the first thing that needed
it. Stage 8 made `matcher/` its second caller, and `matcher/` importing `generator/` is the
wrong direction — the same argument that moved `window_pool` at stage 7. The body moved
verbatim.

Rewriting it from §9.3's pseudocode would have reintroduced two bugs stage 3 found the hard
way: the `remaining == 0 … return` that drops every superset adding a zero-netting group (the
very second solution the uniqueness gate exists to find), and, without the return, the same
subset re-reported at every node down the all-skip path, where duplicates consume the
two-solution cutoff and mark a uniquely resolvable line ambiguous. The property test
(`tests/test_subsetsum.py`, §6.3) passes unchanged from the new home, and both callers still
route through it — which is the only check that the oracle is sound.

`C2_MAX_POOL` moved here too, out of `generator/config.py`. It is a bound on the problem, not
a knob of either side: generation sizes payouts so a window pool stays under it, and C2
refuses above it. Two copies would let the dataset and the matcher disagree about where the
pigeonhole bound is, and the disagreement would present as a recall result.

### `solve_tolerance` — four places the obvious implementation is wrong

§9.3 gives the tolerance pass as a four-line comment. Each line of it is a correction to
something a straightforward implementation gets wrong, and the function is written around
them:

- **Records at interior nodes and keeps searching.** Any node's `chosen` is a complete
  candidate — you simply stop adding. Accepting the first and returning gives whichever near
  miss the sort order reached first, which on a pool sorted by descending `|net|` is
  systematically the wrong one. `test_the_minimum_is_taken_not_the_first_node_inside_the_band`
  is a three-item pool where the first qualifying node has delta 2 and the minimum is 1.
- **The band is §8.2's double cap over the FULL composition,** which is why `solve_tolerance`
  takes `base_size`. C1 searches only the residual, so `min(tol, len(chosen))` computed over
  the residual is *stricter* than the G4 that will judge the claim — the solver would discard
  candidates the gate admits, and the failure would look like recall rather than like a bug.
- **Pruning widens by `tol`.** `solve_exact`'s suffix bounds ask whether the remainder is
  exactly attainable. Reused unchanged they prune away every near miss before it is recorded.
- **No solution-count cutoff.** The minimum is not known until the tree is exhausted, so the
  two-solution cutoff that makes `solve_exact` cheap is unavailable here. Only the node budget
  bounds this pass, and an exhausted budget raises rather than returning the best-so-far — a
  partial tree says nothing about which candidate was best.

It is checked against brute force the same way `solve_exact` is: enumerate every subset,
filter to the double cap, take the minimum |delta|, compare. That test is the reason the four
points above are claims rather than hopes.

### `matcher/proposers/search_p.py` — C1, C2, and one thing it deliberately does not do

`SearchProposer("C1" | "C2", txns)`. It emits `Claim`s and approves nothing; the verification
layer was not touched this stage, which is §7.2's claim about adding a proposer and this is
the first time it has been tested by an actual addition.

**C1 does not implement the window exemption.** It sets `anchor_settlement_id` on the claim
and `g1_exclusivity` does the rest — anchor members skip the window test, strays do not. That
is what makes an `ONHOLD_RELEASE` settled four days early recoverable at C1 and invisible to
C2, and putting the rule in the gate rather than the tier means the tier cannot widen it.
Anchors come from the same `RegexProposer` recovery Phase A uses, re-run rather than threaded
through, so C1 is testable on its own.

**G3 runs inside both searches, as `keep`, over the full composition.** Not after. A candidate
G3 would reject must not consume the two-solution cutoff, or a coherent second solution deeper
in the tree is never reached and an ambiguous line is reported unique. For C1 that means
`is_plausible_payout(group + candidate)`, not `is_plausible_payout(candidate)` — filtering the
residual alone would be a different rule than the gate that follows.

**The tolerance pass runs only if the exact pass returned nothing** (§9.3), and both results
are local so the rule lives where it is stated. That matters at the top end too, in a way §9.3
does not spell out: if the exact pass returned *two* solutions the line is ambiguous, and a
wider band could produce a single answer to it. The pass not running is what stops that, and
`test_an_ambiguous_line_is_not_rescued_by_a_wider_band` pins it. It is the one place in this
file where a plausible refactor costs precision rather than recall.

C1 does not propose a residual of zero. The bare group is A1's and B1's claim and has already
walked the gate chain, G4 included; re-proposing a set the gates ruled on cannot change the
answer.

### Refusals are recorded, not swallowed

A tier that declined to search and a tier that searched and found nothing are different facts
and score identically today, so the distinction has to survive somewhere until stage 10's
ledger exists. `SearchProposer.refusals` is a `dict[bank_line_id, str]` the orchestrator reads
into the trace via `getattr`, so the `Proposer` protocol is not widened for one tier's
by-product. Both causes — pool past the cap, budget exhausted — type as `UNIQUENESS_UNPROVEN`,
which §10.1 is explicit is neither a match nor "found nothing".

The scoreboard prints `proposed on`, not `attempted`. The trace holds a line only when a tier
produced a candidate or declined, so a tier that searched exhaustively and found nothing
leaves no entry — C2 saw 45 open lines and appears against 30. Labelling that "attempted"
would be a number that reads larger than the fact behind it.

### `matcher/run.py` — `build_tiers`

The tier list is now a function, so a caller can measure one tier's reach by taking a prefix.
That is how prediction 1 was scored: `build_tiers(txns)[:6]` is A1–C1. The alternative was to
score C1 by deleting C2 and remembering to put it back, which is how a measurement quietly
becomes a different measurement.

### `tests/conftest.py` — one seed-42 dataset

Four modules pinned counts against the same deterministic `generate(42, …)` at the 2M budget
and each paid ~7s to rebuild the identical bytes. One session fixture; the suite went from
50s back to 28s with the new tests in it. Not a stage-8 concern, but stage 9 adds two
propagation passes to every one of those fixtures and this is cheaper to fix now than then.

### `core/models.py` — `settlement_members`

A1–A3, B1 and now C1 all need `settlement_id -> its entity ids`, and the third copy of the
four-line grouping was about to be written. One function, three call sites, net deletion.

---

## Deviated from the spec

**The tolerance pass is not a separate tier.** §9.3 presents it as the solver's second pass
and that is where it is — inside `propose()`, after the exact pass, per line. A separate
`C1-tol` / `C2-tol` tier running after all exact tiers would give a stronger ordering
guarantee under §9.8's tier-major rule: today a tolerance match on one line can consume
transactions another line's exact match needed. §9.9 already acknowledges the system is greedy
and that ordering mitigates rather than eliminates this. On seed 42 it does not bite — 5
tolerance matches, all correct — but it is a real difference between "exact beats tolerance
per line" and "exact beats tolerance globally", and stage 9 owns the ordering.

**`SUBSET_NODE_BUDGET = 250_000` is declared in `search_p.py`,** following
`gates.py::TOLERANCE_PAISE` and `lookup_p.py::SETTLEMENT_WINDOW_DAYS`, rather than in a config
module `matcher/` should not import.

## Deferred

**C3 is stage 13.** The six `SPLIT_PAYOUT` halves remain FN by construction, ₹1,74,891.40 at
risk — the largest exposure on the board now that `TIMING_SHIFT` is half closed.

**Nothing types the refusals yet.** Sixteen lines carry `UNIQUENESS_UNPROVEN` and two carry
`TIMING_SHIFT` with no diagnosis; §10.2's delta diagnostics and the exception ledger are stage
10. The trace carries the reason string so stage 10 has something to type.

**The 250k budget has not been tuned and should not be.** §10.1: it decides whether the
uniqueness guarantee holds, not how fast the run is. The 60M probe above says raising it buys
zero correct matches on this seed. If a later stage is tempted to move it, that probe is the
thing to re-run first.

**Every number here is single-pass.** No tier-major ordering across propagation passes, no
run-level deadline — stage 9. §9.8 says resolving one line shrinks every other pool and can
turn an ambiguous line into a determined one, so the 6 G5 refusals and 16 unproven lines are
an upper bound on what a second pass would still refuse, not a final count.

**Two budgets are still in play.** The scoreboard scores the committed 40M artifact; the suite
regenerates at 2M so it stays under 30s. Both are disclosed and asserted, and picking one is
still stage 14's call.
