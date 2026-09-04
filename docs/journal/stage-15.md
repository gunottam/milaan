# Stage 15 — one rule, in front of the ladder

`pytest -q`: **243 passed in 10 s**. `pytest -q -m slow`: **79 passed in 3 m 34 s**.
`node check-strip.mjs`: **37 checks, all ok**. All inside `.venv`, installed from
`pyproject.toml`.

No new module, no new tier, no new gate. One call added to `run_ladder`, one default argument
added to a function that already existed, and three paragraphs of spec that were wrong.

**Precision reads 100.0% on all ten seeds, and recall went up.**

| | stage 14 | stage 15 |
|---|---|---|
| precision | 99.71% ± 0.44% — **3 FP** on seeds 7, 13, 101 | **100.0% ± 0.0% — 0 FP** |
| all-lines recall | 92.55% ± 1.59% (90.27 – 95.24) | **92.82% ± 1.42%** (90.83 – 95.24) |
| headline recall | 97.03% ± 1.97% (94.90 – 100.0) | **97.33% ± 1.90%** (94.90 – 100.0) |
| lines withheld from every tier | — | 60 across 10 seeds, **0 of them resolvable** |

That combination is the thing worth reading twice. A pre-match exclusion is a *restriction*:
by §1's taxonomy the only failure it can have is withholding a line that had an answer, so
the expected price of buying three false matches back was some recall. It cost none, and it
returned one true match on each of the three seeds it fixed — because the transactions the
duplicate had been eating went back to the line that had actually earned them.

---

## The bug, restated in one line

§3.2's reversal-pair rule existed, was correct, was tested, and ran **after** the ladder.

`matcher/ledger.py::reversal_pairs` has implemented it to the letter since stage 10 — equal
magnitude, opposite sign, adjacent calendar day. It ran once, over the lines still open,
for exception *typing*: to put `DUPLICATE_CREDIT` and a `⇄ bl_9007` partner on a ledger row.
Nothing consulted it before a tier proposed. So on every seed, three duplicate postings went
into the ladder as ordinary credits, each of them a byte-identical twin of a real payout, and
§9.8's `(pool size, bank_line_id)` sort decided which twin got the settlement.

Seed 42 got it right three times out of three, by tie-break. Seeds 7, 13 and 101 got it wrong
once each. `scoring/score.py` had a comment predicting exactly this since stage 7, and stage
14's regression is what cashed it.

### And it cost the ledger two rows, on exactly those three seeds

This one was in the committed file and nobody read it. `regression.json`'s per-seed
`ledger.by_type` says `DUPLICATE_CREDIT: 6` on seven seeds and **`4` on seeds 7, 13 and 101**
— the three with the false match.

That is the same bug seen from the other end. §10's typing pass runs `reversal_pairs` over the
lines *still open*, and one half of the pair had been closed by a tier, so it was not a
candidate. Its partner then had nobody left to pair with. **One wrong match deleted both rows
of the pair from the ledger**, so a human looking at seeds 7, 13 and 101 saw four duplicate
postings where the bank had made six, with no indication that two were missing. The break
count and the exception count disagreed and neither was flagged.

After the exclusion all three read `6`, on every seed. That is not a fix for a second bug; it
is the same rule reaching the same six lines from in front of the ladder instead of behind it.

---

## The fix

```python
# matcher/run.py, before the first tier opens
excluded = reversal_pairs(bank_lines)
...
open_lines = [b for b in bank_lines
              if b.bank_line_id not in matched
              and b.bank_line_id not in excluded]
```

Three decisions in that, and each of them had a wrong version that would have looked fine.

### It reuses the rule, it does not re-implement it

`reversal_pairs` gained one optional argument:

```python
def reversal_pairs(bank_lines, open_lines: Iterable[str] | None = None) -> dict[str, str]:
    wanted = ({b.bank_line_id for b in bank_lines} if open_lines is None
              else set(open_lines))
```

`None` means every line, which is the pre-match scope — before anything has matched, "open"
*is* every line. §10's typing pass keeps passing its explicit set.

A second copy of the rule in `matcher/run.py` would have been three lines shorter to write
and would have had exactly the failure mode the generator and the matcher nearly had over
coherence: two implementations of one empirical claim, drifting one edit at a time, with
nothing that fails when they disagree. The rule has four conditions in §3.2, only three of
which are implemented (narration similarity is deliberately unused — at `--noise high` about
30% of narrations are unparseable, so a string comparison would drop the pairs it is needed
on most). Any future argument about the fourth condition has to land in one place.

### The two scopes agree by construction, and that is not good enough

The pre-match call sees every line; the ledger's call sees the lines still open. They return
the same map only because an excluded line is never matched and is therefore still open when
the ledger looks. That is a real argument and it is also exactly the kind of argument that
survives right up until somebody changes one of the two call sites. So it is pinned on the
134-line board instead:

```python
def test_the_ledger_types_exactly_what_the_ladder_excluded(twice):
    ...
    assert set(run.excluded) == typed
    assert len(typed) == 6
```

The `== 6` is there so that a generator change which stopped injecting duplicates cannot make
the test pass by giving both sides nothing to find.

### It is an exclusion, not a gate

The tempting place to put this is `G3`, or a new `G0`. Both are wrong for the same reason: a
gate sees a *candidate composition*, and by the time a composition exists the wrong question
has already been asked. `check()` would have had to learn what makes a bank line not a payout
at all, which is a fact about the statement and has nothing to do with whether an assembly of
transactions balances. I8 says tiers select and gates approve; this rule does neither. It
decides what may be proposed on.

It also earns its place in §1's monotonicity table, which now carries a row for it. The
table is about *failure direction*, and an exclusion's direction is the same as a restrictive
gate's: it can only remove candidates, so a wrong pairing costs recall and can never approve
a wrong answer. That is the entire licence for shipping a three-condition heuristic in front
of a system whose thesis is deterministic verification.

### An excluded line is not `EXCEEDED_SEARCH_BUDGET`

The easy bug in this change is a one-line one. `Run.exceeded` is derived as "not matched and
not walked", and an excluded line is never walked, so without a third clause all six of them
land in §9.10's population — which sets `deadline_hit`, prints the banner, and tells a reader
*"deadline reached — 6 lines unattempted"* on a run where no clock was even armed. Two
sentences that score identically and are not the same fact, which is the thing §9.10's banner
exists to keep apart.

So `exceeded` excludes them, `cut` cannot reach them (they leave no trace rows), and there is
a test whose whole job is that distinction:

```python
def test_an_excluded_line_is_not_a_deadline_casualty():
    assert set(run.exceeded).isdisjoint(run.excluded)
    assert set(run.cut).isdisjoint(run.excluded)
    assert run.exceeded == () and run.banner() == []
```

The per-line deadline divisor moved for the same reason: `min(2000, remaining / unmatched)`
was dividing the remaining time by lines that will never be offered a tier, which
under-allocates every real line's slice. Offline runs have no clock so no measured figure
moves; the live run gets its honest fair share.

---

## What it did, line by line

### Seed 42's board is byte-identical, and five pinned counts still moved

Nothing on seed 42's scoreboard changed: 100 closed, 95.24% all-lines, 100.0% headline, 0 FP,
the same 34 open lines, the same residue gap. The six duplicate lines were already open there,
because the tie-break happened to go the right way three times out of three.

What moved is everything derived from the **trace**, because six lines that used to be offered
eight tiers twice a pass now leave no trace rows at all. Five slow-set assertions failed on
the first run and every one of them was a real number changing, not a broken test:

| assertion | before | after | what it means |
|---|---|---|---|
| `run.exceeded` under a 1 ms deadline | 134 | **128** | the six are not the clock's casualties |
| A1 pass-1 encounters | 81 | **79** | two duplicates used to reach A1 |
| A1 pass-1 `won` | 40 | **40** | neither ever closed there |
| A1 pass-1 stale rejections | 2 | **0** | both of those two were G1 rejections |
| A3 pass-1 encounters | 21 | **19** | two more reached the cascade |
| A3 pass-1 stale rejections | 825 | **751** | the bulk G1 rejections left with them |
| `anchors_recovered.recovered` | 101 | **97** | four recovered a settlement id |
| `anchors_recovered.wrong` | 0 | **0** | stage 11's revert condition, untouched |
| `anchors_recovered.true_anchor_present` | 84 | **84** | unchanged, and that is the finding |
| `anchors_recovered.no_true_anchor` | 17 | **13** | all four losses were here |

Read the last three rows together. The four anchors the census lost were **all** in
`no_true_anchor` — a settlement id parsed off a bank line that has no true settlement, because
it is a duplicate posting of one. `true_anchor_present` did not move by a single line. So the
anchor census did not get worse; it stopped counting four recoveries on lines that were not
payouts. The same is true of A1's two lost encounters: both were stale G1 rejections, and A1's
`won` count is identical.

A bank's duplicate posting carries the original's narration byte for byte, which is exactly
why these lines parsed so well and exactly why parsing was never going to separate them. The
distinguishing fact was never in the narration — it was the contra on the next day.

The sixth movement is the one worth naming separately, because it is the bug this change could
have shipped. `Run.exceeded` is derived as "not matched and not walked", an excluded line is
never walked, and without a third clause all six landed in §9.10's population — which sets
`deadline_hit`, prints *"deadline reached — 6 lines unattempted"*, and says the clock stopped
work that never existed. It is one `and` in a generator expression and it would have put a
false sentence at the top of every board.

---

## The thing I did not expect: nine C3 refusals that were about nothing

`SPLIT_PAYOUT` refusal halves across the ten seeds went **61 → 52**, and not only on the
seeds with the false match:

| seed | `SPLIT_PAYOUT` | `DUPLICATE_CREDIT` | `UNIQUENESS_UNPROVEN` | other |
|---|---|---|---|---|
| 7 | 9 → **6** | 4 → **6** | 3 → **4** | — |
| 99 | 7 → **6** | 6 | 6 | `AMBIGUOUS_CONSEQUENTIAL` 4 → 5 |
| 5 | 5 → **4** | 6 | 7 → **8** | — |
| 13 | 8 → **6** | 4 → **6** | 2 | `AMBIGUOUS_EQUIVALENT` 3 → 4, `WITHHELD_RECORD` 7 → 6 |
| 101 | 8 → **6** | 4 → **6** | 5 | — |
| 42, 2026, 1, 23, 777 | unchanged | unchanged | unchanged | unchanged |

Row totals are identical on every seed — 40 exception rows on seed 7 before and after, 42 on
seed 99, and so on. Nothing appeared or vanished; nine lines were **retyped**.

Look at the odd numbers. Nine and seven and five are odd counts for a break that comes in
halves, and that is the tell: **C3 was pairing a real credit with a duplicate posting.** A
duplicate carries the original's amount to the paisa, so a settlement that ties out against
(real credit + duplicate credit) ties out exactly as well as against (real + real), and C3
found two solutions and refused — correctly, by its own rule, over a pairing that could not
exist. The duplicate half then sorted into `DUPLICATE_CREDIT` (§10.1 types a reversal pair
first) and its "partner" was left holding a `SPLIT_PAYOUT`, which is why the counts came out
odd.

**Those refusals were on the board, with their census.** The refusal block is the strongest
claim this project makes — *279 divisions of `setl_0048`'s payout balance against this credit,
and the statement does not say which* — and nine of the halves under it were divisions of a
settlement against a bank line that was never a payout. Seeds 99 and 5 carried one each and
neither has ever had a false match, so this was not a symptom of the FP: it was a second
consequence of the same missing rule, and no metric on the board was going to surface it.

`at_risk_paise` moved with the retyping, in both directions, because `SPLIT_PAYOUT` is priced
as documentation and `UNIQUENESS_UNPROVEN` and `AMBIGUOUS_CONSEQUENTIAL` are priced as money:
seed 13's at-risk fell ₹62,591.16 and seed 7's rose ₹58,519.03. Neither figure was wrong
before or right now in isolation — what changed is that they are now about lines the bank
actually needs someone to look at.

---

## The exclusion's cost, priced

An exclusion trades recall for correctness by construction, so the trade has to appear in the
artefact rather than in an argument. `regression.json` now carries it per seed:

```json
"excluded": {
  "lines": ["bl_9004", "bl_9005", "bl_9006", "bl_9007", "bl_9008", "bl_9009"],
  "pairs": 3,
  "withheld_resolvable": []
}
```

`withheld_resolvable` is the cost: lines withheld from every tier that `truth.json` says had
a composition. It is **empty on all ten seeds** — the rule withheld 60 lines and every one of
them was an injected duplicate posting or its contra. Measured in `scoring/` and not in
`matcher/`, which cannot reach the answer key (I3).

It is reported even though it is zero, because "we checked and it was zero" and "we did not
check" produce the same silence. `summary.excluded.costs_no_recall_on_any_seed` is the claim,
and the board renders it beside the false-match claim rather than in a footnote.

**This is the number to watch on real data.** The rule needs two unrelated payouts of
*identical* magnitude on consecutive days with opposite signs to fire wrongly, which is
implausible in a generator with a paisa-level amount distribution and entirely plausible in a
production statement full of round numbers. §17's honest statement is that the failure would
be a refusal on a real payout, visible in the ledger as a `DUPLICATE_CREDIT` row that names a
partner a human can see is not a contra — which is the class of failure this whole design
prefers.

---

## The two amendments

Both are stage-14 findings that get written down rather than built. The spec was frozen at
v1.3, and each of these changes what it *claims*, so §18.1 records them as v1.3.1 instead of
editing the frozen text silently.

### §15's Phase D allocation is not enforceable by §9.10's mechanism

The budget table gives Detective A 3 s and Detective B 9 s. There is no mechanism that can
hold them to it. There is one clock, `MATCH_DEADLINE_MS`, and it is checked in two places:
between tiers, and before each line. That bounds every *search* tier, because a search tier
does its work per line and can be stopped between two of them. A batching tier does its work
in `prepare()`, before the sweep — §9.6 batches 25 narrations and 5 hypotheses per call while
the `Proposer` protocol is per-line, so batching cannot live inside `propose()` — and **a
batch already in flight cannot be interrupted.** The deadline has no purchase inside a network
round trip.

The consequence is legal and measured: a run can pass the between-tiers check at 21.9 s of a
22,000 ms deadline, open D1, and return well past the 60 s ceiling. Stage 14's ten seeds ran
**33.8 – 80.7 s** with the model answering against **12.5 – 24.2 s** ablated, breaching on two
of the six seeds where Groq answered at all.

Two honest options:

1. **Enforce it** — a per-tier deadline plus a cancellable client, so `prepare()` abandons
   in-flight batches at its allocation. That is real work and it changes what a partial Phase
   D means.
2. **Do not spend the budget.**

Option 2, and it is a measurement rather than a preference: **Phase D closed zero extra lines
on all ten seeds**, for 297 paise of tokens. A phase that can cost 59 s and returns nothing is
not a phase a demo should run.

### The demo runs `use_llm: false`, and the ceiling is asserted for that configuration

`api/main.py::RunRequest.use_llm` already defaulted to `False` and `web/src/App.jsx` already
sent `false`. Nothing in the code changed; what changed is that it is now the recorded
decision with the number behind it, rather than a default nobody had argued for. §7.2's
ablation is a filter over the tier list, so "off" needed no new code — and the ablation delta
it reports is **0.00**, which is the finding, not a disappointment about the harness.

The regression's live pass therefore runs ablated by default. `--detective` still measures
Phase D for anyone who wants the comparison; the committed artefact has no model in its
`live s` column at all. That also removes the trap CLAUDE.md warns about: Groq's free tier
caps tokens per day at 200,000, a ten-seed live pass exhausts it, a 429 counts as a call, and
four rows of the stage-14 file were rate-limited rather than fast.

One consequence in the renderer, because it would otherwise have shipped a sentence about
nothing: with Phase D off the ablated clock *is* the live clock, so both the CLI table and the
board suppress the "the difference is the model's round trips" comparison and say which
configuration the run was instead. `web/check-strip.mjs` pins that with a second fixture.

---

## The board

Two changes, both claims rather than controls.

- The exclusion is a claim line beside the false-match claim: how many lines it withheld, and
  **how much recall that cost**. A rule that removes work from the ladder does not get to be
  invisible just because its effect on the headline was positive.
- The ablation sentence is conditional on there being an ablation. Comparing a run with itself
  and then explaining the difference is worse than printing nothing.

One thing deliberately left alone: a `DUPLICATE_CREDIT` ledger row now reads *"δ
reversed_by_pair · 0 hypotheses tried"*, because there are no trace rows for a line no tier
was offered. That is not a display bug, it is the point — nothing was tried, and the evidence
tokens beneath say why.

---

## What did not change

- `matcher/gates.py`, `matcher/verify.py`, `matcher/uniqueness.py`: untouched. G1–G4 and
  `check()` do not know this rule exists, and G5 never saw the lines.
- The scoring rule: still per-line composition set equality (I5). Pair-scored `SPLIT_PAYOUT`
  stays declined, and `SCORING_RULE` still says why. The new `MATCHER_CHANGE` constant beside
  it records what *did* move between the stage-14 numbers and these, so the two files cannot
  be compared without seeing it.
- Seed 42's board: 100 closed, 95.24% / 100.0%, 0 FP — **byte-identical**. It was clean before
  by a `bank_line_id` tie-break and is clean now by a rule. The headline did not move; it
  became earned, which was the actual complaint.

---

## The measurement

Ten seeds, node budget only, no wall clock. `regression.json`, regenerated against this
matcher — stage 14's file was measured against one with a known false match.

| seed | lines | closed | all-lines | headline | precision | ambiguity | FP | withheld | of those, resolvable | live s |
|---|---|---|---|---|---|---|---|---|---|---|
| 42 | 134 | 100 | 95.2% | 100.0% | **100.0%** | 11.9% | 0 | 6 | 0 | 20.3 |
| 7 | 134 | 103 | 91.2% | 96.0% | **100.0%** | 6.0% | 0 | 6 | 0 | 19.8 |
| 99 | 134 | 101 | 93.5% | 99.0% | **100.0%** | 9.7% | 0 | 6 | 0 | 20.4 |
| 2026 | 134 | 105 | 92.1% | 97.1% | **100.0%** | 5.2% | 0 | 6 | 0 | 19.1 |
| 1 | 134 | 103 | 94.5% | 100.0% | **100.0%** | 9.0% | 0 | 6 | 0 | 24.4 |
| 5 | 134 | 103 | 92.0% | 96.0% | **100.0%** | 6.7% | 0 | 6 | 0 | 22.4 |
| 13 | 134 | 104 | 93.7% | 99.0% | **100.0%** | 7.5% | 0 | 6 | 0 | 17.6 |
| 23 | 134 | 99 | 90.8% | 94.9% | **100.0%** | 9.0% | 0 | 6 | 0 | 19.9 |
| 101 | 134 | 108 | 91.5% | 96.3% | **100.0%** | 2.2% | 0 | 6 | 0 | 15.9 |
| 777 | 134 | 103 | 93.6% | 94.9% | **100.0%** | 8.2% | 0 | 6 | 0 | 12.1 |

| | mean ± σ | range |
|---|---|---|
| all-lines recall | **92.8% ± 1.4%** | 90.8% – 95.2% |
| headline recall | **97.3% ± 1.9%** | 94.9% – 100.0% |
| precision | **100.0% ± 0.0%** | 100.0% – 100.0% |
| ambiguity rate | 7.5% ± 2.6% | 2.2% – 11.9% |

**False matches: 0 across ten seeds.** **Lines withheld: 60, of which 0 were resolvable.**

### Before and after, per seed

| seed | recall before | after | Δ | precision before | after | FP | `DUPLICATE_CREDIT` rows |
|---|---|---|---|---|---|---|---|
| 42 | 95.2% | 95.2% | — | 100.0% | **100.0%** | 0 → 0 | 6 → 6 |
| 7 | 90.3% | **91.2%** | +0.88 pt | 99.0% | **100.0%** | **1 → 0** | **4 → 6** |
| 99 | 93.5% | 93.5% | — | 100.0% | **100.0%** | 0 → 0 | 6 → 6 |
| 2026 | 92.1% | 92.1% | — | 100.0% | **100.0%** | 0 → 0 | 6 → 6 |
| 1 | 94.5% | 94.5% | — | 100.0% | **100.0%** | 0 → 0 | 6 → 6 |
| 5 | 92.0% | 92.0% | — | 100.0% | **100.0%** | 0 → 0 | 6 → 6 |
| 13 | 92.8% | **93.7%** | +0.90 pt | 99.0% | **100.0%** | **1 → 0** | **4 → 6** |
| 23 | 90.8% | 90.8% | — | 100.0% | **100.0%** | 0 → 0 | 6 → 6 |
| 101 | 90.7% | **91.5%** | +0.85 pt | 99.1% | **100.0%** | **1 → 0** | **4 → 6** |
| 777 | 93.6% | 93.6% | — | 100.0% | **100.0%** | 0 → 0 | 6 → 6 |

**No seed lost recall. Three gained it, and they are the three that carried the false match.**

Named, because "+1 TP" is not checkable and a line id is:

| seed | the duplicate that was matched | tier | the payout that scored FN | tier now |
|---|---|---|---|---|
| 7 | `bl_9004` **FP → TN** | A1 → — | `bl_0106` **FN → TP** | — → **A1** |
| 13 | `bl_9008` **FP → TN** | C1 → — | `bl_0119` **FN → TP** | — → **C1** |
| 101 | `bl_9004` **FP → TN** | C1 → — | `bl_0019` **FN → TP** | — → **C1** |

**Same tier, both times, on all three seeds.** That is the mechanism rather than a
coincidence: the duplicate had taken the real payout's place in the same tier's sweep, using
the same transactions, because it is the same amount in the same window with the same
narration. `closed` is unchanged on all ten seeds and so is the entire `by_tier` distribution
— one closure, one tier, the other line. The residue gap is byte-identical on all ten for the
same reason: swapping which of two equal-magnitude credits is closed leaves both sides of
§9.7's subtraction exactly where they were.

**One correction to stage 14's table.** It recorded seed 13's false match as an FP with no
matching FN, on the reasoning that `bl_0118` — the line it took the settlement from — is
itself an unresolvable `SPLIT_PAYOUT` half and so could not have scored TP. That was right
about `bl_0118` and wrong about the consequence: the transactions `bl_9008` had consumed went
to **`bl_0119`**, an `FX_MARKUP` line that had been scoring FN, and it closes at C1. Greedy
assignment does not return what it took to the line it took it from (§9.9), and the seed-13
row is the case.

### The live clock, on the configuration that ships

**19.2 s ± 3.2 s, range 12.1 – 24.4 s, inside §15's 60 s ceiling on all ten seeds.** Phase D
off, the run deadline armed, generation at the demo uniqueness budget — what a judge triggers
from the browser. Match time is 5.1 – 13.4 s of that, against a 22,000 ms run deadline, so
nothing ran out of run clock — and nine of the ten still report `deadline_hit`. That is the
*per-line* slice, `min(2000, remaining / unmatched)`, stopping at least one search mid-tree:
§9.10's `cut` population, not its `exceeded` one. Same FN, different sentence to a human —
"give it more time" rather than "there is nothing here" — and the banner says which.

This is the only clock in the file and it is a property of this box. The accuracy columns
above have no clock in them at all.
