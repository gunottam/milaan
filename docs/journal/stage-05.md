# Stage 5 — the proposal/verification split, G1–G4, G5

Written for someone who knows `docs/spec.md` and has not read the code.

Spec sections read: **§7** (the two layers, the protocol, the gate chain) and **§8**
(tolerance, the sole non-monotonic gate).

`pytest -q`: **96 passed, 0 skipped.** The skip is gone —
`test_claim_carries_no_source` has been skipping since stage 2 because
`matcher/proposers/base.py` did not exist, and it now passes on a real file. Every one of the
five invariant greps is live for the first time.

Nothing matches anything yet. There are no proposers, so `Proposer` has zero implementations
and `check()` is exercised only by `tests/test_gates.py`. That is the stage: the types the
next eight stages are written against, and the four gates that decide.

---

## The finding: a gate that cannot express approval

§7.3 describes G1–G4 as returning verdicts. They do not, here. **A gate returns a rejection
reason, or `None` for pass.** `check()` stamps the gate name and assembles the only `Verdict`
in the codebase.

This started as a way to avoid an import cycle (`gates.py` needing `Verdict`, `verify.py`
needing the gates) and turned out to be the stronger design. I2 says only `verify.check()` may
return a passing verdict, and it is enforced by a grep test — but a grep test is a tripwire,
not a mechanism. With this shape a passing verdict is *unconstructible* from `gates.py`,
because `Verdict` is not imported there at all. The invariant stops depending on nobody
writing the wrong line.

It also makes G2's odd position in the chain legible. **G2 does not reject anything** — §7.3
sends a non-zero delta to G4 — so it is not a gate in the same sense as the others and its
signature says so: it returns a `Paise` delta, and `check()` decides what that means.

```
G1  (claim, line, txns, claimed) -> str | None      reject: stale/unknown/out-of-window
G2  (claim, line, txns)          -> Paise           never rejects; falls to G4
G3  (claim, txns)                -> str | None      reject: not the shape of a payout
G4  (claim, delta)               -> str | None      reject: outside the double cap
```

---

## Files

### `matcher/proposers/base.py` — §7.2

`Pool`, the `Proposer` protocol, and the frozen `Claim`. Forty lines of which the important
ones are the ones not there: `Claim` has no provenance field of any kind (I9), and the word
that names one does not appear in the file even in a comment, because the invariant grep is a
plain substring match over the whole file. The docstring says "provenance" throughout for that
reason.

`window_days` defaults to 0 and `anchor_settlement_id` to `None`, so the minimal claim — a
single settlement's members cited by id — is `Claim(line_id, ids, anchor)`.

### `matcher/gates.py` — §7.3, §8.2

`TOLERANCE_PAISE = 100` and `MAX_WINDOW_OVERRIDE_DAYS = 5` live here as module constants
rather than in a config module. They are gate policy and nothing else reads them; §15's block
can be hoisted into one place the first time a second consumer appears.

**G3 imports `core.coherence.is_plausible_payout`, the same function
`generator/uniqueness.py::classify` applies when it builds truth.** A test asserts they are
the identical object, not merely equivalent:

```python
assert gates.is_plausible_payout is coherence.is_plausible_payout
```

That is worth an assertion because the failure mode is invisible. If the oracle counted a
second solution that the matcher's G3 would reject, truth would mark the line
`AMBIGUOUS_SUBSET`, the matcher would produce the one correct answer, and scoring would call
it a **false positive** — the single number the whole design exists to keep at zero. The
reason string G3 returns counts settlements only to explain itself; the decision is entirely
the shared function's.

**G1 is deliberately less restrictive in exactly one place.** Entities belonging to the
claim's `anchor_settlement_id` skip the window test. §9.3: once the settlement id is known
membership is a fact rather than an inference, which is the only reason an `ONHOLD_RELEASE`
settled three cycles late is recoverable at C1 at all. Without the exemption G1 would reject
every claim C1's whole existence is justified by.

G1 also rejects two things §7.3 does not mention: an empty composition, and a composition
citing the same entity twice. The second is the one that matters — a repeated id doubles its
own contribution, so without the check a claim can balance by counting one payment twice.

### `matcher/verify.py` — §7.2, §7.3

`Verdict` and `check()`. Every `Verdict` field is explicit at every construction; in
particular **`delta_paise` has no default**, because I6 is that no difference is ever silently
absorbed and a defaulted zero is precisely how one would be. Rejections carry their delta too
— a test asserts that, since a refusal that forgets the number it refused over is useless to
the exception ledger in stage 10.

`confidence` is `"exact"` when G2 came up zero and `"tolerance"` when G4 admitted it, never
absent from a passing verdict.

### `core/proof.py` — §7.2, §13

Built now rather than deferred to stage 11. §7.2 pins `Verdict`'s shape and a frozen public
type that changes later makes every measurement taken before it incomparable — and I8 ("no
tier returns a match without a balanced proof") is only literally true if the proof is
constructed at approval time. It is not new arithmetic: it is the sum `check()` already
performed, kept instead of thrown away.

`Proof.rows` is `(label, count, amount_paise)` and sums to `total_paise`, so §13's proof strip
is a `for` loop over a tuple and the double rule is the renderer's only contribution.
Aggregation only, no `fmt_inr` — formatting is not the verification layer's business.

### `matcher/uniqueness.py` — §7.3

`resolve(passing) -> (claim | None, verdict | None)`, over the set of passing verdicts for one
line. Three outcomes, and the caller needs all three distinguished: nothing passed
`(None, None)`, a tie `(None, G5 refusal)`, one survivor `(claim, verdict)`.

Two rulings inside it:

- **Distinctness is set equality on the composition** (I5). The same set proposed by two
  proposers — a regex hit and a lookup hit on the same settlement — is one answer, not a tie.
  Without this, G5 would refuse every line two tiers agree on, which is most of them.
- **Exact beats tolerance.** §9.3 takes the minimum `|delta|` and refuses only on ties *at
  that minimum*. A delta-0 answer and a delta-2 answer do not tie: one is arithmetic and the
  other is a relaxation of it. Only G4-admitted answers can tie with each other, and they do
  so at equal `|delta|`, which is exactly §9.3's rule.

The refusal it emits is `Verdict(ok=False, gate="G5", ...)`. G5 can construct that and nothing
else — it withdraws approval, it never grants it.

### `tests/test_gates.py`

Twenty-two tests. The four the stage names, plus the shapes:

| case | assertion |
|---|---|
| G1 stale entity | rejected, and `check().gate == "G1"` |
| G1 unknown entity | rejected — §7.4's `MALFORMED_HYPOTHESIS` path |
| G1 out-of-window entity | rejected; **accepted** when it belongs to the anchor settlement |
| G1 repeated entity, empty composition, window over the §15 cap | rejected |
| G2 delta of 1 paise | `-1`, and the verdict is `tolerance`, never `exact` |
| G2 on a valid anchor that comes up ₹198 short | not a match (I8, `bl_06`) |
| G2 with `extra_terms` | delta unchanged (I7) |
| G3 three partial slices | balances perfectly at delta 0 and is still rejected |
| G4 2 paise / 3 transactions | accepted, `confidence="tolerance"` |
| G4 87 paise / 3 transactions | rejected — and the test asserts the ₹1 cap *would* have admitted it, so the second cap is visibly the one working |
| `Claim` | frozen, and `dataclasses.fields` contains no provenance field |
| a passing verdict | carries a `Proof` whose rows sum to the target |
| a rejected verdict | still carries its delta (I6) |
| G5 | refuses two tied compositions; collapses the same set from two proposers; prefers exact over tolerance; says nothing when nothing passed |

## Deviated from the spec

**"G2 rejects a delta of 1 paise" cannot be tested as a rejection, and the test says so.** One
paise clears §8.2's double cap for *any* non-empty composition — `1 ≤ 100` and
`1 ≤ len(composition)` — so a one-paise delta is unrejectable by the chain as specified. What
is testable, and what the build-stage note must mean, is that G2 refuses to call it exact:
`g2_delta` returns `-1` and the verdict comes out `confidence="tolerance"`, counted on its own
scoreboard line (§8.3) and never folded into the exact count. The test asserts both facts
rather than a rejection that cannot happen.

**`extra_terms` is not summed by G2.** §7.2 puts the field on `Claim` and §9.6 lets the
detective populate it, but I7 says every deduction sits on the transaction that incurred it
and there are no settlement-level terms. Summing it would let a claim invent money to close
its own gap — the exact false-match class G4 is quarantined for. The field carries the model's
*account* of a difference, for the exception ledger to read; it is never an addend. A test
pins that.

**`core/proof.py` is a fifth file this stage did not name.** Reasoning above; it is 60 lines
and `Verdict.proof` had to be typed as something.

## Deferred

**`MatchResult`, and therefore `source`.** I9 puts provenance on the match result, output
only. Nothing produces a match result until a proposer exists, so the type arrives with stage
6 rather than being scaffolded empty here.

**`MALFORMED_HYPOTHESIS` counting.** G1 rejects a claim citing a non-existent or already-spent
entity and returns the reason; §7.4 wants a running count as a prompt-quality signal. Counting
belongs to whatever loops over lines, which is `matcher/run.py` in stage 9.

**G5 does not sub-type its refusals.** §10.1 splits ambiguity into `AMBIGUOUS_EQUIVALENT` and
`AMBIGUOUS_CONSEQUENTIAL` by whether the alternatives post identical books. The oracle already
computes that distinction (`generator/uniqueness.py::_shape`), and the matcher's copy belongs
with the exception ledger in stage 10. `resolve()` returns the refusal and the tied count; the
classification hangs off it later.

**No proposer calls any of this.** The gate chain has never run against generated data — only
against hand-built universes of three to four transactions. The first real measurement is
stage 6's Phase A + B, and the first honest recall number is stage 7's.

**`check()` takes the whole `txns` mapping.** G3 genuinely needs the universe, not the
composition — completeness of a settlement group cannot be judged from the group's members
alone — so this is not avoidable, but it does mean the verification layer holds a reference to
every transaction in the run. If stage 9's memory or ordering ever makes that awkward, the fix
is a settlement-size index passed alongside, not a smaller `txns`.
