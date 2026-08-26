# Stage 3 — generator, truth, uniqueness gate, property test

Written for someone who knows `docs/spec.md` and has not read the code.

Clean data only, no break injectors. `pytest -q`: **49 passed, 1 skipped** (the skip is
`test_claim_carries_no_source`, waiting on `matcher/proposers/base.py` in stage 5).

```
data/runs/seed42: 120 bank lines, 3000 transactions, 2823 orders
  resolvable 120   verified 118   budget_exhausted 2   ambiguous 0
  narrations unparseable by regex alone: 38/120 (31.7%)
```

---

## Three findings that changed the design

### 1. §9.3's pseudocode is wrong, in two separate ways

The property test of §6.3 exists because a solver bug makes the oracle assert a uniqueness it
never established — invisibly, in a way no other test catches. It earned its place on the first
run by failing against brute force, and then a second time.

**Bug one — the `return` on a found solution.** §9.3 reads:

```python
if remaining == 0 and chosen:
    solutions.append(tuple(t.entity_id for t in chosen)); return
```

Returning there drops every *superset* of a solution that adds a group netting to zero — a
refund cancelling a payment inside the same payout. Those supersets are precisely the second
solution the uniqueness gate is looking for, so the gate would report `verified` on genuinely
ambiguous lines. Brute force found `{e00}` and `{e00, e01, e02}` for a pool of `[9, 4, −4]`;
the DFS found only the first.

**Bug two — removing the `return` naively.** With the return deleted, `remaining == 0` stays
true all the way down the all-skip path, so the same subset is re-reported at every node below
it: `('p1',)` came back three times. Duplicates are worse than they look, because two copies of
one answer trip the `len(solutions) >= 2` test and mark a uniquely resolvable line
`AMBIGUOUS_SUBSET` — silent recall loss. My property test missed this because it compared
*sets* of solutions, which deduplicates; the test now asserts on the raw list as well.

The fix records a subset at the moment its last element is taken, so each is reported exactly
once and supersets are still explored. Both failures were recall-only, never a false match —
but the second one would have quietly suppressed real matches in every later stage.

### 2. Unanchored subset-sum over a multi-cycle pool is information-theoretically impossible

The first generated dataset had **115 of 120 lines exhausting the node budget**. The cause is
not the solver and not the budget. A payout of ~25 transactions inside a 2-day window whose
pool also catches its neighbours gives ~75 transactions: `2**75` subsets against a target
range of ~₹3 lakh. There are vastly more subsets than attainable sums, so by pigeonhole every
target has many representations. Uniqueness is not merely expensive to prove there — it is
false. The two lines I forced to completion at 250k nodes both came back with two solutions.

Consequences, in order of importance:

- **The dataset spaces settlement cycles `window_days + 1` apart** (`generator/config.py::cycle_spacing`)
  so a line's window pool holds its own settlement and nothing else. This is the load-bearing
  decision in the generator and the one a reviewer should push on — see below.
- **`C2_MAX_POOL = 35` is now a config rule** with the argument written above it. Stage 8 must
  make C2 refuse above it rather than search. Not wired into a tier yet.
- **§9.3 of the spec now records that C2 is a small-pool tier, not a general fallback**, and
  that C1's anchored residual search is the primary search path. This matches §9.5's existing
  observation that most settlements are already claimed by the time the late tiers run.

### 3. The oracle and the matcher have to share one coherence rule

The gate ran the raw solver while the matcher will run the solver *plus* G3. Any second
solution G3 would reject made the gate mark the line unresolvable — and then the matcher's
correct answer scores as a **false positive**, the one number that must read zero.

At the offline budget, 18 of 120 lines had a second arithmetic solution. **All 18 were partial
slices of the line's own settlement**, which G3 rejects outright: a payout is a whole
settlement group, never a subset of one. With `is_plausible_payout` applied, ambiguity on clean
data is **0**.

That is not a tuning result, it is structural: when the window pool equals the settlement, every
alternative subset is a partial slice, so clean data *cannot* produce `AMBIGUOUS_SUBSET`. The
truth record's ambiguity machinery is therefore exercised only by unit tests until stage 4's
breaks put foreign transactions into windows — which is what §5 means by "emerges naturally".
`TARGET_AMBIGUOUS_RATE = 0.08` is a stage-4 obligation, not a stage-3 one.

The filter runs *inside* the search, via a `keep` predicate on `solve_exact`. It has to: a
rejected candidate must not consume the two-solution cutoff, or a coherent second solution
further down the tree is never reached. §9.3's tier table already describes C2 as "filtered by
G3", so this is the spec's own arrangement.

### Budget split, and the 2 lines that remain

`UNIQUENESS_NODE_BUDGET` became `_OFFLINE = 2_000_000` (default) and `_LIVE = 20_000`
(`--live`). Cost tracks the count of *negative-net* items in the pool, not pool size — refunds
disable the undershoot prune — so an exhausted budget correlates with difficulty, and excluding
those lines from scoring inflates recall by dropping the hardest cases.

| Budget | `verified` | `budget_exhausted` | Excluded from scoring | Wall clock |
|---|---|---|---|---|
| live, 20k | 100 | 20 | 16.7% | 0.4 s |
| offline, 2M | 118 | **2** | **1.7%** | 1.3 s |

The target was under 1% and the result is 1.7%, because the last two lines are not a budget
problem. `bl_0054` (pool 34) and `bl_0074` (pool 36) sit at or above `C2_MAX_POOL`; `bl_0074`
resolves at 40M nodes and `bl_0054` still does not. Getting under 1% means capping composition
size, not raising the budget. Two lines conservatively marked "an answer, uniqueness unproven"
is the honest outcome.

---

## Files

### `core/models.py` — §3

The three CSV row types as frozen dataclasses, plus `net_contribution` (§3.1) and the signed
`target` (§3.2, finding 8.1). Money is `int` paise throughout and timestamps are IST-aware
ISO8601 *strings*, so a CSV round-trip is lossless and IST parsing happens in exactly one place.

*Questionable:* every `GatewayTxn` field except three carries a default, which makes it easy for
a test to construct a transaction that could not exist in reality. The alternative — mandatory
fields — turns every unit test into a 20-argument constructor call, and `net_contribution`
crashing loudly on an unknown `type` covers the failure that actually matters.

### `core/coherence.py` — §9.4

`is_plausible_payout(composition, txns) -> bool`, the G3 rule as a pure function with no imports
from `matcher/` or `generator/`. It takes the whole transaction universe, not just the
composition, because completeness of a settlement group cannot be judged from that group's
members alone.

*Questionable:* it rejects a composition of **two complete settlements**. §9.4's table does not
list that shape, but `SETTLEMENT_CONTAMINATION` implies spanning compositions are
accepted-and-flagged rather than refused. G3 is monotonically restrictive, so being strict here
costs recall and cannot admit a wrong answer — the safe direction, but a reviewer may want it
loosened once stage 4's contamination break exists.

### `generator/config.py` — §15

The §15 constants that generation needs, the dataset shape (price catalogue, method weights,
noise profiles), and the two findings above as named rules: `cycle_spacing()` and `C2_MAX_POOL`.

*Questionable:* `C2_MAX_POOL = 35` is a round number from an order-of-magnitude argument, not a
derived threshold — `2**35` against a ₹3 lakh paise range is where the two quantities cross for
*this* dataset. The bound is real; the constant is a judgement call.

### `generator/narration.py` — §3.4

The narration templates and the seven degradations: drop the UTR, truncate to 5–8 characters,
transpose adjacent digits, abbreviate the legal entity, collapse whitespace, uppercase, blank
the line. `render()` returns a `recoverable` flag alongside the text, which is how the ~30%
unparseable rate at `--noise high` is measured (31.7% at seed 42).

*Questionable:* `recoverable` is what the generator *injected*, not what a regex actually fails
on. The real figure can only be measured once `matcher/proposers/regex_p.py` exists in stage 6,
and it will be higher — a truncated UTR is flagged recoverable here but only the §9.5 prefix
cascade can use it. Templates also carry `{utr}` whole rather than §3.4's literal `N{utr}`,
since the leading `N` lives in the identifier.

### `generator/entities.py` — §3, clean data

Builds the settlements, transactions, bank lines and orders. One settlement per cycle, one bank
line per settlement, and the bank credit equals the sum of its members' net contributions to the
paise — asserted per settlement at build time and again in the tests.

*Questionable:* refunds attach to a parent payment from an earlier cycle and are capped at a
quarter of the payout's net, which is what keeps every settlement net-positive. The cap is
arbitrary and it deliberately prevents `NEGATIVE_SETTLEMENT` from arising on its own — stage 4
injects that case rather than letting it fall out of the refund distribution.

### `generator/allocate.py` — §4.3

The even split whose `total % n` remainder is discarded, which is the mechanism behind
`ROUNDING_DRIFT`. Moved here out of `core/fees.py` to match §14's layout.

*Questionable:* four lines, and nothing calls it yet — the stage-4 injector is its first caller.
Kept because §14 names the file and stage 1's golden test already pins the behaviour
(`test_allocation_remainder_is_dropped_by_integer_division`).

### `generator/uniqueness.py` — §6.2, §9.3

`solve_exact` (the shared DFS with the two fixes above), `window_pool` (§9.3 pool construction,
which never reads `on_hold`), `classify` (the §6.2 three-way truth record) and
`mark_duplicate_targets` (finding 8.4 — two bank lines with the same date and amount are
interchangeable, so truth marks the whole *set* unresolvable rather than assert an assignment
that scoring would then penalise).

*Questionable:* the solver the matcher will run lives in `generator/`, so stage 8's
`search_p.py` will import product code from dev tooling. The alternative is two copies of the
DFS, which is exactly the failure §6.3 warns about. It should move to `core/` or `matcher/` in
stage 8; a `ponytail:` comment at the top of the file says so.

### `generator/generate.py` — §6.1

The CLI (`--seed --bank-lines --records --noise --window-days --live --out --generated-at`),
CSV writing with `\n` line endings, and the `truth.json` shape of §6.1. Prints the resolvable /
verified / exhausted / ambiguous counts and the unparseable-narration rate so a bad dataset is
visible without opening a file.

*Questionable:* `--generated-at` exists only so byte-identical reproduction is checkable — the
CSVs are reproducible from `--seed` alone, but an unpinned wall-clock timestamp inside
`truth.json` makes a `diff -r` of two runs fail on a field that carries no data. `--breaks` is
absent until stage 4 has injectors to name.

### `tests/test_subsetsum.py` — §6.3

The non-negotiable property test: 126 random pools of ≤18 mixed-sign transactions, each compared
against `itertools.combinations`, plus the empty-subset guard (8.3), the two-solution cutoff, the
budget refusal and the determinism tie-break (8.6).

*Questionable:* nets are drawn from ±1..40, a deliberately narrow range. Wide random integers
almost never collide, so the test would pass while proving nothing about the ambiguity path —
the narrow range is what makes second solutions common enough to compare.

### `tests/test_coherence.py` — §9.4

One test per row of §9.4's table, plus the gate-level test the fix demanded: a payout whose own
prefix balances (`{p1}` where `{p1, p2, r1}` is the settlement and `r1` cancels `p2`) produces
two raw solutions, and truth must still record `verified`.

### `tests/test_generator.py`

The generator's own guarantees: byte-identical output for a repeated seed, exact record counts,
every line tying to its settlement to the paise, every transaction in exactly one settlement,
zero fees off the payment path (I7), a `uniqueness` value on every resolvable line, and the
noise rates at `high` and `low`.

*Questionable:* not in §14's test list. It is the only runnable check on the largest module in
the stage, so it stays.

### Also

`allocate()` moved from `core/fees.py`; `tests/test_fees.py` re-pointed from a local stand-in
class to the real `GatewayTxn`, all 17 golden cases unchanged and still green. A golden test
asserting against a mock is worse than none.

---

## Deviated from the spec

**`solve_exact` does not follow §9.3's pseudocode.** Two bugs, described above. The spec's
version returns on a found solution, which drops the supersets that constitute the second
solution; the naive repair re-reports the same subset at every node down the all-skip path. The
code records a subset when its last element is taken. The pseudocode is otherwise followed
exactly, including the sort tie-break of 8.6 and the pos/neg suffix arrays.

**Settlement cycles are spaced `window_days + 1` apart, not daily.** §3 implies a daily payout
cadence; that makes the window pool ~75 transactions, where uniqueness is not merely expensive
but false. The dataset is now ~2 payouts a week for a year rather than daily for four months.
This is the deviation most worth arguing with, because it makes clean data *easy* — pool equals
composition — and defers all genuine search difficulty to stage 4's breaks.

**Narration templates carry `{utr}` whole**, not §3.4's literal `N{utr}`. The leading `N` is
part of the identifier (`NHDFC26010100001`), so the spec's form would render `NN…`. §3.4's
`{blank}` template is implemented as a degradation rather than a template, and the
`CHGBK-{partial_disp_ref}-RZP ADJ` template is absent — it belongs to a dispute debit, which is
a stage-4 break.

**`UNIQUENESS_NODE_BUDGET` was split in two** rather than kept as §15's single 20,000. §15's
figure is a live-run budget; using it offline excludes 16.7% of lines from scoring, and the
exclusion correlates with difficulty.

**`is_plausible_payout` rejects two complete settlements**, a shape §9.4's table neither accepts
nor rejects. Strict costs recall only.

## Deferred

**Break injectors — all 18.** Stage 4. Nothing in `generator/breaks.py` exists;
`truth.json.break_manifest` is `{}` and `injected_breaks` is `[]` on every resolvable line.

**`truth.json.settlements` is empty.** `no_payout_expected` (§5.1, `NET_ZERO_SETTLEMENT`)
requires a settlement netting to zero, which clean data does not produce.

**`--breaks` CLI flag.** Named in §14's CLI list; absent until there are injectors to name. A
flag that accepts a value and ignores it is worse than a missing flag.

**`C2_MAX_POOL` is a constant, not a behaviour.** Wiring it into a tier is stage 8, per
instruction.

**`solve()` — the §9.3 pinned signature** `solve(pool, target, *, window_days, extra_terms, tol)`
does not exist. Only `solve_exact` does. `extra_terms` and the tolerance pass are stage 8, and
`tests/test_subsetsum.py` therefore covers §6.3's property test and the ambiguity path but not
the tolerance path §14 also lists for that file.

**`TARGET_AMBIGUOUS_RATE` is unmet by construction** — 0.08 against an actual 0.00. Explained
above: clean data cannot produce ambiguity once G3 applies. Stage 4 owns this number.

**Transaction types beyond `payment` and `refund`.** `dispute`, `transfer`,
`adjustment_credit`, `adjustment_debit` are handled by `net_contribution` and unit-tested, but
no generated row uses them, because each corresponds to a break (`DISPUTE_DEBIT`,
`ROUTE_SPLIT`). No `debit` bank lines exist yet either, so the signed target of finding 8.1 is
exercised only by tests.

**The real unparseable-narration rate.** 31.7% is what the generator injected. What a regex
actually fails on can only be measured in stage 6, and will be higher.
