# Stage 13 — C3, and the six lines that were never six

`pytest -q`: **220 passed in 9 s.** `pytest -q -m slow`: **76 passed in 3 m 30 s.**
Nine new unit tests, four new board tests, one new tier.

**Headline: C3 closes one of the six `SPLIT_PAYOUT` halves, not six. Precision
stayed 100.0% with FP 0. All-lines recall 94.3% → 95.2%.**

| committed board, 40M budget, `--deadline-ms 0` | closed | TP | FP | FN | TN | precision | recall |
|---|---|---|---|---|---|---|---|
| through C2 | 99 | 99 | 0 | 6 | 29 | 100.0% | 94.3% |
| **through C3** | **100** | **100** | **0** | **5** | **29** | **100.0%** | **95.2%** |

The brief predicted six lines and 2× the detective's addressable population. It got
one line. **The other five are not a search failure — the input does not contain the
answer, and truth asserts one anyway.** That is the finding of this stage and the
rest of this document is the arithmetic behind it.

---

## The representation, worked out before the search

`Claim` gained one field: `joint_with: tuple[str, ...]`.

A split payout is the one composition in the whole design whose coherence cannot be
judged from one bank line. The bank took one settlement and posted it as two
credits, so each credit's own composition is **a partial slice of a settlement** —
and G3 refuses partial slices by design (§9.4). That refusal is correct and must
stay correct. So the pair has to be expressible without weakening it.

The split, and it is the only one that leaves every gate meaning what it meant:

| gate | reads | why |
|---|---|---|
| G1 exclusivity | `composition` for spend, `composition + joint_with` for existence and window | The partner half is **cited, never spent** |
| G2 arithmetic | `composition` alone | This credit against this line's target. Exact, delta 0 |
| G3 coherence | `composition + joint_with` | The shape a payout must have is a property of *the payout*, not of either credit the bank cut it into |
| G4 tolerance | unchanged | Never consulted; a split closes exactly or not at all |
| G5 uniqueness | unchanged | Per line, on `composition`. Both halves are judged separately |

`composition` stays what it always was — what **this** line consumes — so nothing
downstream changed: scoring is still set equality on `composition` (I5), the residue
partition still reads compositions (§9.7), `claimed` still grows by `composition`
alone. The one test that proves the field is load-bearing rather than decorative:

```python
bare   = Claim("bl_0001", ("pay_a", "pay_b"), anchor_settlement_id="setl_x")
joined = Claim("bl_0001", ("pay_a", "pay_b"), anchor_settlement_id="setl_x",
               joint_with=("pay_c", "pay_d"))
assert check(bare,   line, txns).gate == "G3"     # partial slice, refused
assert check(joined, line, txns).ok               # a payout, approved
```

Same composition, same line, same arithmetic. The partner half is the only
difference and it is what makes the payout a payout.

### G1's one exemption, and why it cannot create money

`joint_with` is deliberately **not** run through the `claimed` test. Both halves
walk the gate chain independently in the same tier sweep, so by the time the second
reaches it the first has legitimately spent its half — rejecting there would refuse
a pair on the strength of its own success.

Nothing is double-spent by the exemption, and the reason is structural rather than
careful: G2 sums `composition`, the ladder adds `composition` to `claimed`, and
§9.7's four-way partition reads compositions. A wrong `joint_with` buys a G3
approval on a premise G1 could not check — **exactly the standing
`anchor_settlement_id` has had since stage 8**, and the reason C3 asserts one only
after it has found the whole payout and balanced it against both credits.

I did not add `partner_bank_line_id` to `Claim`. No gate reads it, and I9's
discipline is that the claim carries what the gates read and nothing else. The
partner id lives on the tier, where the refusal string and the ledger use it.

### No ladder surgery

C3's whole search runs in `prepare()`, the hook the ladder already offers batching
tiers (§9.6 uses it for the detective's 25-narration batches). A pair is not a
property of one line and the `Proposer` protocol is per-line, so the sweep plans
every pair once and `propose()` hands each line what the plan holds for it. Two
independent claims, two independent `check()` calls, two independent closures.
`run.py` gained one line in `build_tiers` and nothing else.

---

## The measurement

C3 found all three pairs on the first propagation pass, from 16 window-compatible
pairs out of 595, in **under 0.1 s**. It paired the right lines with the right
settlements every time and proposed no spurious pair at all.

Then it tried to say which transactions sat behind which credit. Brute-forced with
meet-in-the-middle, here is what the input actually determines:

| pair | settlement | payout | joint credit | divisions that balance | outcome |
|---|---|---|---|---|---|
| `bl_0101` + `bl_9001` | `setl_0101` | 6 txns | ₹19,790.60 | **1** | `bl_0101` **closed** |
| `bl_0019` + `bl_9002` | `setl_0019` | 23 txns | ₹67,269.20 | **6** | both refused |
| `bl_0048` + `bl_9003` | `setl_0048` | 30 txns | ₹87,831.60 | **279** | both refused |

Truth records one of those 279 as `bl_0048`'s composition, with
`uniqueness: "by_construction"`. It is the division the generator's greedy prefix
happened to cut (`generator/breaks.py::split_payout` accumulates `w.members(s)` in
order until it passes half). Nothing in the three CSVs distinguishes it from the
other 278.

**This is finding 8.4 on the bank-line side.** §6.2 already says it, about the
mirror case: *"Truth must mark the whole set unresolvable rather than asserting a
specific assignment — otherwise scoring penalises an answer that is
bookkeeping-identical to truth."* Stage 4 applied that rule to two bank lines with
identical amounts and did not apply it to `SPLIT_PAYOUT`. The 279 divisions are the
same situation one level down: the payout is proved, the attribution is not, and
truth asserts an attribution.

I did not change truth. Stage 4's ruling — a truth file that flips at stage 13 makes
every measurement taken before it incomparable — is right, and it is more valuable
than four TPs.

### The sixth line refuses for a different reason

`bl_0101` + `bl_9001` has exactly one division, and one of the two still refused.
Its payout is `setl_0101` plus a cross-cycle stray of −₹999.00, and **two identical
refunds each compose that residual** (`rfnd_02558`, `rfnd_02564`). So C3 proposes
two payouts. `bl_0101`'s half is a single payment and is the same under both, so it
closes. `bl_9001`'s half holds the stray, differs between them, and G5 refuses.

One pair, two outcomes, both correct — and the refusal is §6.2's ordinary repeated
pricing, not a split-payout problem at all.

### What I refused to do, and what happened when I checked it

The tempting move is a tie-break prior: assume the bank posts the earlier
transactions in the first credit, order the payout by `settled_at`, cut at the
credit. That is the same *kind* of rule as G3 — an empirical claim about how payouts
are assembled — so it deserved a measurement rather than a principle. Prefix of the
payout, ordered three ways, against truth's division:

| ordering | `bl_0019` | `bl_0048` | `bl_0101` |
|---|---|---|---|
| `settled_at` | ✗ | ✓ | ✗ |
| `created_at` | ✗ | ✗ | ✗ |
| `entity_id` | ✓ | ✓ | ✓ |

**`settled_at` recovers one of three.** So it is not even a working shortcut — a
prior with a 33% hit rate on three cases is noise, and shipping it would have
converted four honest refusals into some mix of TPs and false matches with no way
to tell which from the input.

The ordering that recovers all three is `entity_id`, and that is the finding rather
than the loophole. `w.members(s)` returns members sorted by entity id and the
injector takes a prefix of that list, so **entity-id order is the answer key
wearing a column name.** An export row ordering carries no accounting meaning at
all; a bank does not divide a payout alphabetically. §17: *"it does not invent
distinctions to break ties."* A prior that fits the oracle and nothing else is not a
prior, it is the oracle.

---

## The ledger, which is the other half of the stage

Before C3, the six halves were typed:

```
bl_0019  UNIQUENESS_UNPROVEN   medium     at_risk
bl_9002  UNIQUENESS_UNPROVEN   medium     at_risk
bl_0048  UNIQUENESS_UNPROVEN   medium     at_risk
bl_9003  UNIQUENESS_UNPROVEN   medium     at_risk
bl_0101  UNIQUENESS_UNPROVEN   medium     at_risk
bl_9001  WITHHELD_RECORD       medium     at_risk
```

Stage 10 called this refusals wearing the wrong label, and it was worse than a
mislabel. `UNIQUENESS_UNPROVEN` says *give it a bigger node budget*, which would
never have helped. `WITHHELD_RECORD` says *a source record is missing from the
gateway export* and prices the whole credit as money the books cannot account for —
on a line whose settlement was sitting in the export the entire time, complete.

After C3, one line is closed and the other five read:

```
exc_0036  bl_0048   ₹44,453.90  SPLIT_PAYOUT   high   documentation   setl_0048
   · setl_0048 ties to this credit and bl_9003 jointly to the paisa, but 2 different
     sets of its transactions balance against this credit and the statement does not
     say which of them this credit carried
   · 2 sets of the payout's transactions balance against this credit exactly;
     G5 withdrew approval rather than pick one
   · Nothing is unaccounted for — the pair contributes zero to the residue gap,
     because the payout sits on one side of §9.7's subtraction and both credits on
     the other
   blocked on: A bank advice naming the transactions behind each credit: the payout
               ties out jointly to the paisa, and the statement does not record how
               it was divided.
   human_documentation: Book the settlement against both credits as one payout; the
               division between them changes no figure in the books.
```

Three things moved and each of them matters more than the recall point:

**The type is right.** `SPLIT_PAYOUT` is in §5's taxonomy and this is now the code
the ledger emits for it. Exception typing is a scored metric.

**The price is right.** `SPLIT_PAYOUT` joins `DOCUMENTATION`, so it leaves
`at_risk_paise` — **₹1,62,900.87 moved out of "the books cannot account for this"
and into "needs a note"**, and `bl_0101`'s ₹11,990.53 left the ledger altogether.
The justification is arithmetic rather than editorial: the payout sits on one side of E1's subtraction and both credits on the
other, so the pair contributes exactly zero to the residue gap. The face value here
is also the payout counted twice, which is the second reason it was never a risk
figure. Both halves sort last, with `AMBIGUOUS_EQUIVALENT`, because a documentation
task is not an investigation.

**`blocked_on` names the missing input.** A bank advice. Not a bigger budget, not a
missing record — the one document that would settle it, which no gateway API call
can produce.

The residue gap did not move: ₹1,991.26, of which ₹1,990.90 predates any match. C3
closing `bl_0101` moved both sides of the subtraction by that line's own delta,
which is zero.

---

## Two things the stage broke that were worth breaking

### Propagation stopped being a replay

`test_propagation_pass_two_is_a_replay_on_this_data` failed, and it failed for the
right reason. Its docstring said pass 2 is byte-for-byte identical on seeds 42, 7,
99 and 2026, and that §9.8's mechanism — resolving one line shrinks every other
pool — never fires here because cycles are spaced `window_days + 1` apart.

C3 closing `bl_0101` is **the first closure on this board that removes a transaction
from a different line's window pool.** `bl_0100` shares the cycle; one transaction
lighter, its C2 search finds two solutions in pass 2 where it found none in pass 1:

```
moved: {("bl_0100", "C2"): (0, 2)}
```

G5 refuses both, so nothing closes and pass 2's payoff is still zero. But the
mechanism is demonstrably live now, and the test pins that one movement exactly
rather than tolerating movement in general. Stage 14's 10-seed regression is still
where the second propagation pass earns its 4 seconds or gets deleted.

### `test_the_full_ladder_closes_99_of_134` was measuring seven tiers

The `full` fixture is `build_tiers(...)[:7]`, so it stopped at C2 and passed
unchanged after C3 landed — **the slow set went green on a board C3 had never
run.** Exactly the trap `CLAUDE.md` warns about, arriving through a fixture rather
than through a missing `-m slow`.

I left the fixture at seven tiers and documented why: it is the baseline the stage-13
delta is measured against, and re-pointing it at the whole ladder would have moved
the number the delta is measured from. `tests/test_split.py::with_c3` runs the
ladder entire and pins 100 closed, TP 1 / FN 5 across the `by_construction_c3`
bucket, FP 0, and the headline bucket unmoved at TP 88 / TN 13.

---

## Two smaller fixes, both found by the stage rather than by me

**`settlement_id` on the ledger row was wrong for `bl_9001`.** The draft took
`anchors[0]` — every settlement *any* tier recovered for the line — and A3's prefix
cascade contributes candidates it could not close, so an alphabetical first put
`setl_0000` on a record whose payout is `setl_0101`. The SPLIT_PAYOUT draft now
reads C3's own anchor, and the test asserts the id appears in the sentence beside
it, so the two cannot disagree again.

**`test_provenance_is_on_the_result_never_on_the_claim` was already failing on
`main`,** before this stage, and I confirmed that against a clean tree rather than
assuming it. It pinned `ablation.detective_available is False`, which reads whether
*this box* holds credentials — true since stage 12a put a key in `.env`. That made
the suite pass or fail on whose laptop ran it, which is precisely §11's objection to
machine-dependent numbers. The assertion is now `detective_ran is False`, which is
the fact the test is actually about.

`.venv` cannot run the suite at all — `dotenv` and `httpx2` are missing from it, so
three modules fail at collection. Every number here is from the system 3.11
interpreter, which has both. Worth fixing before stage 14 so the two interpreters
do not disagree about what green means.

---

## What C3 cost

| | |
|---|---|
| new module | `matcher/proposers/split_p.py`, 235 lines |
| `Claim` | +1 field |
| gates | G1 and G3, one clause each. G2, G4, G5 untouched |
| `run.py` | +1 line in `build_tiers` |
| ledger | +1 type, +1 branch, +1 `DOCUMENTATION` entry |
| wall clock | pair search < 0.1 s; full live run 7.8 s of the 60 s ceiling |
| recall | +1 line, +0.95 points all-lines |

§16 puts C3 first on the cut list. On this seed it bought one line of recall and the
correct typing, pricing and `blocked_on` sentence for five more — and it is the
tier that established the five are not missing records. If something has to go for
stage 14, the honest reading is that **the tier earns its place through the ledger
rather than through the scoreboard**, which is not the case the brief made for it.

---

## Standing question for stage 14

Is per-line composition the right unit for scoring a split payout?

The five refusals are correct under I5 and I use them as correct throughout this
document. They are also the design refusing to answer a question the merchant did
not ask: nobody needs to know which of `setl_0048`'s 30 transactions sat behind
which of two same-day credits from the same bank, because every one of them is tied
out, to the paisa, on the same settlement and the same date, whichever way it is
booked. Scoring the *pair* — the agent's union across both lines against truth's
union — would read 6 TP and would still catch a wrong composition as FP, because
`split_partner` is already in the truth record and the union is exact.

I did not do it in this stage. Changing the scoring rule in the same commit that
adds the tier the rule would reward is how a measurement stops being one, and it
belongs in the regression stage with all ten seeds visible rather than here with
one. Recording it as an open question and the number it would produce.
