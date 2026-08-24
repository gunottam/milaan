# Milaan — project memory

Settlement reconciliation agent. Given a bank statement, a Razorpay gateway ledger and an
order list, it determines what composes every bank line, proves it to the paisa, and refuses
honestly when it cannot.

Full spec: `docs/spec.md` (frozen v1.3). Narrative + worked example: `docs/workflow.md`.
Build stages: `docs/build-stages.md`. **Read only the spec sections a stage names.**

---

## Verify before claiming done

```bash
pytest -q                        # must be green before any stage is complete
pytest tests/test_invariants.py  # the invariant enforcement, run it constantly
pytest tests/test_subsetsum.py   # includes the brute-force property test
```

Never report a stage complete without running these. If a command could not be run, say so.

---

## Money

- **All money is `int` paise.** `Paise = int`. No floats anywhere outside `core/fees.py`.
- `Decimal` is permitted **only** in `core/fees.py` for rate multiplication.
- One rounding function: `round_paise()`, `ROUND_HALF_UP`. Do not use `round()`.
- Rounding is **per transaction, never on an aggregate**.
- GST is computed on the **already-rounded** fee. This order is load-bearing — reversing it
  makes `ROUNDING_DRIFT` unfireable.
- Display uses Indian digit grouping: `₹4,61,938.80`, never `₹461,938.80`.

## Time

All IST (+05:30). Window comparisons are on the **IST calendar date**. Window key is
`value_date`, falling back to `txn_date`.

---

## The invariants

| # | Rule |
|---|---|
| I1 | Integer paise. No floats outside `core/fees.py` |
| I2 | Only `verify.check()` may return `Verdict(ok=True)` |
| I3 | `detective/` has no reference to `truth` |
| I4 | Proposers emit `Claim`, never a verdict |
| I5 | Composition comparison is set equality. No partial credit |
| I6 | Every verdict carries `delta_paise`. Nothing is silently absorbed |
| I7 | Every deduction sits on the transaction that incurred it. No settlement-level terms |
| I8 | No tier returns a match without a balanced proof. Tiers **select**; gates **approve** |
| I9 | `Claim` is frozen and has **no `source` field**. `source` is on `MatchResult` only |
| I10 | `notes` and `description` never enter a prompt |

---

## Architecture

Two layers. Do not blur them.

**Proposers** (`matcher/proposers/`) create candidates: regex, lookup, search, detective.
All four implement the same `Proposer` protocol and emit an identical frozen `Claim`.

**Gates** (`matcher/gates.py`) approve them, in order:
`G1` exclusivity → `G2` arithmetic → `G3` coherence → `G4` tolerance.

`check()` cannot tell which proposer produced a claim. That is the point — keep it that way.

`G5` uniqueness lives in `matcher/uniqueness.py`, **not** in `check()`. It operates on the
*set* of passing verdicts for a line and never approves anything; it withdraws approval when
two verdicts tie.

**G4 is the only gate that can admit a wrong answer.** Every other gate can only cost recall.
Treat changes to it with suspicion.

---

## Do not

- **Do not return the first solution found.** Search continues until a second is found or the
  space is exhausted. Two solutions means refuse. This is not an optimisation target.
- **Do not treat the node budget as a performance knob.** It determines whether the
  uniqueness guarantee holds. Lowering it converts proven matches into `UNIQUENESS_UNPROVEN`.
- **Do not add `source` to `Claim`** (I9), however useful it looks.
- **Do not skip arithmetic on an identifier match.** A clean UTR hit that does not balance is
  not a match (I8). `bl_06` in `docs/workflow.md` is the case.
- **Do not absorb a delta into a "rounding adjustment"** outside G4's double cap.
- **Do not build SSE.** Polling at 500 ms is the design.
- **Do not add SQLite.** `data/runs/` plus a directory glob is the store.
- **Do not scaffold future stages.** Build only the stage you were given.
- **Do not write excessive comments.** Docstrings on public functions; skip narration.

## Style

- Python 3.11 (`from __future__ import annotations` at the top of every module),
  type hints on all public functions, `@dataclass(frozen=True)` for value types.
- Tests use plain `pytest`, no fixtures framework beyond `tmp_path`.
- Frontend: Vite + React, plain CSS with the tokens in `docs/spec.md` §13. No UI library.
