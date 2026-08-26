# Stage 2 — invariant enforcement

Written retroactively, for someone who understands `docs/spec.md` and has not read the code.

Spec sections read: **§0** (the ten invariants) and **§14** (repo layout, which contains the
five test bodies verbatim).

`pytest tests/test_invariants.py`: **4 passed, 1 skipped**. The skip is deliberate and explained
below. Negative control, from `docs/build-stages.md`:

```
$ echo "x = float(1)" >> core/money.py
$ pytest tests/test_invariants.py
E  AssertionError: assert not ['core/money.py:58: x = float(1)']
   1 failed, 3 passed, 1 skipped
$ git checkout core/money.py
   4 passed, 1 skipped
```

---

## Why this stage is second

§16 puts it here with a one-line justification — "before there is anything to violate" — and the
ordering is the whole point. An invariant added after the code that breaks it is a negotiation:
you find eleven violations, three look expensive to fix, and the rule quietly becomes a
guideline. An invariant added when the tree is empty is free, and every later stage inherits it
as a constraint rather than a cleanup task.

§0's own framing is the thing to internalise: **each invariant is "enforced by a mechanism, not
a promise."** Five of the ten reduce to a text search over the tree, so those five are tests.
The other five are enforced by types and structure — `Claim` being frozen (I9), `Claim` having no
verdict field (I4), set equality in scoring (I5), `delta_paise` on every verdict (I6),
`tds_paise` being a column (I7) — and cannot be greped for.

---

## Files

### `tests/test_invariants.py` — §0, §14

A `grep(pattern, paths)` helper plus the five tests §14 specifies: no `float(` in `core/`,
`matcher/`, `generator/` (I1); no `Verdict(ok=True` outside `matcher/verify.py` (I2); no `truth`
under `detective/` (I3); no `source` in `matcher/proposers/base.py` (I9); no `.notes` or
`.description` under `detective/` (I10). The helper walks `*.py` files, skips dot-directories,
and calls `pytest.skip` when a named path does not exist yet, so the file stays runnable through
every stage rather than erroring on modules that have not been written.

*The decision a reviewer would ask about:* **these are line-based text searches, so they cannot
tell a violation from a mention.** The word `truth` in a docstring under `detective/` fails I3
even though nothing was imported; conversely `\bfloat\(` catches `float(x)` but not a bare `1.5`
literal, not `/` true division, and not `math.fsum`. Both directions are known and accepted. An
AST-based version would be more precise and nobody would trust it under time pressure, whereas a
grep failure is a filename, a line number and the offending text — a five-second diagnosis. The
false positives are also cheap to resolve: rename the variable.

Two consequences worth carrying forward:

- **I2 greps `.`, which includes `tests/`.** So no test may construct a passing verdict by hand;
  stage 5's `test_gates.py` has to route through `check()`. That is the invariant working as
  intended, not an obstacle to work around. This test file is immune to its own pattern only
  because the pattern is written escaped in the source (`Verdict\(ok=True` does not match
  `Verdict(ok=True`) — an accident, but a stable one.
- **A missing path skips the whole test, not just that path.** `test_claim_carries_no_source` is
  the one currently skipping, because `matcher/proposers/base.py` arrives in stage 5. An empty
  *directory* that exists, by contrast, passes trivially — there is nothing in it to violate. So
  "4 passed" today is a weaker claim than it will be in stage 5, and the skip line in pytest's
  output is the honest signal of that.

---

## Deviated from the spec

**§14's snippets call a `grep()` that §14 does not define.** I chose a module-scoped helper
returning `path:line: text` strings, `pytest.skip` on a missing path, and an assertion message
carrying the hits (`assert all(...), hits`) so a failure names the file rather than printing
`assert False`. The five test bodies themselves are §14's, unchanged in meaning.

**`test_only_verify_approves` was left greping `.` literally**, including `tests/`, `api/` and
`web/`. Excluding the test tree would have made the invariant weaker exactly where a shortcut is
most tempting.

## Deferred

**The five invariants that are not text searches.** I4, I5, I6, I7 and I9's frozen-dataclass half
are enforced by the types in `matcher/proposers/base.py` and `core/proof.py`, neither of which
exists before stage 5. §0's table already assigns each one its mechanism; this stage only builds
the mechanisms that are tests.

**I9's grep is currently vacuous.** `test_claim_carries_no_source` skips, so the strongest
invariant in the design — that the verification layer cannot tell a model hypothesis from a
regex hit — is unenforced until stage 5 creates the file it points at. Worth remembering when
reading a green test run today.

**No check that the grep tests themselves still bite.** The negative control above was run by
hand, once. There is no meta-test asserting that `test_no_floats_in_core` fails on a planted
violation, because a test that plants a violation in a source file, runs pytest recursively and
reverts it is more machinery than the thing it guards. Re-run the four lines above by hand if the
file is ever refactored.
