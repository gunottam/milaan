# Stage 10 — the trial balance, and a number derived twice

Written for someone who knows `docs/spec.md` and has not read the code.

Spec sections read: **§9.7** (Phase E), **§10** (exception ledger), **§10.2** (delta
diagnostics).

`pytest -q`: **198 passed, 0 skipped.** Twenty-three are new, all in `tests/test_audit.py`.

New files: `matcher/audit.py`, `matcher/diagnose.py`, `matcher/ledger.py`.

```
$ python -m scoring.score --run data/runs/seed42 --deadline-ms 0

  134 bank lines · 3009 transactions · 97 closed · 37 open

  residue gap ₹1,991.26   does NOT reconcile
      37 open bank lines                            ₹13,47,725.49
     528 unclaimed and due transactions             ₹13,45,734.23
    2481 claimed                                    ₹64,68,380.26   excluded (§9.7)
       0 not_yet_due                                        ₹0.00   excluded (§9.7)
       0 no_payout_expected                                 ₹0.00   excluded (§9.7)

HEADLINE — TP 90  FP 0  FN 2  TN 13   precision 100.0%   recall 97.8%

EXCEPTION LEDGER — 46 open, ₹18,82,686.28 at risk, aged from 2026-11-18
  DUPLICATE_CREDIT               6       ₹5,13,970.88
  WITHHELD_RECORD                9       ₹5,01,485.52
  UNIQUENESS_UNPROVEN            8       ₹3,92,357.40
  AMBIGUOUS_CONSEQUENTIAL       10       ₹3,06,219.44
  AMBIGUOUS_EQUIVALENT           4       ₹1,47,663.13
  ORPHAN_ORDER                   6         ₹14,545.00
  SETTLEMENT_CONTAMINATION       3          ₹6,444.91
  MALFORMED_HYPOTHESIS  811  (internal counter, §10.1)
```

The board did not move — same TP/FP/FN/TN as stages 8 and 9. Nothing in this stage matches
anything; it audits, types and prices what the ladder left.

---

## The one assertion the stage exists for

**Residue gap ₹1,991.26 = 199,126 paise. The four `WITHHELD_RECORD` injections on seed 42
delete records whose nets are 49,623 + 99,618 + 24,922 + 24,963 = 199,126 paise. Exactly.**

That is the strongest check in the suite, and it is worth being precise about *why*, because
it is easy to read as one more test passing.

Every other test in this project verifies that a rule does what it says. This one verifies
something the per-line analysis structurally cannot: E1 computes `Σ open bank lines` minus
`Σ unclaimed-and-due transactions` over the whole board. It never parses a narration, never
runs a tier, never learns which settlement was short. It subtracts one sum from another —
and lands on the size of a hole that the line-by-line work could only describe.

Three of the four withheld lines recovered **no settlement identifier at all**, so the ledger
can say nothing about their size (see §9.1: no anchor, nothing to hold the credit against).
The global sum knows anyway. That is the whole argument for Phase E in one number.

For it to land, every *other* open line must contribute exactly zero: the 14 ambiguous ones,
the 6 split-payout halves, the 6 duplicate-credit lines and their reversals, the 2 timing
shifts. An open line whose transactions are also unclaimed cancels on both sides of the
subtraction. Any leak in any of the four partition arms and the figure misses.

Asserted twice, on purpose:

| Test | Dataset | What it isolates |
|---|---|---|
| `test_the_residue_gap_equals_the_withheld_net` | one `WITHHELD_RECORD`, no other break | the arithmetic, unambiguously |
| `test_the_gap_survives_every_other_break_on_the_committed_board` | seed 42, all 15 injectors | that nothing else leaks |

The second is the real claim. The first is what tells you which half broke when it fails.
The isolated dataset needed `inject(..., counts=…)`, a one-line override on `BREAK_COUNTS`;
the default is unchanged, so no committed dataset moved.

---

## The four-way partition, and the arm that costs nothing on this data

| State | In the denominator? | Seed 42 |
|---|---|---|
| Claimed by a matched line | No | 2,481 txns |
| Unclaimed, `settled = true` | **Yes** | 528 txns, ₹13,45,734.23 |
| `settled = false` — not yet due | No | 0 |
| Member of a `no_payout_expected` settlement | No | **0 — see below** |

Two arms read zero, and they read zero for different reasons.

`not_yet_due` is zero because the generator settles everything it emits. The arm is tested
directly (`test_not_yet_due_transactions_are_not_in_the_denominator`) rather than left
untested on the strength of a dataset that never exercises it.

`no_payout_expected` is zero and **should not be.** Truth records two `NET_ZERO_SETTLEMENT`
groups. The matcher derives the classification itself — it has no access to `truth.json`, and
a real merchant's export does not come with a note saying which cycles netted out — by §5.1's
rule: a settlement whose net is zero produces no payout. On seed 42 that rule finds nothing,
because both net-zero groups net **+₹499** over their *tagged* members: the refund that
offsets them is a cross-cycle stray carrying `settlement_id = null`. The generator's
`Settlement` object counts it a member; the CSV does not; the CSV is all the matcher has.

The obvious repair — attach a stray to its parent payment's settlement — was tried and
**rejected**. Measured: it recovers one of the two groups and not the other, and it would let
any ordinary cross-cycle refund drag an unrelated settlement toward zero. A rule that is right
half the time about which transactions to *remove from the denominator* is worse than no rule,
because the failure direction is silently shrinking the thing you are auditing against.

The cost is bounded and it is why the gap is still exact: the group (+₹499) and its stray
(−₹499) both land in `unclaimed_due` and cancel there. **The census under-reports this arm;
the gap does not move.** Both facts are in the docstring at `no_payout_settlements`, and the
arm is tested on a hand-built settlement so it is exercised rather than merely written.

---

## Phase E on partial results — what stage 9 deferred

§9.10 requires that when the deadline fires, the ladder stops issuing work and **Phase E runs
on what was proved.** Stage 9 could not do this because `audit.py` did not exist. It does now,
through one function — `scoring.score.phase_e` — called unconditionally after `run_ladder`
returns, never behind a check on whether the clock was hit. `run_ladder` never raises, so
there is no path where the audit is skipped.

The accommodation the partial case needs is not mechanical, it is honest. A deadline-cut run
has open lines nobody looked at, and their whole target sits in the gap. So `Residue.reconciles`
is **three-valued**: `True`, `False`, or `None` when the run was cut. Answering `False` there
would report a discrepancy that does not exist — the gap would be measuring the clock, not the
books. The board prints `indeterminate — the run was cut short` and names why.

`test_phase_e_runs_on_partial_results` runs the ladder at `deadline_ms=1` and asserts the
partition still covers every transaction, `reconciles is None`, and the banner says so.

---

## The exception ledger — 46 rows, typed, priced, aged

§10's bar is one sentence: **`blocked_on` must name the missing input. "Could not match" is
not acceptable output.** A test asserts it on every row — a full sentence, six words minimum,
and the phrase itself is banned.

```
exc_0001  bl_0061      ₹1,24,363.46  WITHHELD_RECORD   low   >30d
         δ no_matching_residual · 0 hypotheses tried
         · No settlement id recovered; 0 tiers proposed 0 candidates and none balanced
         · -12436346 paise matches no fee, tax, premium, remainder or unclaimed net
         · The gap can be sized and located, not attributed (§17)
         blocked on: An identifier for this credit: nothing in the narration, the
                     reference or the amount index resolves ₹1,24,363.46 to a settlement.
         api_call: GET /v1/settlements?from=2026-06-18&amount=12436346
```

**Exception typing accuracy: 33 of 46, 71.7%.** The residual is entirely the two breaks whose
tiers do not exist yet (below).

**Ageing is reproducible.** `age_days` is measured from the statement's own last value date,
not from `today()`. §11 keeps machine-dependent numbers off the board, and a ledger that aged
by the wall clock would render different bytes tomorrow for the same input. A test builds the
ledger twice and compares the rendered text.

### `type_confidence` counts corroboration, not sentences

First cut derived `high`/`medium`/`low` from `len(evidence)`, and it read 29 rows `high`. That
was wrong in a specific way worth recording: the WITHHELD_RECORD path always appends three
sentences, and the third is *"the gap can be sized, not attributed"* — an admission that we
have nothing. Confidence was rising on the strength of saying we did not know.

Corroborating tokens are now counted separately from displayed evidence. For WITHHELD_RECORD
they are exactly three, each of which argues *for* the typing: a recovered anchor, a group
total that demonstrably does not close, a named delta cause. An unanchored line with an
undiagnosable residual scores zero and comes out `low` — which is the correct reading, since
that type is the residual class and everything unrecognised lands in it.

Distribution now: **20 high, 22 medium, 4 low.**

`EXCEEDED_SEARCH_BUDGET` overrides to `low` regardless of the count, because the typing is a
statement about this box's clock and corroborating it three ways would not make it hold on a
faster machine.

### The deadline-dependence sentence

Every deadline-cut row carries, in its evidence:

> This type is deadline-dependent and may differ on faster hardware: the clock ended this
> line, not the data (§11).

Appended *after* the confidence count, deliberately — a caveat is not corroboration. Zero rows
carry it on the committed board (`--deadline-ms 0`); the live run produces them, and
`test_deadline_cut_exceptions_disclose_that_the_type_moves_with_the_hardware` builds one
directly rather than depending on a timing race to exercise the path.

---

## The ambiguity split — 16 lines, and how they classify

You asked for this number specifically.

**Truth records 16 `AMBIGUOUS_SUBSET` lines: 11 consequential, 5 equivalent.**

**The ledger reaches 14 of them, and sub-classifies all 14 correctly — 10
`AMBIGUOUS_CONSEQUENTIAL`, 4 `AMBIGUOUS_EQUIVALENT`. Zero sub-class errors.**

The two it misses are `bl_0040` (consequential) and `bl_0067` (equivalent). Neither reaches
G5 at all: C2 declines above `C2_MAX_POOL` and the node budget expires elsewhere, so no tie is
ever observed and both are typed `UNIQUENESS_UNPROVEN`. That is the right refusal for the
wrong-looking reason — the line genuinely has two answers, and the search never got far enough
to see the second. Both still score as correct refusals in §11; only the *type* is off.

The split is **derived, not read.** `matcher/` has no access to `truth.json`. The ledger
compares the *book shape* of the tied compositions — types, methods, amounts, fee, GST, TDS and
settlement dates, with entity ids deliberately excluded, since ids are the one thing the
alternatives are guaranteed to differ in. Identical shape means either assignment posts
identical books, which is `AMBIGUOUS_EQUIVALENT` and a 30-second documentation task.

That function is `core.coherence.book_shape`, moved out of `generator/uniqueness.py` where it
was the private `_shape`. Both callers now share it — the generator's oracle stamps
`ambiguity_class` into truth with it, the ledger derives its own answer with it, and neither
imports the other. Had they drifted, exception typing would have been scored against a rule
the ledger does not apply, and the 14/14 agreement above would be measuring nothing.

Getting the tied compositions to the ledger needed one small change in the ladder: G5's refusal
`Verdict` carries only *"2 compositions tie at 0 paise"*, which is not enough to compare shapes.
`matcher/uniqueness.finalists()` is now exposed (the min-|delta| rule `resolve` already used,
lifted out rather than copied) and `run.py` records the tied compositions in the trace on a
refusal only — carrying the losers of every line would put the whole search space in the trace
for no reader.

---

## The 2 remaining FN — what the diagnostics say

`bl_0083` and `bl_0102`. Both `TIMING_SHIFT`. Both typed `WITHHELD_RECORD`, `low` confidence,
`delta_diagnosis: no_matching_residual`.

**The diagnostics are right, and the interesting part is what they rule out.** The residual on
each is the entire credit — ₹27,985.31 and ₹1,06,015.38 — and it matches no TDS sum, no GST
sum, no ₹25 premium, no allocation remainder, no unclaimed net, no FX markup. There is no term
missing. Nothing arithmetic went wrong.

What the row actually says is `hypotheses_tried: 0`. **No tier proposed anything.** The failure
is upstream of arithmetic entirely, which is exactly what a `no_matching_residual` on an
unanchored line means and why the confidence is `low` rather than `high`: nothing positively
argues for the typing, it is just where unrecognised failures land.

Following that upward:

```
bl_0083  narration 'NEFT-RZPSOFTW-HDFC0000060-NHDFC2-RZPSETTLE'   ref_no None
bl_0102  narration 'IMPS/NHDFC2/RZP SOFT/SETTLEMENT'              ref_no None
```

The truncated UTR is `NHDFC2` — 6 characters, squarely inside §3.4's 5–8 truncation range.
`regex_p.FRAGMENT_RX` is `N?[A-Z]{2,6}\d{2,}` and demands **two** trailing digits, so `NHDFC2`
is never emitted as a fragment and never reaches the §9.5 prefix cascade. `bl_0083` yields only
`HDFC0000060`, the IFSC, which prefixes no UTR; `bl_0102` yields nothing at all.

Meanwhile `TIMING_SHIFT` pushed 2 of `bl_0083`'s 27 members and 3 of `bl_0102`'s 30 out of the
date window, so C2's pool provably cannot contain the answer. C1 could ignore the window
entirely — §9.3, once the settlement id is known membership is a fact — but C1 has no anchor.
**This is §9.1's amendment landing exactly as written: a line with no recoverable identifier
has no tier that can answer it.**

**Not fixed here, and the one-character fix is not free.** Relaxing to `\d+` was measured:
`NHDFC2` then prefix-matches **123 of ~120 settlements** on both lines. That is not an anchor,
it is the whole board, and it would cost 123 anchored C1 searches per line for a G5 refusal at
the end. §9.5 anticipates this ("collisions are near-guaranteed... filter 3 does most of the
work") and the exclusivity filter would cut it hard under tier-major ordering — but that is a
Phase A recall/cost tradeoff to measure against stage 6 and 8's numbers, not a change to smuggle
into the audit stage. Recorded here so it is a decision rather than an oversight.

---

## `DUPLICATE_CREDIT` — a typing fix that was too cheap to skip

First measurement typed **15** lines `WITHHELD_RECORD` against 4 injected. Six of them were one
break: `bl_9008` and `bl_9009` and their kind — equal magnitude, opposite sign, adjacent day.
§3.2 hands over the detection rule outright, and the ledger was calling them missing records.

`reversal_pairs` implements three of §3.2's four conditions. Narration similarity is the fourth
and is not used: at `--noise high` roughly 30% of narrations are unparseable, so a string
comparison would fail on the pairs it is needed for most, and equal-magnitude-opposite-sign on
adjacent days is already tight enough that a false pair needs two unrelated payouts of identical
magnitude on consecutive days.

Only open lines are considered. A closed line has a balanced proof against real transactions,
and reversing that on a coincidence of amount and date would withdraw a match no gate rejected.

Result: 6 of 6 typed correctly, `WITHHELD_RECORD` down from 15 to 9, and §3.2's note that *the
balance column cannot detect this* is now a sentence in the evidence rather than a comment in
the spec. Scoring's `refusal-only` flag on `DUPLICATE_CREDIT` — six greens for code that did not
exist, flagged at stage 7 — is now earned.

---

## What is still mis-typed, and why

| Injected | Typed | Count | Cause |
|---|---|---|---|
| `SPLIT_PAYOUT` | `UNIQUENESS_UNPROVEN` | 5 | C3 is stage 13 |
| `SPLIT_PAYOUT` | `WITHHELD_RECORD` | 1 | C3 is stage 13 |
| `SETTLEMENT_CONTAMINATION` | `WITHHELD_RECORD` | 2 | the line the contamination was taken *from* |
| `SETTLEMENT_CONTAMINATION` | `UNIQUENESS_UNPROVEN` | 1 | same |
| `TIMING_SHIFT` | `WITHHELD_RECORD` | 2 | the two FN above |
| `AMBIGUOUS_SUBSET` | `UNIQUENESS_UNPROVEN` | 2 | never reached G5 |

Six of the thirteen are `SPLIT_PAYOUT` waiting on C3, which §16 places first on the cut list.
None of them is a false match; every one is a refusal wearing the wrong label, which is the
cheap failure class by design (§1).

E2's coherence audit flags 3 settlements correctly and independently of all of this — those are
matches that G3 *accepted* and a human should still see, which is why it is an audit and not a
gate: rejecting them would cost recall on every payout that nets a legitimate cross-cycle stray.

---

## Small things worth knowing

- **`gst_on()` added to `core/fees.py`.** §10.2 tests the residual against "₹25 + GST", and I1
  confines `Decimal` to that module. Everything else the diagnostics compare against is read
  straight off the transactions (`tds_paise`, `tax_paise`) — which is also the *correct*
  comparison, since rounding is per transaction and `Σ round(x)` ≠ `round(Σ x)`.
- **The FX check recomputes rather than reads.** FX markup folds into `fee_paise` and is never
  a separate term (I7), so the only honest way to ask what it cost is
  `expected_fee(txn) − expected_fee(replace(txn, international=False))`.
- **Diagnostic 4, the allocation remainder, is unreachable from a rejected claim** and is kept
  anyway. §8.2 accepts iff `|δ| ≤ 100` *and* `|δ| ≤ n`, so a rejected claim with `|δ| ≤ n`
  needs a composition of over a hundred items and §15 caps payouts far below that. It fires on
  residuals that never met a gate. Documented at the branch so nobody "simplifies" it away.
- **`amount_at_risk_paise` and `residual_paise` are different numbers** and both are on the
  record. The first is the whole credit; the second is the gap a line could size against a
  recovered settlement, or `None` when it recovered none.
- **`MALFORMED_HYPOTHESIS` reads 811.** All of it is deterministic tiers re-proposing a set an
  earlier line consumed, caught by G1 (§7.4). It is the counter the model proposer will be read
  against at stage 12, and it is a counter rather than a row because no bank line owns it.

---

## Invariants

Untouched. `matcher/` still cannot reach `truth` — the ambiguity split, the net-zero
classification and the reversal-pair rule are all derived from the CSVs. `Verdict` is not
imported in `ledger.py` or `diagnose.py`, so I2 holds structurally: nothing added this stage can
approve anything. An accepted `unresolvable` is still not a match (I4).

`pytest tests/test_invariants.py`: green.
