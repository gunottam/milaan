# Stage 11 — one character, and a ledger on a screen

Written for someone who knows `docs/spec.md` and has not read the code.

Spec sections read: **§12** (API), **§13** (UI). Plus the experiment stage 10 recorded
and declined to run.

`pytest -q`: **149 passed in 16.9 s**; `pytest -q -m slow`: **72 passed in 6 m 15 s** — 221 in total, split at stage 11c below (212 at first commit; 11a and 11b add 9). Twelve are new in `tests/test_api.py`,
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

---

# Stage 11a — four issues from the board

Raised against the rendered screen, in priority order. All four were real; two of
them were findings about the *design*, not the pixels.

`pytest -q`: **220 passed.** Plus `cd web && npm run check` — a new structural check
on the proof strip, described at the end.

---

## 1. `recall 100.0%` beside `35 open` — the denominator was silently narrow

**The number was right and the label was not.** `recall` is computed over the
**headline bucket only** — §11's verified-unique lines plus refusals on lines nobody
rigged. Everything else is disclosed separately and has been since stage 7. At the
live 20 k budget the split is:

| bucket | n | outcomes |
|---|---|---|
| **headline** | **65** | TP 52 · TN 13 · **FN 0** |
| unproven | 57 | TP 43 · **FN 14** |
| by_construction_c3 | 6 | **FN 6** |
| by_construction_single | 4 | TP 4 |
| emergent | 2 | TN 2 |

So `TP/(TP+FN) = 52/52 = 100%` over a denominator of 52, while 20 lines score FN in
buckets the header never mentioned. Not a bug — but an unlabelled percentage over an
invisible denominator is exactly the kind of number this project exists to refuse,
and it read as a contradiction because it was one from the reader's side.

**Why the buckets are so much bigger here than on the committed board.** The
committed board generates at `UNIQUENESS_NODE_BUDGET_OFFLINE = 40_000_000` and has 3
lines in `unproven`. A browser-triggered run cannot afford that — it generates at
`UNIQUENESS_NODE_BUDGET_LIVE = 20_000`, and 57 lines land in `unproven` instead.
§10.1 is explicit that the budget is not a performance knob; this is that sentence
arriving as a headline denominator.

**Fixed** on both renderers:

```
precision 100.0% (verified-unique, n=65)        recall 100.0% (verified-unique, n=65)
69 of 134 scored lines are held out of this figure and broken out below.
```

The API now ships `headline_n` and a `buckets` array — every population by name with
its own TP/FP/FN/TN — and the UI renders them beside the headline behind a
`show all 5 scored buckets` control rather than implying them.

---

## 2. The residue gap was unexplained — and stage 10's `?` was wrong

Two problems, and the second is the interesting one.

The gap **is** ₹1,991.26 = 199,126 paise = exactly the four withheld records, same as
the committed board. Nothing had drifted. But it rendered as `?` with no way to take
it apart, because stage 10 made `reconciles` `None` for *any* deadline-cut run.

**The algebra says that was over-conservative.** Closing a line `L` with composition
`C` removes `target(L)` from the open sum and `Σ net(C)` from the unclaimed sum, so
the gap moves by

```
Σ net(C) − target(L)  =  the line's own delta
```

and by nothing else. **An exact match moves the gap by zero.** Measured, three ways:

| run | closed | gap | Σ tolerance deltas |
|---|---|---|---|
| nothing matched at all | 0 | ₹1,990.90 | — |
| deadline off | 99 | ₹1,991.26 | 36 paise |
| deadline 22 s | 99 | ₹1,991.26 | 36 paise |
| deadline 2 s | 79 | ₹1,991.12 | 22 paise |

Every row: `gap = baseline + Σδ`, to the paisa. So Phase E is computable on an
untouched board, and the deadline's exposure is **not** the ₹1,75,751.87 those five
cut lines total — it is at most `TOLERANCE_PAISE` each, because §8.2 caps what any
one match may absorb at ₹1.00. **₹5.00, against a gap of ₹1,991.26.**

`reconciles` is now `True` at zero, `None` only when the band could actually swallow
the gap, and `False` otherwise. On this run it reads **`does NOT reconcile`** —
determinate, despite the clock. Stage 10 was throwing away a bound it could compute.

The `!` chip expands to the composition, straight from `audit.py` so the sentences
and the identity live in one place:

```
residue gap ₹1,991.26   does NOT reconcile
    Σ   35 open bank lines                          ₹12,13,724.80
  − Σ  471 unclaimed and due transactions           ₹12,11,733.54
      2538 claimed                    ₹66,02,380.95   excluded (§9.7)
         0 not_yet_due                        ₹0.00   excluded (§9.7)
         0 no_payout_expected                 ₹0.00   excluded (§9.7)
    ₹1,990.90 of this was the gap before any line matched; closing a line moves it by
    that line's own delta and nothing else, so the whole matcher contributed ₹0.36.
    5 lines were cut by the deadline. §8.2 caps what one match may absorb at ₹1.00,
    so the clock can still account for at most ₹5.00 — the rest is a hole in the books.
```

`matcher_delta_paise` is a bonus: **a second, global derivation of how much G4
absorbed**, which agrees with the sum of the individual verdicts to the paisa.

**One route I tried and threw away.** Attributing the gap per line — `target(line)`
against its recovered settlement's total — sums to ₹5,52,722.09 against a real gap of
₹1,991.26. Open lines resolve *bogus* anchors by prefix collision (five separate
lines all claimed `setl_0000`), and a settlement already consumed by a closed line
produces a meaningless residual. That is stage 10's claim confirmed the hard way: the
per-line analysis cannot reproduce the gap, which is precisely why E1 exists.

---

## 3. `DUPLICATE_CREDIT` × 6 — the rule runs; the *pricing* was wrong

`reversal_pairs` **does** run in the API path, and it types all six lines correctly.
Six is the right count: three pairs × two bank lines. Each amount appears once
closed (the genuine settlement) and twice open (the duplicate posting and its T+1
contra), which is what §3.2 describes.

The defect was one field. Every row carried the full amount as
`amount_at_risk_paise`, so **AT RISK counted ₹1,25,737.50 twice for a pair that nets
to zero by construction** — ₹5,13,970.88 of phantom exposure in a figure that is
supposed to mean "the books cannot account for this".

---

## 4. Presentation

**AT RISK is now two figures that are never added together.** `risk_class` is stamped
on the exception in `matcher/ledger.py`, so the CLI board and the API cannot disagree
about which column a row belongs in. Three types are `documentation`, each with a
stated reason rather than a vibe:

| type | why it is not money at risk |
|---|---|
| `DUPLICATE_CREDIT` | a posting and its contra; the two rows cancel exactly |
| `AMBIGUOUS_EQUIVALENT` | §10.1 — either assignment gives **identical books** |
| `SETTLEMENT_CONTAMINATION` | the line is **closed** with a zero delta; confirm a tagging |

Everything else defaults to `at_risk`, so a new type is money until somebody argues
otherwise.

```
AT RISK              31 items   ₹10,80,606.67   the books cannot account for this
NEEDS DOCUMENTATION  13 items    ₹6,68,078.92   reconciled or bookkeeping-identical
                                 ₹2,56,985.44   of it is a posting and its contra (§3.2)
```

Each reversal row now names its partner (`⇄ bl_9007`) — one half alone reads as an
unexplained credit, and the pair is the finding.

**The closed column shows the first 8** with `show all 99 closed bank lines (91
more)`. **The `EXCEEDED_SEARCH_BUDGET` line-ID list moved into the open column**,
where it also carries the ₹5.00 bound from issue 2. The header banner is capped at
**two lines**.

**Greenbar parity, found while doing the above.** The tint was
`tr.row:nth-of-type(4n+3)`, and an expanded proof row is a `<tr>` too — so opening a
strip re-banded every row beneath it. On a ledger, banding that jumps reads as the
numbers having moved. The class now comes from the row's index in the data.

---

## Confirming the proof strip

§13's "expands in place, no modal" is a **structural** claim, and a screenshot cannot
settle it: a strip that is missing and a strip that is merely closed look identical.
No browser tooling was available, so `web/check-strip.mjs` (`npm run check`) renders
the real `<Row/>` through `react-dom/server` with `open` set and asserts on the
markup. esbuild and `react-dom/server` are already present as Vite and React
dependencies — no test runner, no jsdom, nothing new installed.

```
ok    closed: exactly one outer <tr>, caret pointing right
ok    open: a second outer <tr> appears
ok    the proof <tr> is a SIBLING of the data <tr>, not nested inside it
ok    and it is a real table row spanning the columns above it
ok    no modal, dialog, overlay or fixed positioning
ok    single rule above the total (tr.total)
ok    double rule below (div.double-under)
ok    the tick is in the margin
ok    figures use Indian grouping
ok    it ties, with the delta stated
ok    the caret flips to ▾ when open
```

It expands in place. What the screenshots were missing is that **nothing said the row
was clickable** — there was no affordance at all. Every expandable row now carries a
`▸`/`▾` caret in the margin, is focusable, and responds to Enter and Space.

---

# Stage 11b — the complete figure, and the budget that was hiding it

Seven items. The first two changed what the board claims; five were presentation.

`pytest -q`: **221 passed.** `cd web && npm run check` now asserts items 4–7 as
well, so none of them can regress into a screenshot nobody checks.

---

## 1. The complete recall figure, above the fold

The narrow figure was labelled and the complete one was not printed at all. Both now
sit on adjacent lines, in ink, at the same weight:

```
  precision 100.0% (verified-unique, n=105)        recall 100.0% (verified-unique, n=105)
  ALL LINES  TP   99  FP    0  FN    6  TN   29   precision 100.0%   recall  94.3%  (n=134)
  6 of those FN are in the disclosed buckets below, held out of the headline figure.
```

On the browser board (demo budget, live deadline) that reads
`recall 100.0% over verified-unique (n=105) · 9 FN in disclosed buckets ·
all-lines recall 91.7% (n=134)`.

`all_lines()` is a named function in `scoring/score.py` rather than
`report.counts()` with the default argument, because the complete denominator is
the number a reader checks the board against and a default argument is not
something anybody reads. The API ships it as `all_lines` beside `counts`, and the
UI prints the complete figure with an underline — demoting it typographically
would be the same evasion as hiding it behind a control, done with CSS.

---

## 2. `unproven: 57` — the demo was measuring a different board

Confirmed, measured and fixed. Seed 42, 120 payouts / 3,000 records, sweeping the
uniqueness budget between the live 20 k and the offline 40 M:

| budget | gen s | unproven | verified | ambiguous |
|---|---|---|---|---|
| 20,000 | 0.8 | **57** | 52 | 2 |
| 50,000 | 1.1 | 44 | 65 | 2 |
| 100,000 | 1.7 | 37 | 70 | 4 |
| 250,000 | 2.9 | 26 | 80 | 5 |
| 500,000 | 4.5 | 22 | 84 | 5 |
| 1,000,000 | 7.4 | 20 | 86 | 5 |
| 2,000,000 | 12.3 | 15 | 88 | 8 |
| **5,000,000** | **18.7** | **6** | **92** | 13 |
| 10,000,000 | 25.8 | 4 | 92 | 15 |
| 20,000,000 | 35.2 | 3 | 92 | 16 |
| 40,000,000 | 53.9 | 3 | 92 | 16 |

**The knee is 5 M and the reason is sharper than "single digits".** `verified`
reaches its ceiling of **92 — the same figure the 40 M offline run reports** — at
5 M. Beyond that only three lines move, and they move *out of* `unproven` and *into*
`AMBIGUOUS_SUBSET`; the headline population does not grow at all. So 5 M buys the
entire scored headline for 18.7 s.

`UNIQUENESS_NODE_BUDGET_DEMO = 5_000_000`, with the sweep table in the comment.
Measured end to end through the API: **31 s** — 19 s generate, 11 s match, audit and
scoring inside the rest. That overruns §15's 6 s generation line and fits its 60 s
ceiling comfortably. The overrun is deliberate: a demo that generates in under a
second and then measures a different board from the journals is the worse trade, and
§10.1 is explicit that the budget is not a performance knob.

**The board before and after, same code, same seed, same deadline:**

| | 20 k | 5 M |
|---|---|---|
| headline n | 65 | **105** |
| headline TP / FN | 52 / 0 | **92 / 0** |
| `unproven` | 57 | **6** |
| `emergent` (AMBIGUOUS_SUBSET) | 2 | **13** |
| all-lines recall | 83.2% | **91.7%** |
| end to end | 13 s | 31 s |

Nine FN remain on the browser board: six `SPLIT_PAYOUT` halves waiting on C3
(stage 13) and three still `unproven`.

**Two side findings, recorded and not acted on.** 20 M is *indistinguishable* from
40 M — 3 unproven, 92 verified, 16 ambiguous — at 35 s against 53.9 s, so the
committed offline budget carries ~19 s of pure waste. And `verified` plateauing at 92
means the 42 lines outside the headline are not budget-limited at all; no budget
recovers them. Changing the offline budget would regenerate the committed board and
move every pinned count in the suite, so it is a separate decision, not a drive-by.

---

## 3. The closed column was 90 % whitespace

`FIRST_SCREEN` 8 → **20**, and **the first row's proof strip renders open on
arrival**. §11.1 is that in production the proof strip is what a human verifies
*instead of* precision — so it is the claim the board is making, and a claim behind a
click is a claim nobody sees.

---

## 4. The double rule was there and invisible

`<div class="double-under">` has rendered since the first commit. The global
`* { box-sizing: border-box }` reset made `height: 3px` **include** both 1 px
borders, leaving a 1 px gap — two rules 1 px apart render as one thick line, which
loses the convention entirely. `box-sizing: content-box` on that one element, so the
height is the gap.

The check now asserts the element by name against §13.

---

## 5. `₹` on the total, bare line items

`fmtBare` for the rows, `fmtInr` for the total. A ledger does not repeat the symbol
on every line, and a bare total is not obviously money — the total is the answer, so
it carries the mark. Asserted as *exactly one* `₹` in the arithmetic table, on the
total row.

---

## 6. The delta has its own line

It was sharing a flex row with the tie sentence and wrapping under the transaction
count, where the figure a judge reads closest looked like a trailing note. It is now
its own right-aligned line at 160 px — the same column as the total it refers to —
in weight 500 and `white-space: nowrap`.

---

## 7. Derived rows carry an em dash

MDR, GST and TDS have no count of their own; the blank cells read as missing data.
An em dash in `--rule` says "not applicable here", which is what it is. Asserted:
exactly one `count derived` cell in the fixture, and the payments row still shows
`29`.

---

## The check earns its place

`npm run check` grew from 11 assertions to 13 and now covers items 4 through 7:

```
ok    double rule below (div.double-under) — §13 ledger convention
ok    ₹ appears exactly once in the arithmetic table, and on the total
ok    derived rows carry an em dash, not a blank cell
ok    the delta is on its own line, not sharing a row with the tie sentence
```

One assertion was written with a `|| true` in it while I was iterating and has been
deleted rather than shipped. A green that cannot fail is worse than no green.

---

# Stage 11c — splitting the suite, and what was actually slow

`pytest -q`: **149 passed in 16.9 s.** `pytest -q -m slow`: **72 passed in 6 m 15 s.**
149 + 72 = 221, the whole suite, nothing dropped.

---

## The diagnosis was wrong and the request was right

The brief said runtime went from 28 s to 394 s "when the fixture moved to the 5M
budget." **The fixture never moved.** `tests/conftest.py` has generated seed 42 at
`NODE_BUDGET = 2_000_000` since stage 7 and still does; the 5 M constant added at
stage 11b is `UNIQUENESS_NODE_BUDGET_DEMO`, and its only consumer is `api/main.py`
when a browser asks for a run. No test uses it.

`--durations=25` says where the 392 s goes:

| cost | test |
|---|---|
| 88.9 s | `test_orchestration` setup — the 2 M generate plus several uncapped ladders |
| 45.0 s | `test_audit::test_the_gap_survives_every_other_break_on_the_committed_board` |
| 44.9 s | `test_api` `report` fixture — `build_report(SEED42, deadline_ms=None)` |
| 44.9 s | `test_audit` `board` fixture |
| 44.6 s | `test_phase_c` `full` fixture |
| 44.1 s | `test_audit::test_the_ledger_is_reproducible_across_two_builds` |
| 41.8 s | `test_phase_c` `with_c1` fixture |
| 16.5 s | `test_breaks` setup — the 2 M generate |
| **~21 s** | **everything else, 213 tests** |

**Six tests each run `run_ladder(deadline_ms=None)` over 134 lines at ~45 s
apiece.** That is stage 11's regex widening, and the journal above already priced it:
the uncapped board went from 25.6 s to 43.8 s because A3 now hands C1 up to 123
candidate anchors per line (§9.5) and with no clock every one is searched to
exhaustion. The 2 M generate is 13 s of the 392, unchanged since stage 7.

So the axis is not fast-budget versus slow-budget. It is **"does this test's
assertion live on the 134-line board"** — because that is what an uncapped ladder
costs, and those are the tests that need one.

---

## The split

`pyproject.toml` gains the marker and applies `-m 'not slow'` in `addopts`. A `-m`
on the command line **replaces** it rather than adding to it, so `-m slow` runs the
board set and `-m ""` runs everything.

Marking is **keyed on the fixture closure, not on the test**:

```python
BOARD_FIXTURES = frozenset({"seed42", "board", "report"})

def pytest_collection_modifyitems(config, items):
    for item in items:
        if BOARD_FIXTURES & set(getattr(item, "fixturenames", ())):
            item.add_marker(pytest.mark.slow)
```

Six lines, and it is the right six. A decorator per test is a list that drifts the
moment somebody adds one; `item.fixturenames` is the transitive closure pytest has
already computed, so `run`, `baseline`, `with_c1` and `full` are all caught through
their dependency on `seed42` without naming any of them. A new test that touches a
board fixture is marked without anyone remembering to.

Exactly one test needed a hand-written `@pytest.mark.slow`:
`test_the_gap_survives_every_other_break_on_the_committed_board` reads the committed
CSVs directly and runs its own ladder, so there is no fixture to key on. The comment
on it says why.

---

## What the default sweep still covers

The 149 fast tests are not a smoke screen. They keep:

- every gate rejection (`test_gates`, 26)
- §6.3's brute-force property test against the DFS (`test_subsetsum`, 13)
- the fee and money golden cases (`test_fees`, 17)
- all five invariant greps (`test_invariants`)
- §10.2's six delta diagnostics, on hand-built transactions
- the hand-built ledger and audit cases — reversal pairs, the risk split, the orders
  tie-out, the four-way partition arms
- **§9.7's acceptance criterion.** `test_the_residue_gap_equals_the_withheld_net`
  runs in the default sweep, because the `isolated` fixture is a deliberately small
  40-payout dataset at a 500 k budget and costs ~15 s. The strongest assertion in the
  project is not behind an opt-in.

What moves to `slow` is the *measurements*: pinned tier counts, recall figures, the
anchor census, the committed-board residue gap and ledger, the reproducibility
check. Those need the board by definition.

**And that is the risk this split creates, stated plainly:** a change that moves a
measured count is now invisible to `pytest -q`. `CLAUDE.md` says to run `-m slow`
before committing a stage and always after touching `matcher/`, `generator/` or
`scoring/`, and `docs/build-stages.md` makes it a stage-14 gate — the regression
exists to defend exactly those numbers, and a stage-14 run that shells `pytest -q`
and sees green has checked the gates and the solver and none of the measurements.

`regression.json` and the slow set answer different questions and stage 14 needs
both: the regression measures **variance across ten seeds**, the slow set pins **the
committed seed at the offline budget**. A change that moves seed 42 and nothing else
passes the first and fails the second.
