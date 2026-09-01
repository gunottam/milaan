# Stage 11 — one character, and a ledger on a screen

Written for someone who knows `docs/spec.md` and has not read the code.

Spec sections read: **§12** (API), **§13** (UI). Plus the experiment stage 10 recorded
and declined to run.

`pytest -q`: **212 passed, 0 skipped**, in 7 m 30 s. Twelve are new in `tests/test_api.py`,
two in `tests/test_gates.py`, and seven pinned counts moved and were re-pinned to measured
values.

New files: `api/main.py`, `web/` (Vite + React), `tests/test_api.py`.

---

## Part one — the experiment

Stage 10 found the cause of the last two headline FN and declined to fix it: `FRAGMENT_RX`
is `N?[A-Z]{2,6}\d{2,}`, demanding **two** trailing digits, so the 6-character truncation
`NHDFC2` was never emitted as a fragment and never reached §9.5's prefix cascade. Widening
to `\d+` gives that fragment **123 candidates** — nearly the whole book — and stage 10 read
that as a cost not worth paying.

**That reading was wrong, and the argument against it is the one you gave: stage 6 measured
A3's median at 123 candidates with zero wrong anchors. A large candidate set is what the
cascade is built for.** §9.5's four filters are prefix, date window, exclusivity, arithmetic
— and filters 2 to 4 are G1 and G2, which are not weakened by being handed more to reject.
Refusing to enter the cascade is strictly worse than entering it and being filtered: the
first loses the answer, the second costs nodes.

### Result

| | Before | After |
|---|---|---|
| **Wrong anchors** | 0 | **0** |
| Anchors recovered | 93 | **101** |
| Precision | 100.0% | **100.0%** |
| Recall (headline) | 97.8% | **100.0%** |
| Headline TP / FP / FN / TN | 90 / 0 / 2 / 13 | **92 / 0 / 0 / 13** |
| Lines closed | 97 | **99** |
| `bl_0083`, `bl_0102` | FN | **TP, both at C1** |
| Residue gap | ₹1,991.26 | **₹1,991.26** |

**The revert condition never fired.** Zero wrong anchors at the committed 40M board *and* at
the 2M test fixture, and zero wrong compositions in either. Precision stays at 100%.

The two lines close exactly where §9.1's amendment says they should: **at C1, not at A3.**
`NHDFC2` resolves to 123 candidate settlements, G1's exclusivity filter kills the claimed
ones, and what survives becomes the anchor C1 needs to run its residual search. Phase A's
product is an anchor, not a composition — the amendment is now load-bearing rather than
descriptive.

### What it cost

| | Before | After |
|---|---|---|
| Board, `--deadline-ms 0` | 25.6 s | **43.8 s** |
| Board, live deadline (22 s) | ~10 s | **10.9 s** |
| Full `pytest -q` | 187 s | **337 s** (450 s once `test_api.py` lands) |

The uncapped run nearly doubles: 8 more anchors × up to 123 candidate settlements each is a
lot of anchored residual searches, and most are refused. (The suite's further rise to 450 s is
`test_api.py`, which walks the full 40M board twice more; 150 s of the total is the widening.)

**Under the live deadline it costs nothing measurable** — 10.9 s against a 22 s Phase C
allocation, still inside §15's budget, and the deadline consumes 5 lines either way. The expensive configuration is the reproducible
one that the regression harness uses offline and the demo never runs.

Judgement: worth it. Two false negatives converted to true positives, no false positive
created, and the cost lands in the mode that has no clock to answer to.

### The seven pinned counts that moved

Every one is a stage 6/7/8 fixture number, re-pinned to a re-measurement rather than relaxed.

| Test | Was | Now |
|---|---|---|
| Phase A+B per tier | A1 40, A3 4, B1 16, B2 4 | A1 40, **A3 7, B1 13**, B2 4 |
| A3 pass-1 lines reached | 12 | **21** |
| C1 closures | 25 | **28** |
| C1 headline | TP 79 / FN 9 / TN 13 | **TP 82 / FN 6 / TN 13** |
| C2 pass-1 closed / declined | 8 / 16 | **7 / 15** |
| Full ladder headline (2M fixture) | TP 86 / FN 2 / TN 13 | **TP 88 / FN 0 / TN 13** |
| Anchors recovered | 93 | **101** |

Two of these deserve a sentence rather than a row.

**A+B still closes 64 — but A3 takes 3 lines B1 was taking.** Same total, three lines earlier
in the ladder, resolved on a recovered identifier instead of an amount collision. That is
tier-major ordering doing precisely what §9.8 puts it there for: stronger evidence first.

**C1's number was a registered prediction, and I have not quietly re-baselined it.** Stage 7
predicted "25 of the 35 headline misses already carry the anchor C1 needs" before C1 existed,
and C1 closed exactly 25. It now closes 28 — not because the residual search improved but
because Phase A hands it eight more anchors than it had when the prediction was made. The
claim under test ("every line that already had an anchor closes") still holds; the population
that has one grew. The docstring in `test_phase_c.py` says so, because converting a
falsifiable prediction into a description of whatever the code does is how a test stops being
worth anything.

---

## Part two — a bug the API found

Writing `tests/test_api.py` produced the first assertion in the project that compared
`Proof.delta_paise` against `Verdict.delta_paise`. They disagreed: **−166 against 6.**

`core/proof.py` summed its deductions over *every* transaction in the composition:

```python
amount = sum(getattr(t, field) for t in chosen)     # wrong
```

But `net_contribution` (§3.1) subtracts fee, GST and TDS **for payments and nothing else** —
a refund contributes exactly `−amount_paise`. And thirteen refunds on seed 42 carry a non-zero
`fee_paise`, because `ROUNDING_DRIFT` and `INSTANT_SETTLEMENT` allocate their charge across a
settlement's members (§4.3) without caring what type each member is.

So the strip deducted money the gate never deducted, and its total missed the gate's by up to
₹1.72 on any composition holding one of those refunds.

**This is the exact failure I8 exists to prevent, hiding inside the thing that displays I8.**
§11.1's whole argument is that precision is unmeasurable in production and *the proof strip is
what a human verifies instead*. A strip that does not equal the sum `check()` performed is
worse than no strip: it is a wrong number wearing the authority of an audit trail. It survived
stages 5 through 10 because nothing ever checked the proof's own arithmetic against the
verdict's — the proof was rendered, never reconciled.

Fixed to sum over payments only, and pinned by two tests in `tests/test_gates.py`, one of
which builds the exact shape that broke it.

---

## Part three — the API. §12

Four endpoints, and every ruling in §12 taken literally.

```
POST /api/runs                            -> { run_id }
GET  /api/runs/{id}                       -> { status, phase, progress, report? }
GET  /api/runs/{id}/lines/{bank_line_id}  -> Proof or Exception detail
GET  /api/runs                            -> directory glob over data/runs/*/report.json
```

**No SSE.** `setInterval` at 500 ms, one fetch. The run is under 60 s, so a stream buys
nothing a poll does not and adds a reconnect path to debug in the demo room.

**No SQLite.** In-flight state — phase and progress — is a dict behind a lock and dies with
the process. Finished state is `report.json` and the listing is `RUNS.glob("*/report.json")`.
A restart loses progress bars and no finished work, which is the correct thing to lose. A
directory mid-write is skipped rather than erroring.

**One computation, two renderers.** `build_report` calls the same `run_ladder`, `phase_e` and
`score` that `scoring.score.main` calls, in the same order. If the API had its own scoring
path the screen and the terminal could disagree about the same board, and this project is an
argument that a figure should be derivable twice and agree.

### Progress is measured, not interpolated

`run_ladder` grew one optional callback, `on_tier(name, pass_no, closed)`, fired as each tier
opens. Four lines, and it is a notification rather than a control — nothing it returns is
read. Without it the API would have to interpolate a bar against a timer, which for a 10-second
run means the bar is visibly lying for most of it. §12 asks for `phase` and `progress`; those
are now the ladder's actual tier and its actual closed-line count.

The tier→phase map is three entries (`A`→`phase_a`, `B`→`phase_b`, `C`→`phase_c`), with pass 2
reported as `propagation_2`. `detective_a` and `detective_b` are in the enum because §12 lists
them, rendered struck through — a phase that silently vanished would make the ladder look
shorter than the spec says it is.

### `use_llm` is accepted, ignored, and disclosed

The detective is stage 12. Refusing the request would be worse — the run is still a real run —
but reporting `use_llm: true` as satisfied would put a number on the board that no code
produced. The run carries a note saying so, and every `closed_line` is stamped
`source: "deterministic"` rather than left unstamped, because absent and `"deterministic"`
render identically and mean different things.

Same reasoning on the ablation line: `full_recall` is `null`, not a copy of the deterministic
figure. Two equal numbers on an ablation bar read as "the agent adds nothing", which is the
opposite of "there is no agent yet".

### The live budget is disclosed on every run

A browser-triggered run cannot generate at the 40M offline budget — that takes minutes. It uses
`UNIQUENESS_NODE_BUDGET_LIVE = 20_000`, and §10.1 is emphatic that the budget is not a
performance knob: it decides how many lines truth calls `verified` rather than `unproven`, so a
live-budget board and a committed offline board have different denominators and the difference
looks exactly like a regression. Every run says so in its notes.

---

## Part four — the UI. §13

Vite + React, plain CSS, no UI library. `App.jsx` (shell, controls, summary, poll loop),
`Board.jsx` (two columns, proof strip, exception detail), `money.js`, `styles.css`. Four files.

**There is not one `box-shadow` or `border-radius: >0` in the stylesheet.** §13 lists what to
avoid — drop-shadowed cards, gradient hero stats, rounded SaaS chrome, donut charts — and the
absence is the design, not an oversight.

- **Greenbar.** `tr.row:nth-of-type(4n + 3)` — every other *data* row, counting the proof
  expansion that may sit between them, so the banding does not break when a row opens.
- **Tabular figures.** `font-variant-numeric: tabular-nums` on every numeral, id and amount.
  It is the one typographic decision the whole screen rests on: columns of money align on the
  decimal without a single explicit alignment rule.
- **Indian digit grouping** is `Intl.NumberFormat('en-IN')` — the platform does lakh/crore
  grouping natively, so there is no hand-rolled grouper to keep in step with `fmt_inr`. The
  sign sits *after* the rupee mark (`₹-4,500.00`) because that is where `fmt_inr` puts it, and
  two formatters disagreeing about a minus sign in a demo is a bad minute.
- **IBM Plex, self-hosted** via `@fontsource`, not a CDN. The demo room may have no network,
  and a webfont that fails to load takes the tabular figures with it.
- **Motion:** rows settle in with a 40 ms stagger, capped at 24 rows so the last one is not a
  second late. Nothing else animates. `prefers-reduced-motion` turns it off.

### Two nouns, never conflated

The header reads, from the live run:

```
134 bank lines · 3,009 transactions · 10.8s
99 lines closed   0 false   35 open   2,538 transactions tied   residue gap ₹1,991.26 !
exact 94 · tolerance 5 · via hypothesis 0 · precision 100.0% · recall 100.0%
deterministic 100.0% ────────────  agent not built — ablation delta arrives at stage 12
```

**Bank lines are closed or open. Transactions are tied.** 134 and 3,009 are different
quantities and the words say which is which — a screen reading "99 of 134 reconciled" leaves a
reader unable to tell whether 35 payouts or 35 payments are unexplained, and those differ by
two orders of magnitude in money. `transactions_tied` is read from Phase E's census rather than
recomputed, so it cannot drift from the audit that produced it.

### The residue gap has three states, not two

It sits in the header as §13 requires. `✓` reconciles, `!` does not, and **`?` when the run
was cut by its deadline** — because a partial run's gap contains open lines nobody looked at,
and calling that a discrepancy would report one that does not exist (§9.10). Stage 10 made
`Residue.reconciles` three-valued for exactly this; the header is where it becomes visible.

### The proof strip

Expands **in place**, no modal — a modal covers the row you are checking it against. Rendered
from the served `Proof.rows`, not recomputed in the browser: a front end that re-derived the
arithmetic would be a second implementation of it, and the point of the strip is that a human
reads the same figures the gate did.

```
bl_0000                                      A1 · exact · deterministic
    29  payments captured                            97,539.19
 −      MDR                                           1,282.58
 −      GST @ 18% on MDR                                230.85
 −      TDS @ 0.10% u/s 194-O                            97.52
                                             ─────────────────
                                                     95,928.24
                                             ═════════════════
 ✓ ties to the credit of 04-Jan-2026 · setl_0000 · 29 transactions tied    0 paise delta
```

Single rule above the total, double rule below — the bookkeeping mark for a closed sum, and
the reason the strip reads as a statement rather than a table of numbers. The sign lives in
the left margin and figures are unsigned, per §13's sketch. `✓` in the margin of every exact
row; `~` when a tolerance match closed it.

**The `--hypo` marker exists and nothing triggers it.** `source: "hypothesis"` renders a `◆` in
`--hypo` on the row and colours the strip header. No such match exists until stage 12; the rule
is written now so that when one arrives its provenance is unambiguous rather than needing a
stylesheet change to become visible.

### The finding the UI forced

A test asserting "a line is a proof **or** an exception, never both" failed on three lines:
`bl_0017`, `bl_0028`, `bl_0052`. All three are **closed** and all three carry a
`SETTLEMENT_CONTAMINATION` exception.

That is not a bug, it is §9.4: *accepted* matches spanning more than one settlement are flagged
for human confirmation. The line is closed — G3 accepted the shape, G2 balanced it to zero — and
the flag is an annotation on a match, not a refusal.

The API had been dropping it: `line_detail` checked `closed_lines` first and returned the proof,
so the flag was unreachable for exactly the three lines that had one. Both halves now ship —
each closed row carries a `flags` array, and the strip renders it under the double rule in
`--break` with a `⚑`. Hide the flag and a mis-tagged transaction is absorbed silently, which is
the shape `SETTLEMENT_CONTAMINATION` takes once it has been; hide the proof and a balanced line
reads as unexplained.

---

## Running it

```bash
python -m uvicorn api.main:app --port 8000
cd web && npm install && npm run dev        # http://localhost:5173
```

Vite proxies `/api` to 8000, so the browser stays on one origin and nothing depends on the CORS
middleware being permissive — that is there for the demo room, not for this.

**Verified end to end through the proxy** — POST, poll, `done` in 10.8 s, 99 closed, the full
report shape asserted by twelve tests. **Not verified visually**: no browser tooling was
available this session, so the rendering itself is unconfirmed. Open `http://localhost:5173`,
press Run, and click a closed row.

---

## Invariants

Untouched. `api/` reads `truth.json` only through `scoring/`, which is the one module allowed
to (I3). `source` is stamped on the serialised result and never on `Claim` (I9) — the grep test
still passes. `Verdict(ok=True)` appears nowhere outside `matcher/verify.py` (I2). The
`core/proof.py` fix moved the strip *closer* to I8, not further: its total is now
`Σ net_contribution(composition)` by construction, and a test pins it.

`pytest tests/test_invariants.py`: green.
