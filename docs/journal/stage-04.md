# Stage 4 — break injectors, and the ambiguity mechanism

Written for someone who knows `docs/spec.md` and has not read the code.

Spec sections read: **§5** (the eighteen-break taxonomy) and **§5.1**
(`NET_ZERO_SETTLEMENT`).

`pytest -q`: **73 passed, 1 skipped** (the skip is still `test_claim_carries_no_source`,
waiting on `matcher/proposers/base.py` in stage 5). `--seed 42` is byte-identical across two
runs, all four files.

```
data/runs/seed42: 134 bank lines, 3009 transactions, 2763 orders
  resolvable 105   verified 92   by_construction 10   unproven 3   unresolvable 29
  ambiguous 16 (11.9%)   cross-cycle strays 70   narrations unparseable 36 (30.0%)
  breaks injected 63 across 15 of 15 codes
```

The flag is `--payouts`, because that is what it controls. Injected breaks add bank lines (a
duplicate posting genuinely is an extra line in a statement; a split payout is two) and
`NET_ZERO_SETTLEMENT` removes one, which is how 120 payouts become 134 lines.

---

## The composed finding

This is the thing to take away from stage 4, and it took two stages to see whole.

**Ambiguity requires overlapping windows. Overlapping windows are exactly where amount-based
search stops being informative.** The same property drives both halves:

- Stage 3 established that subset-sum carries information only while `2**len(pool)` stays near
  the range of reachable targets. Past that, pigeonhole says every target has many
  representations, so uniqueness is not expensive to prove — it is false.
- Stage 4 establishes the converse. Ambiguity needs a **decoy**: a transaction in a line's
  window pool that its composition does not use. With one payout per window there are none —
  every settled transaction in the window belongs to that window's payout, so the pool *is* the
  composition. Measured on clean data: **0 decoys across 120 lines.**

A decoy only exists when a window holds transactions belonging to some other payout. So the
same overlap that makes G5 reachable is the overlap that inflates the pool toward the
pigeonhole bound. There is no configuration where amount-based search is both informative and
interesting: the informative regime is the one with nothing to be ambiguous about.

**Therefore identifier recovery has to carry the load, and search is a small-pool fallback.**
Phase A (UTR and `setl_` recovery, §9.1) and Phase B (the B1 total index, §9.2) are not
optimisations that save Phase C some work — they are the only tiers that scale, because C1's
anchored residual search needs an identifier to anchor on and C2 refuses above
`C2_MAX_POOL = 35`. This reframes the detective too: its Pass A job of recovering identifiers
from degraded narrations is not a nice-to-have on top of a working search, it is what keeps
lines out of a tier that cannot answer them.

The pool distribution after injection, over the C1 candidate space (window pool ∪ the
settlement's own members):

```
  20-24  #########                                                                     9
  25-29  ##############################################################################  78
  30-34  ################################                                              32
  35-39  ##                                                                             2
  min 20   p50 28   p90 30   max 36     over C2_MAX_POOL=35: 1 of 121
```

`MAX_PAYOUT_ITEMS = 30` caps the baseline so that count + strays stays under 35. One line still
lands at 36 because injected transactions (a dispute, an instant payout) settle into windows
after that cap is applied. I left it: a single line above the bound is a truthful reading of a
dataset with breaks in it, and stage 8's C2 will refuse it by rule rather than search it badly.

### How ambiguity actually arises now

`SHARED_WINDOW_RATE = 0.10` of cycles host a second, smaller payout (`SECOND_PAYOUT_MAX_ITEMS
= 8`). The cycle's record budget is **split** between the two rather than added to, so the
combined pool does not grow at all.

Both payouts in a shared window net a cross-cycle refund. When those two refunds have equal
net, each line has two compositions that both pass G3 — *its own complete settlement plus
either stray* — and neither drops a member from its own group. That is the only ambiguity
coherence permits.

Every one of the 16 ambiguous lines on seed 42 has this exact shape. The symmetric difference
between the two alternatives is always **two transactions, both `settlement_id = null`, same
method, same catalogue amount** — no member swaps, no other shapes:

```
bl_0025  equivalent      rfnd_00705 refund upi 49900 setl=-
                         rfnd_00712 refund upi 49900 setl=-
bl_0038  consequential   rfnd_01027 refund upi 49900 setl=-
                         rfnd_01034 refund upi 49900 setl=-
   ... 16 lines, every symmetric difference is (stray, stray)
```

They come in consecutive pairs, which are the two payouts of one shared window: 8 of the 12
shared windows produced a collision.

Two mechanisms that look like they should work and do not, both measured rather than assumed:

- **Sticky prices alone.** Swapping an equal-net composition member for another drops a
  transaction from its own settlement, so the alternative is a partial slice and G3 rejects it.
  At 25× the sticky rate, real ambiguity was still exactly **0**.
- **Decoys from `TIMING_SHIFT` / `ONHOLD_RELEASE`.** They do put foreign transactions in a
  window, but the swap they enable is member-for-decoy — again a partial slice, again rejected.
  They widen pools without creating coherent alternatives.

`TARGET_AMBIGUOUS_RATE` is gone from the config. The rate is a measurement, not a setting.

### What actually sets the rate, stated plainly

Parent selection is no longer conditional on the window being shared. **Every** cross-cycle
refund prefers a catalogue-priced parent, and the two payouts of a shared window draw
independently from that population. Nothing rigs a particular line.

Five seeds, at the 40M offline budget:

| seed | ambiguous | rate | unproven |
|---|---|---|---|
| 42 | 16/134 | 11.9% | 3 |
| 43 | 16/134 | 11.9% | 2 |
| 44 | 10/134 | 7.5% | 1 |
| 45 | 8/134 | 6.0% | 0 |
| 46 | 6/134 | 4.5% | 1 |

Mean ~8.4%, range 4.5–11.9%. Decoupling did not collapse it — but the honest caveat is that
**the rate is set almost entirely by how many catalogue prices there are.** `STICKY_PRICES`
holds two (₹499 and ₹999), so two independent draws collide about half the time. Widen it to
the full twelve-price catalogue and ambiguity goes to **zero** (measured, seed 42, 2M budget:
8 lines with two prices, 0 lines with twelve).

So the dataset models a merchant whose revenue concentrates on two plan prices. That is a real
merchant profile and it is precisely §6.2's premise — "two ₹999 UPI payments have identical net
contributions" — but a wide-catalogue merchant would show no ambiguity at all at this scale,
and the 8.4% should be read as a property of the modelled merchant rather than a property of
reconciliation. Changing `STICKY_PRICES` is the single lever; it is two lines of config and
worth a deliberate decision rather than a default.

---

## Files

### `generator/breaks.py` — §5

Fifteen injectors over a mutable working copy of the dataset, each returning how many times it
actually fired, run in a fixed order with a `used` set so two breaks never compound on one
settlement. `inject()` re-derives every bank line's running balance afterwards, so the
statement stays internally consistent even where a break deliberately makes a line not tie.

*Questionable:* **three of §5's eighteen codes are not injected here, and the file says so
rather than faking them.** `TDS_DEDUCTION` and `CROSS_CYCLE_REFUND` are properties of *correct*
data that a naive matcher gets wrong — there is nothing to perturb, and an injector that
"fires" by doing nothing is the exact dishonesty the manifest test exists to catch.
`AMBIGUOUS_SUBSET` is emergent and is counted from what the gate found. A reviewer could
reasonably argue that 15 + 3 is a weaker deliverable than 18; the alternative was three
counters that lie.

Two injectors are worth reading closely:

- **`rounding_drift`** is the §4.3 allocation remainder and nothing else. It allocates
  `INSTANT_FLAT` across the payout's transactions by integer division, folds each share into
  `fee_paise` (I7 — never a separate term), and then sets the bank credit short by the dropped
  `total % n`. The bank deducted the whole ₹25; the ledger records only `n × per`. The test
  asserts the resulting delta satisfies §8.2's double cap — within ₹1 **and** within one paise
  per transaction — which is what makes it G4's business rather than a wrong subset.
- **`net_zero_settlement`** deletes the bank line outright (§5.1: no payout, therefore no line,
  ever) and writes the settlement into the `settlements` truth map that stage 3 left empty,
  with its `entity_ids` so the residue denominator can exclude them. Without that, those
  transactions sit unclaimed forever and the Phase E gap is permanently non-zero — a
  discrepancy that does not exist.

### `tests/test_breaks.py` — §5, §6.1

Twenty-four tests. Every count is **recounted from the emitted dataset** — dispute transactions by
type, reversals by narration, contamination by comparing each transaction's `settlement_id`
against the settlement that actually pays it out — rather than read back from the injector that
produced it.

*Questionable:* two codes are counted from the truth flags instead. `FX_MARKUP` leaves an
international payment that is indistinguishable from a baseline `intl_card` one, and
`NARRATION_TRUNCATED` emits a template baseline degradation also emits. Those two tests
therefore check consistency rather than reality, and the file says which ones and why. Pretending
otherwise would be the failure mode the file is named after.

The manifest assertion is exact: each per-break test asserts the manifest number **equals**
what the data contains, and a separate test warns when a break fired fewer times than
requested. `injected <= requested` was the original assertion and it was too weak — it passes
at zero, which is the one outcome the file exists to catch. A third test asserts every code
fired at least once.

**The recount found two real bugs on first run**, which is the whole argument for writing it
this way:

1. **`WITHHELD_RECORD` was silently manufacturing `ORPHAN_ORDER`s.** Deleting a payment left
   its order behind, so the tie-out found 10 orphans where the manifest claimed 6. §5 says a
   withheld record is "absent from all exports" — the order goes too. The manifest was lying by
   four.
2. **The withheld-gap detector was catching `SPLIT_PAYOUT` halves.** A split half legitimately
   does not tie to its whole settlement, so it looked like a gap. That one was a test bug, not
   a data bug, but it would have masked a real miscount later.

### The node budget, measured rather than assumed

`UNIQUENESS_NODE_BUDGET_OFFLINE` went from 2M to **40M**, on evidence. At 2M, 13 of 134 lines
went unproven; retried at 40M, **12 of the 13 resolve**, and three of those turn out to be
genuinely *ambiguous* — so the lower budget was not merely leaving uniqueness open, it was
hiding true-negative evidence behind an "excluded" flag. Costs, per line, at 40M:

```
bl_0038 pool=28 neg=4   1 solution     0.7s
bl_0112 pool=30 neg=5   2 solutions    6.1s     <- worst resolved
bl_9012 pool=36 neg=4   still unproven 15.7s    <- pool over C2_MAX_POOL
```

The full generate is ~60s, which is offline time nobody waits on; the live path still uses
`--live` at 20k. The one line that never resolves has a pool of 36, above `C2_MAX_POOL` — the
stage-3 bound predicting exactly which line cannot be settled by search.

### `core/coherence.py`, `generator/uniqueness.py` — changed

`classify` records an exhausted search as `uniqueness: "unproven"` with the real composition
and no exclusion flag, and no longer asserts that the intended composition is reachable. When G3 refuses the
real answer, truth now records `resolvable: true` with the real composition and
`g3_refuses_composition: true` — the matcher will miss it, and the miss is the documented cost
of a prior (§9.4). The count is **0** on seed 42 after the contamination fix below, but the
path exists so no future seed crashes the generator.

The gate's pool is now **C1's candidate space**: the window pool plus the settlement's own
members. §9.3 is explicit that once the settlement id is known, membership is a fact rather
than an inference — so a transaction that `TIMING_SHIFT` pushed out of the window is still
reachable, and uniqueness has to hold over everything reachable rather than over what C2 alone
can see.

### `generator/entities.py`, `generator/config.py` — changed

`build()` is restructured around a `make_payout()` closure so a cycle can host two settlements.
Cross-cycle refunds became baseline generation: `settlement_id = null`, settling inside the
payout's own window, deducted from it, drawn from the cycle's record budget so the count stays
exact. 77 of them on seed 42, and `is_plausible_payout` accepts every one as §9.4's second row.

*Questionable:* **in a shared window, both payouts prefer a catalogue-priced parent for their
cross-cycle refund.** This is the lever that makes equal nets likely enough to matter, and it
is a distributional choice, not an emergent one. The defence is that a refund reverses a
product purchase and product purchases sit on catalogue prices — the ±₹5 jitter is the
artefact here, not the collision, and §6.2 says as much when it points at two ₹999 UPI
payments. Nothing forces a *particular* line to be ambiguous; whether the two draws collide is
left to the rng, and the rate is reported rather than targeted.

`STICKY_PRICE_RATE` went from 0.012 to 0.05 to make catalogue-priced payments common enough to
be refundable. The high-noise `drop` probability went from 0.16 to 0.19 to centre the
unparseable rate on §3.4's ~30% (30.0% at seed 42; the assertion band is 20–40% because σ is
about 4 points at 120 lines, and a tighter band would fail on seed choice rather than on a real
change).

---

### `truth.json` has three manifest sections

| section | codes | scored |
|---|---|---|
| `break_manifest` | the 15 injected | per-break, `injected` / `caught` / `missed` |
| `emergent_breaks` | `AMBIGUOUS_SUBSET` | `count` / `refused` / `matched` |
| `baseline_properties` | `TDS_DEDUCTION`, `CROSS_CYCLE_REFUND` | never |

`AMBIGUOUS_SUBSET` sits with the scored breaks rather than the baseline properties because it
is the **true-negative class**: refusals on data nobody rigged are the only evidence G5 works
at all. The other two have nothing to detect — they are properties of correct data, counted so
a generator regression is visible and never scored. A test asserts the three sections are
disjoint and cover all eighteen codes.

## Deviated from the spec

**`SPLIT_PAYOUT` lines are `resolvable: true` with `requires_tier: "C3"`.** Truth describes the
data, not the matcher's current reach. These score FN until C3 exists in stage 13 and TP after,
with **no change to the truth file** — a truth file that flips at stage 13 would make every
measurement taken before it incomparable. Their `uniqueness` is `by_construction`: the gate
cannot verify a half-payout, because a half is a partial slice and G3 refuses it by design, so
the pair is what C3 will verify. `split_partner` names the other half.

**`DISPUTE_DEBIT` records are also `by_construction`.** A single cross-cycle `disp_*` matched by
B2 needs no search to be unique.

**`SETTLEMENT_CONTAMINATION` breaks two lines, not one.** The payout the mis-tagged transaction
really belongs to still passes G3 as "one complete settlement plus one item from another group"
and is merely flagged. The settlement it was tagged *into* can no longer be assembled at all,
because its own composition is now a partial slice of the tag group — so that line is
`resolvable: false`. That matches §17 ("detects, names the settlement and amount, refuses") but
it means one injection costs two lines, and the manifest counts injections.

The injector also had to be constrained: it now only picks source payouts already carrying **at
most one** cross-cycle stray. Contaminating a payout that already had two strays produces three
non-group items, which exceeds §9.4's "1–2" and makes G3 refuse the line the break was supposed
to leave merely flagged. That was caught by the generator crashing on `bl_0016`, and it is a
genuine interaction between a baseline property and an injected break rather than a coding slip.

**`FX_MARKUP` fired 4 times against a requested 5.** One chosen settlement had no domestic card
payment to convert. The manifest records 4, not 5, and the test asserts `injected <= requested`
rather than equality — a manifest that reports what it asked for instead of what it did is the
failure this stage is named after.

**`INSTANT_SETTLEMENT` allocates with no remainder** (5 transactions into ₹25 divides exactly),
so it does not also drift. Both breaks use `allocate()`, and keeping them orthogonal matters
for per-break scoring in §11 — otherwise every instant settlement would double-count as a
rounding drift.

**The instant premium is folded into `fee_paise` without recomputing `tax_paise`.** GST on the
premium is a real thing and this ignores it. The consequence is that §4.2's recompute check
would flag those rows, which is the honest cost; adding GST would change the net again and make
the drift arithmetic harder to read. Flagged rather than hidden.

## Deferred

**`caught` and `missed` in `break_manifest` are `null`.** Only scoring can fill them, and
`scoring/score.py` is stage 7. The keys exist so the shape does not change under stage 7's feet.

**Per-break recall.** §11's per-break table needs a matcher. The ambiguity rate *has* been run
across five seeds (table above); nothing else has, so every other number here is a single-seed
measurement until stage 14's regression harness.

**`STICKY_PRICES` holds two prices, and that is what sets the ambiguity rate.** Widening it to
the full catalogue takes ambiguity to zero. The current value models a two-plan merchant, which
is a real profile and is §6.2's own example, but it is a modelling choice that a reviewer should
be told about rather than left to discover — so it is stated in the finding above rather than
buried in config.

**Scoring owes three disclosed buckets alongside the headline.** Headline precision and
recall are measured over `uniqueness: "verified"` lines. Three sets sit outside that and each
has to be reported by name rather than folded in or dropped — counts are seed 42:

| bucket | seed 42 | what stage 7 must print |
|---|---|---|
| `uniqueness: "unproven"` | 3 lines, all `INSTANT_SETTLEMENT` | matched / refused / wrong. The composition is known, only its uniqueness is not |
| `uniqueness: "by_construction"` | 10 lines — **6** `SPLIT_PAYOUT` halves (`requires_tier: "C3"`) and 4 `DISPUTE_DEBIT` singles | the 6 halves score **FN until C3 lands in stage 13**, and the truth file does not change when it does; the 4 singles are B2's from stage 6 |
| `emergent_breaks.AMBIGUOUS_SUBSET` | 16 lines, `refused` / `matched` both `null` | refused vs matched. This is the true-negative class — a refusal here is the only evidence G5 works, and a match here is a fabricated one |

Nothing is excluded from scoring any more —
`excluded_from_scoring` is gone from the generator entirely. A line whose uniqueness the solver
could not settle is recorded `resolvable: true, uniqueness: "unproven"` with its real
composition, because the composition is known by construction and only its *uniqueness* is
unknown; those are different facts and collapsing them drops the line from every denominator.
Since search cost tracks negative-net items, the dropped set is exactly the hardest lines, so
excluding it inflates recall.

At the raised budget only **3 of 134 lines** are unproven on seed 42 (0–3 across five seeds),
down from 13, so the disclosed bucket is now small enough to read at a glance.

**`DUPLICATE_CREDIT` is generated but not detected.** §3.2's reversal-pair rule (equal
magnitude, opposite sign, adjacent day, similar narration) belongs to the matcher. Truth marks
both halves `resolvable: false`, so a matcher that never implements the rule scores them as
correct refusals — which flatters it. Worth revisiting when the rule lands.

**Nothing verifies that the 15 injectors are mutually independent.** They run in a fixed order
over a `used` set, which prevents two breaks on one settlement, but a break that changes a
*neighbouring* window (an instant payout settling into someone else's pool) is unconstrained.
The `bl_0016` crash was one instance of that class found by accident, not by a test.
