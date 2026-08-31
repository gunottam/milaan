# Stage 5 — the proposal/verification split, and the four gates

Written for someone who knows `docs/spec.md` and has not read the code.

Spec sections read: **§7** (the two layers, the `Proposer` protocol, the gate chain) and **§8**
(tolerance, the sole non-monotonic gate).

`pytest -q`: **96 passed, 0 skipped.** The skip is gone — `test_claim_carries_no_source` has
been skipping since stage 2 because `matcher/proposers/base.py` did not exist, and it now
passes against a real file. All five invariant greps are live for the first time.

```
tests/test_gates.py: 22 passed
  G1 7   G2 3   G3 2   G4 3   shapes 3   G5 4
  gates.py 110   verify.py 70   uniqueness.py 48   base.py 49   core/proof.py 62
  proposers 0   lines matched 0
```

Nothing matches anything yet, and that is the stage rather than a shortfall. `Proposer` has
zero implementations, `check()` has never run against generated data, and every test universe
is three or four hand-built transactions. What exists is the shape stages 6–13 are written
against, and four gates that decide.

---

## The composed finding

**An invariant enforced by a grep is only as strong as the thing it forbids is hard to write.**
Both halves of that turned up in one stage, on the two invariants this file exists to hold.

- **I2 is unstatable, not merely ungreppable.** §7.3 describes G1–G4 as returning verdicts.
  They do not, here: a gate returns a rejection reason as `str`, or `None` for pass, and
  `check()` stamps the gate name and assembles the only `Verdict` in the codebase. This began
  as a way to dodge an import cycle and turned out to be the stronger design — `Verdict` is
  not imported in `gates.py` at all, so a passing verdict cannot be constructed there. The
  grep test has nothing left to catch.
- **I9 is one dataclass field away at all times.** `Claim` carrying no provenance field is not
  hard to write, it is hard to *not* write: the field is useful, it is one line, and every
  reason to add it is a good one right up until a gate reads it. The grep is the whole defence
  and a grep only fires after the line is written.

Measured rather than assumed — adding `source: str = "x"` to `Claim` and running the suite:

```
tests/test_invariants.py::test_claim_carries_no_source          FAILED
  assert not ['matcher/proposers/base.py:41: source: str = "x"']
tests/test_gates.py::test_claim_is_frozen_and_carries_no_provenance  FAILED
  assert not any(f.name == "source" for f in dataclasses.fields(Claim))
```

So I9 now has two independent guards — a substring grep over the file and an assertion over
`dataclasses.fields` — precisely because it is the invariant a mechanism cannot make
unstatable. I2, which a mechanism *can*, kept one.

The practical consequence is a rule for the rest of the build: **when a grep test is the only
enforcement, ask whether the layout can make the violation unwriteable instead, and if it
cannot, add a second guard that fails for a different reason.**

### Where the chain is deliberately less restrictive than it looks

§1's monotonicity table says every gate except G4 can only cost recall. That is true of the
rules; it is not true of G1's *inputs*.

**Entities belonging to the claim's `anchor_settlement_id` skip the window test entirely.**
§9.3: once the settlement id is known, membership is a fact rather than an inference. Without
the exemption, G1 would reject an `ONHOLD_RELEASE` settled three cycles late — which is the
entire justification for C1 existing, so the gate would be quietly deleting the tier stage 8
builds. It is the one place in the chain where a claim carrying *more* information is held to
a *weaker* test, and it is safe only because G2 still has to balance.

G1 also rejects two things §7.3 does not mention. An empty composition, and a composition
citing the same entity twice — the second is the one that matters, because a repeated id
doubles its own contribution and a claim could otherwise balance by counting one payment
twice.

### A one-paise delta cannot be rejected, and the test says so

`docs/build-stages.md` asks for a test where "G2 rejects a delta of 1 paise". It cannot exist.
§8.2's double cap admits any delta within ₹1 **and** within one paise per transaction, and
`1 ≤ 100` and `1 ≤ len(composition)` hold for every non-empty composition. One paise is
G4-admissible by construction.

What is testable is that G2 refuses to call it exact:

```python
assert g2_delta(c, line, TRIO) == -1
verdict = check(c, line, TRIO)
assert verdict.ok and verdict.confidence == "tolerance"
```

Which is the honest reading of the requirement — strict arithmetic rejected it, G4 admitted
it, and §8.3 keeps it off the exact count and on its own scoreboard line. Asserting a
rejection that the spec makes impossible would have been a test that passes by being wrong.

---

## Files

### `matcher/proposers/base.py` — §7.2

`Pool`, the `Proposer` protocol, and the frozen `Claim`. Forty-nine lines, of which the
important ones are absent: no provenance field of any kind (I9), and the word naming one does
not appear in the file even in a comment, because the invariant grep is a plain substring
match over the whole text. The docstring says "provenance" throughout for that reason.

`window_days` defaults to 0 and `anchor_settlement_id` to `None`, so the minimal claim — a
settlement's members cited by id — is `Claim(line_id, ids, anchor)`.

*Questionable:* the protocol is `propose(line, pool)` exactly as §7.2 pins it, and that
signature is already visibly too narrow. B1 needs a total→settlement index, the regex tier
needs UTRs, C1 needs settlement membership. All of that has to be state on the proposer
instance, built at construction. The alternative — widening the protocol to pass a context
object — would let a proposer be handed things the layer split says it should have asked for
itself, so the narrow signature stays and stage 6 will show whether it holds.

### `matcher/gates.py` — §7.3, §8.2

Four functions, no classes, no shared state.

**G3's decision is `core.coherence.is_plausible_payout` — the same function object
`generator/uniqueness.py::classify` applies when it builds truth.** A test asserts identity,
not equivalence:

```python
assert gates.is_plausible_payout is coherence.is_plausible_payout
```

Worth an assertion because the failure mode is invisible. If the oracle counted a second
solution the matcher's G3 would reject, truth would mark the line `AMBIGUOUS_SUBSET`, the
matcher would produce the one correct answer, and scoring would record a **false positive** —
the single number the whole design exists to hold at zero. The reason string G3 returns counts
settlements only to explain itself; nothing about the decision is computed here.

`TOLERANCE_PAISE = 100` and `MAX_WINDOW_OVERRIDE_DAYS = 5` live in this file as module
constants rather than in a config module. They are gate policy, nothing else reads them, and
§15's block can be hoisted the first time a second consumer appears.

*Questionable:* **G2 does not sum `extra_terms`.** §7.2 puts the field on `Claim` and §9.6 lets
the detective populate it, so a reader may reasonably expect the arithmetic to use it. I7 says
every deduction sits on the transaction that incurred it and there are no settlement-level
terms — summing the field would let a claim invent money to close its own gap, which is the
exact false-match class G4 is quarantined for. The field carries the model's *account* of a
difference, for the exception ledger to read. A test pins it at zero effect.

### `matcher/verify.py` — §7.2, §7.3

`Verdict` and `check()`. The gate order is G1 → G2 → G3 → G4, and G4 runs only when G2 came up
non-zero.

Every `Verdict` field is explicit at every construction. **`delta_paise` has no default**,
because I6 is that no difference is ever silently absorbed and a defaulted zero is exactly how
one would be; a test asserts rejections carry their delta too, since a refusal that forgets
the number it refused over is useless to the exception ledger in stage 10. `confidence` is
`"exact"` when the delta is zero and `"tolerance"` when G4 admitted it, never absent from a
passing verdict.

### `core/proof.py` — §7.2, §13

`Proof.rows` is `(label, count, amount_paise)` and sums to `total_paise`, so §13's proof strip
is a loop over a tuple and the double rule is the renderer's only contribution. Aggregation
only, no `fmt_inr` — formatting is not the verification layer's business.

*Questionable:* **this is a fifth file the stage did not ask for.** The defence is that §7.2
pins `Verdict.proof`, so the field had to be typed as something, and I8 — "no tier returns a
match without a balanced proof" — is only literally true if the proof is built at approval
time. It is not new arithmetic; it is the sum `check()` already performed, kept instead of
discarded. The cost of getting it wrong later is a frozen public type changing at stage 11,
which makes every measurement taken before it incomparable.

### `matcher/uniqueness.py` — §7.3

`resolve(passing) -> (claim | None, verdict | None)` over the set of passing verdicts for one
line. Three outcomes and the caller needs all three: nothing passed `(None, None)`, a tie
`(None, G5 refusal)`, one survivor `(claim, verdict)`. The refusal it constructs is
`Verdict(ok=False, gate="G5", …)` — G5 withdraws approval and can express nothing else.

Two rulings inside it:

- **Distinctness is set equality on the composition** (I5). The same set proposed by two
  proposers — a regex hit and a lookup hit on one settlement — is one answer, not a tie.
  Without this G5 would refuse every line two tiers agree on, which is most of them.
- **Exact beats tolerance.** §9.3 takes the minimum `|delta|` and refuses only on ties *at
  that minimum*. A delta-0 answer and a delta-2 answer do not tie: one is arithmetic, the
  other is a relaxation of it. Only G4-admitted answers can tie with each other.

### `tests/test_gates.py` — §7.3, §8.2

Twenty-two tests, every one of which asserts a rejection except the four that pin what G4 and
G5 are allowed to let through.

| case | assertion |
|---|---|
| G1 stale entity | rejected by name, and `check().gate == "G1"` |
| G1 unknown entity | rejected — §7.4's `MALFORMED_HYPOTHESIS` path |
| G1 out-of-window entity | rejected; **accepted** when it belongs to the anchor settlement |
| G1 repeated entity · empty composition · window over the §15 cap | rejected |
| G2 delta of 1 paise | `-1`, verdict `tolerance`, never `exact` |
| G2 on a valid anchor ₹198 short | not a match (I8, `bl_06` of `docs/workflow.md`) |
| G2 with `extra_terms` | delta unchanged (I7) |
| G3 three partial slices | balances at delta 0 and is still rejected |
| G3 | is the oracle's function object, by identity |
| G4 2 paise / 3 transactions | accepted, `confidence="tolerance"` |
| G4 87 paise / 3 transactions | rejected — and the test asserts the ₹1 cap *would* have admitted it, so the second cap is visibly the one working |
| `Claim` | frozen, and no provenance field in `dataclasses.fields` |
| passing verdict | carries a `Proof` whose rows sum to the target |
| rejected verdict | still carries its delta (I6) |
| G5 | refuses two tied compositions · collapses one set from two proposers · prefers exact over tolerance · says nothing when nothing passed |

*Questionable:* the universes are hand-built, three or four transactions each, with round
amounts like 100 and 60 paise. That makes each case readable at a glance and it means **none
of these tests has seen real data**. The gate chain against the generated dataset is stage 6's
first act, and any of these could be right in isolation and wrong in composition.

---

### The chain, as built

| gate | signature | returns |
|---|---|---|
| G1 exclusivity | `(claim, line, txns, claimed)` | `str \| None` — stale, unknown, duplicated, out-of-window, over the override cap |
| G2 arithmetic | `(claim, line, txns)` | `Paise` — never rejects; §7.3 sends a non-zero delta to G4 |
| G3 coherence | `(claim, txns)` | `str \| None` — not the shape of a payout (§9.4) |
| G4 tolerance | `(claim, delta)` | `str \| None` — outside §8.2's double cap |
| G5 uniqueness | `(passing)` → `matcher/uniqueness.py` | a claim, or a refusal. Never an approval |

G2's odd signature is the chain's honesty showing: it is not a gate in the same sense as the
others, because it cannot reject, so it returns the number and lets `check()` decide what the
number means.

## Deviated from the spec

**Gates return `str | None`, not `Verdict`.** §7.3's table implies each gate produces a
verdict. Having them return a reason makes I2 structural rather than aspirational and removes
the `gates.py` ↔ `verify.py` import cycle. The cost is that a gate cannot attach a `Proof` to
its own rejection, which nothing wants: a rejection has no balanced proof to attach.

**`check()` takes the whole `txns` mapping, not a pool.** G3 needs the universe rather than the
composition — completeness of a settlement group cannot be judged from the group's own members
— so this is forced. It does mean the verification layer holds a reference to every
transaction in the run. If stage 9 makes that awkward the fix is a settlement-size index
passed alongside, not a smaller `txns`.

**`Verdict.confidence` is never `None` on a passing verdict.** §7.2 types it optional. In
practice a match is `"exact"` or `"tolerance"` and there is no third state, so the optionality
only describes rejections.

## Deferred

**`MatchResult`, and therefore `source`.** I9 puts provenance on the match result, output
only. Nothing produces a match result until a proposer exists, so the type arrives with stage
6 rather than being scaffolded empty here. This is the one place the spec's word `source` will
legitimately appear.

**`MALFORMED_HYPOTHESIS` counting.** G1 rejects a claim citing a non-existent or already-spent
entity and returns the reason; §7.4 wants a running count as a prompt-quality signal. Counting
belongs to whatever loops over lines, which is `matcher/run.py` in stage 9.

**G5 does not sub-type its refusals.** §10.1 splits ambiguity into `AMBIGUOUS_EQUIVALENT` and
`AMBIGUOUS_CONSEQUENTIAL` by whether the alternatives post identical books. The oracle already
computes that distinction (`generator/uniqueness.py::_shape`); the matcher's copy belongs with
the exception ledger in stage 10. `resolve()` returns the refusal and the tied count, and the
classification hangs off it later.

**`Proof` has no per-method breakdown.** §13's strip shows "MDR (mixed methods)" as one line,
which is what `build_proof` emits. If stage 11 wants the split by `upi` / `card` / `intl_card`
it is a `Counter` over the same composition, not a change to the type.

**Nothing has been measured.** No proposer calls any of this, so there is no recall number, no
precision number and no timing. Stage 6 produces the first, stage 7 the first honest one. Every
claim in this file is about shape, not performance.
