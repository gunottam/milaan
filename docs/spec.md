# Milaan — Technical Design Specification

**Project:** Milaan (मिलान) — settlement reconciliation agent
**Event:** Razorpay Buildathon, Track 04 — AI Finance Controller
**Version:** 1.3 — **FROZEN. Build against this document.**
**Companion:** `milaan-workflow.md` (narrative + worked example, still current)

v1.3 merges 25 items: 5 review fixes, 13 edge-case findings (all ruled ACCEPT, §18),
4 architectural reframes, 3 late additions. Changelog at §18.

---

## 0. Invariants

Ten. Each is enforced by a mechanism, not a promise.

| # | Invariant | Enforcement |
|---|---|---|
| I1 | All money is `int` paise. No floats outside `core/fees.py`. | Grep test |
| I2 | Only `verify.check()` may return a passing verdict. | Grep test: no `Verdict(ok=True` outside `matcher/verify.py` |
| I3 | The detective never sees `truth.json`. | Grep test: no `truth` under `detective/` |
| I4 | Proposers emit claims, never matches. | `Claim` has no verdict field |
| I5 | Partial composition is a false match, not partial credit. | Scoring uses set equality |
| I6 | No difference is silently absorbed. | Every verdict carries `delta_paise` and a confidence band |
| I7 | Every deduction is recorded on the transaction that incurred it. | `tds_paise` is a column; FX and instant premiums fold into `fee_paise` |
| I8 | No tier returns a match without a balanced proof. Tiers **select**; only gates **approve**. | `check()` runs G1–G4 for every tier including O(1) ones |
| **I9** | **The verification layer has no write access to the candidate.** `Claim` is frozen and carries no `source` field. | `@dataclass(frozen=True)`; grep test that `Claim(` construction never passes `source` |
| **I10** | **Merchant free text never enters a prompt.** `notes` and `description` are excluded from all model context. | Grep test on `detective/prompt.py` |

### I8 restated, because it is the load-bearing one

A UTR hash hit is **evidence**, not proof. Once the detective recovers identifiers from
degraded narrations, an O(1) lookup that skips the arithmetic converts a plausible-but-wrong
parse into a confident false match. Worked example `bl_06` is the case: a perfectly valid UTR
match that must still be refused because the sum comes up ₹19,980 short.

### I9 restated

The claim that "the checker cannot tell a model hypothesis from a regex hit" is enforced by
the type, not by discipline. `check()` takes an immutable `Claim` and returns a `Verdict`. It
cannot alter the composition it was handed, so "transform an invalid candidate into a valid
one" is not an operation the layer can perform.

`source` is stamped on `MatchResult` — **output only**. If it ever appears on `Claim`,
someone will write a gate that trusts deterministic claims more than model ones, and the
guarantee evaporates silently.

---

## 1. The controlling thesis

> **Anything may propose a candidate. Only deterministic verification may approve one.**

Not "only arithmetic." Arithmetic is necessary and never sufficient — two compositions can
both balance perfectly and one still be wrong (see `bl_08`, §7 of the workflow doc).
Deterministic verification is the full gate chain.

### The monotonicity property

| Gate | Kind | Can the rule be wrong? | Failure direction |
|---|---|---|---|
| G1 exclusivity | Structural fact — a transaction is in exactly one payout | No, true by definition | — |
| G2 arithmetic | Proof — self-verifying | No | — |
| G3 coherence | **Prior** — an empirical claim about how payouts are assembled | **Yes** | Rejects correct answers → lower recall |
| **G4 tolerance** | **Relaxation** — admits what G2 rejected | **Yes** | **Admits wrong answers → FALSE MATCH** |
| G5 uniqueness | Set-level refusal — different arity, never approves | Over-eager | Refuses → lower recall |

**Every gate except G4 is monotonically restrictive — it can only remove candidates, never
create one. So a wrong prior costs recall, not correctness.**

G4 is the sole exception in the entire design and the only place a bad policy produces a
false match rather than a missed one. That justifies the double cap (§8.3) and the separate
scoreboard line.

### The two failure classes

| | Effect | Cost |
|---|---|---|
| Missed match — refuse when an answer existed | Exception ledger. A human resolves it | Minutes |
| False match — approve something wrong | Books wrong, silently. Propagates to GST and revenue | Severe |

Every design decision converts potential failures into the first class.

---

## 2. Money, time, formatting

```python
# core/money.py
Paise = int

def to_paise(rupees: str | Decimal) -> Paise: ...
def fmt_inr(p: Paise) -> str:   # 4619388 -> '₹46,193.88', Indian grouping (lakh/crore)
def round_paise(d: Decimal) -> Paise:   # ROUND_HALF_UP. The only rounding function.
```

Indian digit grouping is mandatory: `₹4,61,938.80`, never `₹461,938.80`.

**All time is IST (+05:30).** Gateway timestamps are IST-aware ISO8601; bank columns are IST
calendar dates; window comparisons are on the IST calendar date. Comparing a UTC timestamp to
an IST date misfiles every transaction within 5½ hours of midnight.

**Window key is `value_date`, falling back to `txn_date` when absent.**

---

## 3. Domain model

### 3.1 `gateway_txns.csv`

| Column | Type | Notes |
|---|---|---|
| `entity_id` | str | `pay_*` `rfnd_*` `disp_*` `adj_*` `trf_*` |
| `type` | enum | `payment` `refund` `dispute` `transfer` `adjustment_credit` `adjustment_debit` |
| `created_at` | ISO8601 IST | |
| `settled_at` | ISO8601 IST \| null | Rewritten by `ONHOLD_RELEASE` to the release cycle |
| `settlement_id` | str \| null | `setl_*`. Null for unassigned cross-cycle items |
| `settlement_utr` | str \| null | |
| `order_id` | str \| null | |
| `payment_id` | str \| null | Parent for refunds/disputes |
| `method` | enum | `upi` `card` `netbanking` `wallet` `rupay_debit` `intl_card` `emi` |
| `card_network` | str \| null | |
| `international` | bool | |
| `amount_paise` | int | **Always INR paise. Always positive.** Sign comes from `type` |
| `fee_paise` | int | MDR, inclusive of FX markup and allocated instant premium |
| `tax_paise` | int | GST on `fee_paise` |
| `tds_paise` | int | 194-O withholding, per transaction (I7) |
| `source_currency` | str \| null | Display only |
| `source_amount_minor` | int \| null | Display only |
| `fx_rate_micros` | int \| null | Rate × 1e6, integer (a float would breach I1). Display only |
| `on_hold` | bool | **Point-in-time display flag. The pool filter never reads it** |
| `settled` | bool | **Drives the residue partition, §12.2** |
| `description` | str | **Never enters a prompt (I10)** |
| `notes` | str | **Never enters a prompt (I10)** |

```python
def net_contribution(t: GatewayTxn) -> Paise:
    match t.type:
        case "payment":
            return t.amount_paise - t.fee_paise - t.tax_paise - t.tds_paise
        case "refund" | "dispute" | "transfer" | "adjustment_debit":
            return -t.amount_paise
        case "adjustment_credit":
            return t.amount_paise
        case _:
            raise ValueError(f"unknown txn type: {t.type}")
```

Never falls through. An unknown type is a generator bug and must crash loudly.

### 3.2 `bank_statement.csv`

| Column | Type | Notes |
|---|---|---|
| `bank_line_id` | str | `bl_0001` |
| `txn_date` | IST date | |
| `value_date` | IST date | |
| `narration` | str | Deliberately degraded, §3.4 |
| `ref_no` | str \| null | |
| `debit_paise` | int | |
| `credit_paise` | int | |
| `balance_paise` | int | **Presentational only** — derivable from debit/credit, no independent signal |

**Signed target (finding 8.1):**

```python
def target(line: BankLine) -> Paise:
    return line.credit_paise - line.debit_paise      # negative for debit lines
```

Every tier accepts a signed target. Chargebacks, reversals, Route clawbacks and
negative-net settlements all produce debits; B2 must be permitted to match a single negative
net. Pruning already handles mixed signs via the pos/neg suffix arrays (§9.3).

`DUPLICATE_CREDIT` is detected by its **T+1 reversal**: equal magnitude, opposite sign,
adjacent calendar day, similar narration. The balance column cannot detect it — a duplicate
posting is a real posting and the balance includes it.

### 3.3 `orders.csv`

| Column | Type |
|---|---|
| `order_id` | str |
| `order_date` | IST date |
| `customer_ref` | str |
| `gross_paise` | int |
| `currency` | str |
| `status` | `paid` `refunded` `partially_refunded` `cancelled` |
| `invoice_no` | str \| null |

**Secondary tie-out — one query, ~10 lines, not on the cut list:** orders with
`status = 'paid'` and no gateway `payment` carrying that `order_id` → `ORPHAN_ORDER`.
This earns the word "multi-source" and is too cheap to cut.

### 3.4 Narration realism

```
NEFT-RAZORPAYSOFTW-HDFC0000060-N{utr}-RZPSETTLE
IMPS/{utr}/RAZORPAY SOFTWARE PVT/SETTLEMENT
UPI/CR/{ref12}/RAZORPAYSOF/HDFC/settlement
MMT/IMPS/{utr_truncated}/RAZORPAY  SOFT/
{blank}
CHGBK-{partial_disp_ref}-RZP ADJ
INSTSETL RZP {utr} FEE INCL
```

Degradation (`--noise`): truncate UTR to 5–8 chars, drop entirely, collapse whitespace,
uppercase, transpose two digits, abbreviate the legal entity name.

At `--noise high`, ~30% of narrations must be unparseable by regex alone.

---

## 4. Fee, tax, allocation

```python
MDR_BY_METHOD = {
    "upi": Decimal("0.0000"), "rupay_debit": Decimal("0.0000"),
    "card": Decimal("0.0200"), "netbanking": Decimal("0.0200"),
    "wallet": Decimal("0.0200"), "emi": Decimal("0.0300"),
    "intl_card": Decimal("0.0300"),
}
GST_ON_FEE   = Decimal("0.18")
TDS_194O     = Decimal("0.001")   # 0.1% since Oct 2024. CONFIG — verify before demo day
TCS_GST      = Decimal("0.005")   # marketplace TCS, off by default
FX_MARKUP    = Decimal("0.0100")  # folded into fee_paise, never a separate term (I7)
INSTANT_FLAT = 25_00              # ₹25 per instant settlement, allocated per §4.3
```

### 4.2 Per-transaction

```python
def expected_fee(txn) -> tuple[Paise, Paise, Paise]:
    rate = MDR_BY_METHOD[txn.method] + (FX_MARKUP if txn.international else 0)
    fee = round_paise(txn.amount_paise * rate)
    tax = round_paise(fee * GST_ON_FEE)        # GST on the ROUNDED fee
    tds = round_paise(txn.amount_paise * TDS_194O)
    return fee, tax, tds
```

**The recompute check applies to `type == "payment"` only.** Everything else carries
`fee_paise = 0` by construction; checking them reports a mismatch on every row.

### 4.3 Allocation — the mechanism behind `ROUNDING_DRIFT`

```python
def allocate(total: Paise, txns: list[GatewayTxn]) -> dict[str, Paise]:
    per = total // len(txns)          # remainder DELIBERATELY discarded
    return {t.entity_id: per for t in txns}
```

The dropped remainder is `total % n` paise, at most `n − 1`. That is a bounded, explainable
drift between the sum of allocated figures and the bank credit, and it is exactly what G4's
tolerance band exists to catch. Sum of per-transaction integers equals sum of per-transaction
integers, so without allocation the drift is identically zero and the break is a no-op.

---

## 5. Break taxonomy

Eighteen. Fourteen solvable, four structural or unsolvable.

| Code | Description | Generation | Detection |
|---|---|---|---|
| `TIMING_SHIFT` | Settles next cycle | Push `settled_at` +1 cycle | C2, widened window |
| `ONHOLD_RELEASE` | Held N cycles | `on_hold=true`, rewrite `settled_at` | C1 anchored |
| `CROSS_CYCLE_REFUND` | Refund netted on another day | `settlement_id = null` | C1 residual |
| `DISPUTE_DEBIT` | Chargeback as a bank debit | `disp_*` + debit line | B2, signed target |
| `ROUNDING_DRIFT` | Allocation remainder dropped | §4.3, injected deliberately | G4 tolerance |
| `DUPLICATE_CREDIT` | Bank posts twice | Duplicate line + T+1 reversal | Reversal-pair rule |
| `NARRATION_TRUNCATED` | UTR mangled | §3.4 degradation | A3, then D1 |
| `ROUTE_SPLIT` | Sub-merchant transfer | `trf_*` reducing the settlement | C1, negative term |
| `INSTANT_SETTLEMENT` | Off-cycle, flat fee | Flat fee allocated §4.3 | D2 window override |
| `FX_MARKUP` | International | `intl_card`, markup in `fee_paise` | C1, fee branch |
| `TDS_DEDUCTION` | 194-O withheld | `tds_paise` per transaction | C1 — a matcher ignoring `tds_paise` fails by design |
| `ORPHAN_ORDER` | ERP order, no payment | Suppress the payment | §3.3 tie-out |
| **`SETTLEMENT_CONTAMINATION`** | Transaction mis-tagged to the wrong settlement | Rewrite `settlement_id` | G3 coherence + Phase E |
| **`SPLIT_PAYOUT`** | One settlement across two bank lines | Split the credit | C3 |
| **`NEGATIVE_SETTLEMENT`** | Refunds exceed payments | Net negative → bank debit or carry-forward | Signed target |
| **`NET_ZERO_SETTLEMENT`** | Refunds exactly offset payments | **No bank line is created** | §5.1 classification |
| `WITHHELD_RECORD` | **Unsolvable.** Absent from all exports | Delete from gateway export | Must remain an exception |
| `AMBIGUOUS_SUBSET` | **Unsolvable.** Two valid compositions | Emerges naturally, §6.2 | G5 refusal |

### 5.1 `NET_ZERO_SETTLEMENT` — finding 8.2

A settlement netting to zero produces **no payout and therefore no bank line, ever.** Under a
naive design its transactions sit in the unclaimed pool forever and permanently corrupt the
residue check with a discrepancy that does not exist.

**Required:** any settlement whose net is zero is classified `no_payout_expected`, excluded
from B1's index and from the residue denominator, and reported as its own scoreboard line.
Carry-forward negative settlements are classified the same way.

---

## 6. Ground truth

### 6.1 `truth.json`

```json
{
  "seed": 42,
  "generated_at": "2026-08-24T15:30:00+05:30",
  "config": { "bank_lines": 120, "records": 3000, "noise": "high", "window_days": 2 },
  "bank_lines": {
    "bl_0001": {
      "resolvable": true, "uniqueness": "verified",
      "composition": ["pay_a1", "pay_a2", "rfnd_b1"],
      "injected_breaks": ["TIMING_SHIFT"], "expected_delta_paise": 0
    },
    "bl_0042": {
      "resolvable": false, "composition": null,
      "injected_breaks": ["WITHHELD_RECORD"],
      "unresolvable_reason": "Source transaction withheld from gateway export."
    },
    "bl_0077": {
      "resolvable": false, "composition": null,
      "injected_breaks": ["AMBIGUOUS_SUBSET"],
      "ambiguity_class": "equivalent",
      "alternate_compositions": [["pay_c1","pay_c2"], ["pay_c3","pay_c4"]]
    },
    "bl_0091": {
      "resolvable": true, "uniqueness": "budget_exhausted",
      "composition": ["pay_d1"], "excluded_from_scoring": true
    }
  },
  "settlements": { "setl_z": { "no_payout_expected": true, "reason": "net zero" } },
  "orders": { "order_9001": { "linked_payment": "pay_a1" } },
  "break_manifest": { "TIMING_SHIFT": 6, "NARRATION_TRUNCATED": 14 }
}
```

### 6.2 The uniqueness gate — stage 3, not stage 6

Repeated price points are realistic. Two ₹999 UPI payments have **identical net
contributions**, so if a true composition needs `k` of `m > k` identical transactions,
`C(m,k)` distinct entity-id sets sum identically. Ambiguity is the default state.

The generator runs the solver against every line it intends to mark resolvable:

| Outcome (budget `UNIQUENESS_NODE_BUDGET = 20_000`) | Truth record |
|---|---|
| Exactly one solution | `resolvable: true, uniqueness: "verified"` |
| Two or more | `resolvable: false`, `AMBIGUOUS_SUBSET`, alternates + `ambiguity_class` recorded |
| Budget exhausted | `resolvable: true, uniqueness: "budget_exhausted", excluded_from_scoring: true` |

**Divergence retained from v1.2:** ambiguous lines are *converted* to `AMBIGUOUS_SUBSET`
truth records, never re-rolled away. Re-rolling produces a dataset with no repeated pricing —
not what a merchant's book looks like — and discards free true-negatives. Amount jitter is
retained only as a rate control, targeting `TARGET_AMBIGUOUS_RATE = 0.08`.

**Bank-line-side ambiguity (finding 8.4).** Two bank lines with identical amount and date,
and two unclaimed settlements with identical totals, pass every filter. Any bijection
balances. Truth must mark the whole **set** unresolvable rather than asserting a specific
assignment — otherwise scoring penalises an answer that is bookkeeping-identical to truth.

### 6.3 The oracle must be checked — finding 8.9

The gate uses the same solver the matcher uses. A solver bug that misses a second solution
makes the gate miss it too, so truth asserts a uniqueness never established — invisibly, and
every recall number measured against it is wrong in a way no test catches.

**Required, non-negotiable, stage 3:** `tests/test_subsetsum.py` property test. For pools
of ≤ 18 items, generate random targets, run the DFS and a brute-force
`itertools.combinations` enumeration, assert identical solution sets. Brute force is
trivially correct at that size. **This is the only check that the oracle is sound.**

---

## 7. Architecture — proposal and verification

### 7.1 The two layers

| | Proposal layer | Verification layer |
|---|---|---|
| Members | Regex, lookup, search, model | G1–G4 (per claim), G5 (per set) |
| Creates candidates | **Yes — the entire job** | No |
| Approves | No | Yes |
| Sees `truth.json` | Never | Never |
| Failure cost | Missed candidate → recall | Wrong rule → recall, except G4 |

The model is **one proposer among four**, not a privileged component. The answer to "but your
LLM creates candidates" is: yes, and so does a hash lookup; neither approves anything.

Subset-sum manufactured a wrong-but-balanced composition in the worked example with no model
involved. What killed it was G3, which has no idea where the candidate came from — **the
source of a candidate is not recorded during verification.**

### 7.2 The protocol

```python
class Proposer(Protocol):
    name: str
    def propose(self, line: BankLine, pool: Pool) -> list[Claim]: ...

# Implementations: RegexProposer, LookupProposer, SearchProposer, DetectiveProposer

@dataclass(frozen=True)
class Claim:
    bank_line_id: str
    composition: tuple[str, ...]        # entity_ids, immutable
    anchor_settlement_id: str | None
    window_days: int
    extra_terms: tuple[str, ...] = ()
    # NO source field (I9)

@dataclass(frozen=True)
class Verdict:
    ok: bool
    gate: str | None          # which gate rejected
    reason: str | None
    proof: Proof | None
    confidence: Literal["exact", "tolerance"] | None
    delta_paise: Paise
```

Adding a proposer requires touching nothing in the verification layer. Ablation is a filter
over `proposer.name`, not a special case for the model.

### 7.3 The gate chain

`check(claim) -> Verdict` runs, in order:

| Gate | Test | On failure |
|---|---|---|
| **G1** exclusivity | Every cited entity exists, is unclaimed, and lies within the permitted window | Reject, `reason="stale or unknown entity"` |
| **G2** arithmetic | `Σ net_contribution(composition) == target(line)` | Fall to G4 |
| **G3** coherence | Composition shape is a plausible payout, §9.4 | Reject, `reason="spans N partial settlements"` |
| **G4** tolerance | Only if G2 failed. §8.3 double cap | Reject → unresolved |

**G5 uniqueness is not part of `check()`.** It is a predicate over the *set* of passing
verdicts for a line, applied by the orchestrator. It never approves anything — it withdraws
approval when two verdicts tie. Different arity; keeping it separate makes that visible.

### 7.4 G1 also validates model hypotheses — finding 8.10

A `subset_sum` claim can cite entities that do not exist, are already claimed, or fall
outside a sane window. G1 catches all three before the solver runs. Rejections are counted as
`MALFORMED_HYPOTHESIS`; a rising count is a prompt-quality signal, not a silent failure.

---

## 8. Tolerance — the sole non-monotonic gate

### 8.1 Why it is separated

G4 is the only rule in the design that admits a claim strict arithmetic rejected. It does not
*transform* the candidate — the composition is untouched — it **widens the target**. That
makes it neither a pure restriction nor a transformation, and the only gate whose bad policy
produces a false match rather than a missed one.

### 8.2 Acceptance rule

```
accept iff  abs(delta_paise) <= TOLERANCE_PAISE      # 100 paise = ₹1.00
      and   abs(delta_paise) <= len(composition)     # ≤ 1 paise per transaction
```

Both conditions. A ₹0.87 delta across three transactions is not rounding, it is a wrong
subset.

### 8.3 Reporting

Tolerance matches are counted on their own scoreboard line and never folded into the exact
count. `confidence = "tolerance"` is stamped on the verdict and surfaced in the proof strip.

---

## 9. The phases

Five. A bank line exits at the first phase producing a passing verdict, and drops on failure.

### 9.1 Phase A — identifier recovery, O(1)

| Tier | Method |
|---|---|
| A1 | Clean UTR in `ref_no` or narration, exact match to `settlement_utr` |
| A2 | `setl_[a-zA-Z0-9]+` token in narration |
| A3 | Extended regex: truncated UTRs, alternate bank formats, prefix extraction → §9.5 |

A3 is deliberately before any model call. ~85–90% of narration parsing is a regex problem and
should be solved deterministically and for free.

**Phase A selects a candidate set. It does not establish a match.** There is no separate
integrity check on the identifier — a wrong ID means the wrong set was grabbed, G2 fails, and
the line drops. One test instead of two, and it catches garbled IDs, missing transactions,
wrong settlements and hallucinated hints identically.

### 9.2 Phase B — amount lookup, O(1) amortised

| Tier | Method |
|---|---|
| B1 | Index unclaimed settlement groups by total; bank target → hash lookup |
| B2 | Single unclaimed transaction whose net equals the target exactly |

**B1 index maintenance (ruling on §10.10):** built once at run start as
`total_paise → [settlement_id]`. When a settlement is claimed, remove it from its bucket —
O(1) per claim, no rebuild per pass. ~15 lines.

**B1 must apply G5.** Two unclaimed settlements with the same total produce two candidates
with no search involved. v1.2's ambiguity handling lived only in the search phase and would
never have seen this (finding 8.4).

B2 handles single-transaction payouts and **debit lines** — a chargeback posted as a bank
debit matches one `disp_*` with a negative net.

### 9.3 Phase C — combinatorial search

| Tier | Method |
|---|---|
| C1 | **Anchored** subset-sum: seed with a known settlement, search only the residual |
| C2 | Unanchored subset-sum over the window pool, filtered by G3 |
| C3 | Pairwise split: two unmatched bank lines jointly composing one unmatched settlement |

**C1 ignores the date window.** Once the settlement ID is known, membership is a fact, not an
inference — which is why an on-hold release settled outside the window is recoverable through
C1 and invisible to C2.

```python
def solve(pool, target, *, window_days, extra_terms, tol) -> list[Solution]:
    """Signature PINNED. Deterministic path passes extra_terms=(), tol=0."""
```

**Pool construction.** Transactions whose `settled_at` IST calendar date lies in
`[value_date − window_days, value_date]`, excluding anything already claimed. **The filter
never reads `on_hold`.**

**Search.**

```python
def solve_exact(pool, target, budget):
    pool.sort(key=lambda t: (-abs(t.net), t.entity_id))   # tie-break for determinism (8.6)

    pos = suffix_sum(pool, lambda n: max(n, 0))   # max reachable from i onward
    neg = suffix_sum(pool, lambda n: min(n, 0))   # min reachable from i onward
    solutions, nodes = [], 0

    def dfs(i, remaining, chosen):
        nonlocal nodes
        if len(solutions) >= 2: return             # hard cutoff, BOTH branches
        nodes += 1
        if nodes > budget: raise SearchBudgetExceeded(nodes, len(pool))
        if remaining == 0 and chosen:              # empty subset is NOT a solution (8.3)
            solutions.append(tuple(t.entity_id for t in chosen)); return
        if i >= len(pool): return
        if remaining > pos[i]: return
        if remaining < neg[i]: return
        chosen.append(pool[i]); dfs(i+1, remaining - pool[i].net, chosen); chosen.pop()
        dfs(i+1, remaining, chosen)

    dfs(0, target, [])
    return solutions
```

**Tolerance pass** — runs only if `solve_exact` returned nothing:

```python
# At EVERY node, before recursing:
#     if chosen and abs(remaining) <= min(TOLERANCE_PAISE, len(chosen)):
#         candidates.append((tuple(...), remaining))     # RECORD, then KEEP SEARCHING
# After: take min(abs(delta)). Ties on |delta| with different sets -> G5 refusal.
```

Any node's `chosen` is a complete, legitimate candidate — you simply stop adding. Recording
at interior nodes is correct; **accepting the first one and returning is not.** A wider band
makes ambiguity more likely, so G5 applies to tolerance matches identically.

**C3 (finding 8.5).** For each unmatched settlement, test whether any two unmatched bank
lines in the window jointly sum to its total. O(n²) over a residue of ~10 lines. Cheap;
first on the cut list but not cut preemptively.

### 9.4 G3 coherence

A real payout is a **whole settlement group**, possibly plus a stray cross-cycle item.
Razorpay does not assemble payouts from partial slices of three settlements.

| Solution shape | Verdict |
|---|---|
| One complete settlement | Accept |
| One complete settlement + 1–2 items with `settlement_id = null` or from another group | Accept |
| Partial slices of 3+ settlements | **Reject** |

This is a **prior**, not a proof — an empirical claim about Razorpay's behaviour that we
assert. If wrong, it rejects correct answers and costs recall. It cannot admit a wrong one.

Accepted matches spanning more than one settlement are flagged
`SETTLEMENT_CONTAMINATION` in the audit for human confirmation.

### 9.5 The prefix cascade

Real UTRs are structured — `N` + bank code + date + sequence — so **every settlement from the
same bank on the same day shares a long prefix by construction.** Collisions are
near-guaranteed.

1. **Prefix match** — settlements whose UTR starts with the fragment
2. **Date window** — drop those outside `[value_date − window, value_date]`
3. **Exclusivity** — drop those already claimed
4. **Arithmetic** — drop those whose total does not close

| Survivors | Outcome |
|---|---|
| 1 | Match |
| 0 | Hint useless. Fall through, log as tried-and-failed |
| 2+ | G5 refusal — same path as a tied subset-sum, no new machinery |

Because ordering is tier-major, most settlements are claimed by the time prefix matching runs.
Filter 3 does most of the work.

### 9.6 Phase D — detective

Two passes, text only.

**Pass A** — narration strings only, no candidate context, batch 25, concurrent. The ~30%
unparseable rate is a pure text problem; candidates add nothing. Output feeds Phase A. Nearly
free, delivers most of the lift.

**Pass B** — residue after Pass A, structured amounts and entity IDs only, batch 5,
concurrent, 2 rounds.

**I10: `notes` and `description` never enter any prompt.** Merchant-controlled free text is a
prompt-injection surface. Note that even a successful injection cannot produce a false match —
the model has no path to a passing verdict — so the realistic damage is wasted budget and
degraded hypotheses.

| Claim | Params | Returns to |
|---|---|---|
| `narration_parse` | `extracted_utr` | Phase A |
| `direct_link` | `settlement_id` | Phase A |
| `subset_sum` | `candidate_ids`, `extra_terms`, `window_override_days` | Phase C |
| `split_across_cycles` | `partner_bank_line_id`, `settlement_id` | C3 |
| `unresolvable` | `break_type`, `blocked_on` | Exception ledger, typed |

The fifth claim exists because the model is handed a taxonomy containing unsolvable types and
otherwise has no way to say so. Exception typing is a scored metric. An accepted
`unresolvable` is still not a match, so I4 holds.

### 9.7 Phase E — global audit

**E1 residue gap:**

```
Σ open bank lines   vs   Σ unclaimed-and-due transactions
```

**Every line can balance individually while the books fail globally.** That is offsetting
errors, and it is why accountants run a trial balance instead of trusting each entry.

**The partition is four-way (finding 8.8):**

| State | In the residue denominator? |
|---|---|
| Claimed by a matched line | No |
| Unclaimed, `settled = true` | **Yes** |
| `settled = false` — not yet due | No |
| Member of a `no_payout_expected` settlement (§5.1) | No |

Counting not-yet-due transactions as unclaimed makes the gap permanently non-zero and the
check useless.

**E2 coherence audit:** flag settlements whose transactions were split across multiple bank
lines, for human confirmation.

### 9.8 Ordering and the loop

Matching is exclusive. Combined with first-come-first-served, processing order silently
determines outcomes — a speculative search match can consume transactions a Phase A line had
a hard UTR for.

**Tier-major ordering.** Every line attempts A1 before any line attempts A2, and so on down.
Within a tier, lines sort by ascending pool size then `bank_line_id`, so runs are reproducible.

The ladder runs twice (`PROPAGATION_PASSES = 2`). Resolving one line shrinks every other
pool, which can turn an ambiguous line into a determined one.

### 9.9 The system is greedy — finding 8.7

Matches are committed and never revoked. A line matching early can consume transactions a
later line needed, producing a globally worse assignment than optimising the whole board at
once. Tier-major ordering and most-constrained-first mitigate; they do not eliminate.

**Do not claim optimality.** State that assignment is greedy with strongest-evidence-first
ordering, and that Phase E surfaces the damage. A reviewer who works out that this is an
assignment problem solved greedily will respect the acknowledgement and distrust the omission.

### 9.10 Deadlines — finding 8.12

Per-line timeouts do not compose. `120 lines × 2s × 2 passes` blows any ceiling, and the
timeout is paid *most* on lines with no solution, because proving zero solutions means
exhausting the tree.

**Run-level deadline.** Each line gets `min(2000, remaining_ms / unmatched_count)`.

**On deadline exhaustion:** stop issuing work, mark unattempted lines
`EXCEEDED_SEARCH_BUDGET`, **run Phase E on partial results**, render the scoreboard with an
explicit banner — *"deadline reached — 12 lines unattempted."* Those lines score as FN. A
partial run that reports itself honestly demonstrates the thesis rather than failing it.

---

## 10. Exception ledger

```json
{
  "exception_id": "exc_0007",
  "bank_line_id": "bl_0042",
  "exception_type": "WITHHELD_RECORD",
  "type_confidence": "high",
  "amount_at_risk_paise": 1998000,
  "delta_diagnosis": "no_matching_residual",
  "age_days": 6, "age_bucket": "3-7d",
  "evidence": ["Settlement setl_F identified by UTR N4471051677",
               "Recorded transactions total ₹29,262.00 against a credit of ₹49,242.00"],
  "blocked_on": "A source record is missing from the gateway export.",
  "proposed_action": { "kind": "api_call", "detail": "GET /v1/settlements/setl_F/recon" },
  "hypotheses_tried": 2
}
```

`type_confidence` is the enum `high` / `medium` / `low`, derived from how many independent
evidence tokens corroborate the typing — never a model-produced float.

`blocked_on` must name the missing input in one sentence. "Could not match" is not acceptable
output.

### 10.1 Exception types

| Type | Meaning |
|---|---|
| `WITHHELD_RECORD` | Gap with no reachable composition; a source record is absent |
| **`AMBIGUOUS_EQUIVALENT`** | Alternatives have identical fee, GST, TDS, dates and entity types — **either assignment gives identical books.** 30-second human task |
| **`AMBIGUOUS_CONSEQUENTIAL`** | Alternatives differ in tax treatment, timing or counterparty. Needs investigation |
| **`UNIQUENESS_UNPROVEN`** | One solution found, but the budget expired before a second could be ruled out |
| `EXCEEDED_SEARCH_BUDGET` | Deadline consumed the line before any solution was found |
| `SETTLEMENT_CONTAMINATION` | Composition spans settlements, or Phase E flagged a split group |
| `ORPHAN_ORDER` | Paid order with no gateway payment |
| `MALFORMED_HYPOTHESIS` | Internal counter; model cited non-existent or claimed entities |

**`UNIQUENESS_UNPROVEN` matters more than it looks.** Uniqueness only means something if the
search was exhaustive. Finding one solution and hitting the budget before proving there is no
second is *"an answer, unknown whether unique"* — a different state from both a match and
"found nothing," and a human triages it differently.

This also reframes the node budget: **it is not a performance knob, it is what determines
whether the uniqueness guarantee holds.** Tightening it to hit the wall clock silently
converts proven-unique matches into unproven ones.

### 10.2 Delta diagnostics

When a line fails to close, the residual is often diagnosable by cheap arithmetic. Six checks,
run before typing the exception:

| Test on δ | Diagnosis |
|---|---|
| δ = 0.1% of composition gross | `TDS term missing` |
| δ = 18% of computed fee | `GST not applied` |
| δ = ₹25 flat, or ₹25 + GST | `Instant-settlement premium` |
| δ ≤ len(composition), in paise | `Allocation remainder` — retry via G4 |
| δ equals some unclaimed transaction's net | `Likely specific missing record` — name it as a candidate |
| δ = 3% − 2% of a transaction's gross | `FX markup not applied` |

Converts a bare number into a typed exception with a named cause. **Exception typing accuracy
is a scored metric**, so this directly improves a headline number for near-zero cost.

Sorting: by `amount_at_risk_paise` descending within `AMBIGUOUS_CONSEQUENTIAL` and
`WITHHELD_RECORD` first; `AMBIGUOUS_EQUIVALENT` last, since it is a documentation task.

---

## 11. Scoring

Against `truth.json`, never reachable from `matcher/` or `detective/`. Lines with
`excluded_from_scoring: true` are removed from all denominators.

For `truth.resolvable == true`:

- **TP** — the agent's composition set **equals** truth's
- **FP** — composition differs in any element
- **FN** — an exception, **including `EXCEEDED_SEARCH_BUDGET` and `UNIQUENESS_UNPROVEN`**

For `truth.resolvable == false`:

- **TN** — an exception (correct)
- **FP** — a match. A fabricated match; weight it visibly

```
precision = TP / (TP + FP)
recall    = TP / (TP + FN)
```

### Secondary metrics

| Metric | Definition |
|---|---|
| Exception typing accuracy | Fraction of exceptions whose type matches the injected break |
| Ablation delta | Recall filtered to deterministic proposers, vs full |
| Per-break recall | Injected / caught / missed, per code |
| Residue gap | Should reconcile to a single identifiable cause |
| Cost per 1k records | **Paise** (I1), from token accounting |
| Multi-seed variance | Mean ± σ across 10 seeds — **precomputed offline**, node-budget only (8.6) |

**Wall-clock deadlines make results machine-dependent.** The regression harness uses node
budget only, so its numbers are reproducible. The live run uses both and reports which lines
the deadline consumed.

### 11.1 On real data, precision is unmeasurable — finding 8.13

Every accuracy claim depends on `truth.json`. Real merchant data has no answer key — that is
why the merchant needed the tool. In production Milaan reports match rate, the arithmetic
behind every match, and the exception ledger. It **cannot** report precision. The synthetic
harness measures whether the *method* is sound; in production, the proof strip is what a human
verifies instead. Say this plainly rather than letting a reviewer discover it.

---

## 12. API

```
POST /api/runs                            -> { run_id }
     body: { seed, bank_lines, records, noise, use_llm }
GET  /api/runs/{id}                       -> { status, phase, progress, report? }
GET  /api/runs/{id}/lines/{bank_line_id}  -> Proof or Exception detail
GET  /api/runs                            -> directory glob over data/runs/*/report.json
```

**Polling at 500 ms. No SSE, no SQLite.** The run is under 60 s; an event stream is one more
thing to debug in the demo room, and a store written once and only listed is a directory glob.

`phase`: `generating`, `verifying_uniqueness`, `phase_a`, `phase_b`, `phase_c`,
`detective_a`, `detective_b`, `propagation_2`, `audit`, `scoring`, `done`.

---

## 13. UI

### Thesis

Not a dashboard — a **ledger**. Reference: a bank reconciliation statement on greenbar
continuous-feed paper. Ruled rows, tabular figures on the decimal, double rule under a final
sum. The job is to make numbers look *checkable*.

Avoided: drop-shadowed cards, gradient hero stats, rounded SaaS chrome, donut charts.

### Tokens

```css
--paper:#FBFBF8;  --bar:#EBF0E9;  --rule:#D5D8D0;
--ink:#1C1E1A;    --ink-soft:#6B6F66;
--tally:#1D6B4F;  --break:#A8452B;  --hypo:#6A5BA8;
```

Light only — projector legibility, and a ledger is paper.

**IBM Plex Mono** for every numeral, entity id and amount, tabular figures.
**IBM Plex Sans** for labels. Eyebrows 11px, tracking `0.12em`. Weights 400 and 500 only.

### Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  MILAAN              seed [____]  noise [high ▾]      [ Run ]    │
│  ══════════════════════════════════════════════════════════════  │
├──────────────────────────────────────────────────────────────────┤
│  120 bank lines · 3,000 transactions · 38.4s                     │
│  113 lines closed   0 false   7 open      residue gap ₹0 ✓       │
│  exact 104 · tolerance 9 · via hypothesis 21                     │
│  deterministic 78.6% ───────────────────▓▓▓ 94.2% with agent     │
├────────────────────────────────┬─────────────────────────────────┤
│  CLOSED                        │  OPEN ITEMS                     │
│  bl_0001  ₹1,09,501.94  ✓ C1   │  ₹47,882  WITHHELD_RECORD       │
│  bl_0002  ₹   89,120.00 ✓ A1   │  ₹18,240  AMBIG_CONSEQUENTIAL   │
│  bl_0007  ₹   −4,500.00 ✓ B2   │  ₹ 5,988  AMBIG_EQUIVALENT      │
└────────────────────────────────┴─────────────────────────────────┘
```

**Two nouns, never conflated.** *Bank lines* are closed or open; *transactions* are tied.
The residue gap sits in the header — it is the global honesty indicator.

### The proof strip

Clicking a closed row expands **in place**, no modal:

```
  bl_0001                                    C1 · exact · deterministic
       47 payments captured                            1,24,500.00
    −   3 refunds netted                                  8,200.00
    −   1 dispute hold                                    4,500.00
    −     MDR (mixed methods)                             1,842.00
    −     GST @ 18% on MDR                                  331.56
    −     TDS @ 0.10% u/s 194-O                             124.50
                                              ─────────────────────
                                                       1,09,501.94
                                              ═════════════════════
  ✓ ties to HDFC credit 15-Jan-2026                     0 paise delta
```

The one place to spend visual boldness. Hypothesis-sourced matches carry a `--hypo` marker
and the model's reasoning, so provenance is never ambiguous.

### Motion

Rows settle into the closed column as they resolve, ~40 ms stagger. Nothing else animates.
Respect `prefers-reduced-motion`.

---

## 14. Repo layout

```
milaan/
├── generator/
│   ├── config.py  entities.py  narration.py  breaks.py
│   ├── allocate.py        # §4.3 — the ROUNDING_DRIFT mechanism
│   ├── uniqueness.py      # §6.2 gate — STAGE 3
│   └── generate.py        # CLI: --seed --bank-lines --records --breaks --noise
├── core/
│   ├── money.py  fees.py  models.py  proof.py
├── matcher/
│   ├── proposers/
│   │   ├── base.py        # Proposer protocol, Claim
│   │   ├── regex_p.py     # A1-A3 + prefix cascade
│   │   ├── lookup_p.py    # B1 index (incremental), B2
│   │   └── search_p.py    # C1-C3
│   ├── gates.py           # G1-G4
│   ├── verify.py          # check() — the only passing verdict
│   ├── uniqueness.py      # G5, set-level
│   ├── diagnose.py        # §10.2 delta diagnostics
│   ├── audit.py           # Phase E
│   └── run.py             # tier-major ordering, propagation, deadlines
├── detective/
│   ├── schema.py  prompt.py  propose.py     # DetectiveProposer
├── scoring/score.py
├── api/main.py
├── web/
├── data/runs/
├── regression.json
└── tests/
    ├── test_invariants.py   # grep: I1, I2, I3, I9, I10
    ├── test_fees.py         # golden cases incl. allocation remainder
    ├── test_subsetsum.py    # PROPERTY TEST vs brute force (§6.3) + ambiguity + tolerance
    ├── test_gates.py        # each gate rejects what it should
    └── test_scoring.py
```

```python
# tests/test_invariants.py
def test_no_floats_in_core():
    assert not grep(r"\bfloat\(", ["core/", "matcher/", "generator/"])
def test_only_verify_approves():
    assert all(h.startswith("matcher/verify.py") for h in grep(r"Verdict\(ok=True", ["."]))
def test_detective_cannot_reach_truth():
    assert not grep(r"truth", ["detective/"])
def test_claim_carries_no_source():
    assert not grep(r"source", ["matcher/proposers/base.py"])
def test_no_free_text_in_prompts():
    assert not grep(r"\.notes|\.description", ["detective/"])
```

---

## 15. Config and budget

```python
SETTLEMENT_WINDOW_DAYS      = 2
TOLERANCE_PAISE             = 100
SUBSET_MAX_POOL             = 220
UNIQUENESS_NODE_BUDGET      = 20_000
SUBSET_NODE_BUDGET          = 250_000
PROPAGATION_PASSES          = 2
LLM_PASS_A_BATCH            = 25
LLM_BATCH_SIZE              = 5
LLM_ROUNDS                  = 2
DEFAULT_BANK_LINES          = 120
DEFAULT_RECORDS             = 3_000
TARGET_AMBIGUOUS_RATE       = 0.08
MAX_WINDOW_OVERRIDE_DAYS    = 5      # cap on model-supplied overrides (G1)
```

| Phase | Budget | Note |
|---|---|---|
| Generate | 6 s | |
| Verify uniqueness | 4 s | 120 × 20k nodes |
| Phase A + B | 2 s | O(1) tiers; B1 offloads work that would otherwise reach C |
| Phase C | 22 s | `MATCH_DEADLINE_MS`, per-line `min(2000, remaining/unmatched)` |
| Detective A | 3 s | Narration only, concurrent |
| Detective B | 9 s | Batch 5, concurrent, 2 rounds |
| Audit + score + render | 3 s | Phase E is two sums |
| **Total** | **49 s** | Hard ceiling 60 s |

Down from v1.2's 52 s: **B1 is a net reduction in load.** Every line it resolves by hash
lookup never reaches subset-sum, and C is by far the most expensive phase.

---

## 16. Build order

| Stage | Deliverable |
|---|---|
| 1 | `core/money.py`, `core/fees.py`, IST helpers, **golden tests written first** |
| 2 | `tests/test_invariants.py` — before there is anything to violate |
| 3 | Generator + `allocate.py` + **`uniqueness.py`** + **property test vs brute force** + `truth.json` |
| 4 | All 18 break injectors; verify manifest counts against reality |
| 5 | `Proposer` protocol, `Claim`, `Verdict`, `gates.py` G1–G4, `verify.py` |
| 6 | Phase A (A1–A3 + prefix cascade) and Phase B (B1 incremental index, B2) |
| 7 | `scoring/score.py` + CLI scoreboard — **measure before optimising** |
| 8 | Phase C: C1, C2 with G3, tolerance pass, G5 |
| 9 | Tier-major ordering, propagation, run deadline, graceful exhaustion |
| 10 | Phase E audit + `diagnose.py` delta diagnostics |
| 11 | React scoreboard + proof strip |
| 12 | Detective Pass A, then Pass B — ablation arrives free |
| 13 | C3 pairwise split |
| 14 | Offline 10-seed regression → `regression.json`; cost meter |

**Freeze at 14 and rehearse the live-seed run until it cannot fail.**

**Cut list, in order:** C3 · meet-in-the-middle · journal-entry drafting · the `--noise`
selector (hardcode `high`) · per-break table · `regression.json`.

**Never cut:** the uniqueness gate, the property test, G3, G5, the two unsolvable break
types, the orders tie-out, Phase E, the exception ledger, the live-seed re-run.

---

## 17. Known limitations, stated deliberately

| Limitation | Behaviour |
|---|---|
| Cannot repair contamination | Detects, names the settlement and amount, refuses. Repair needs a source we do not have |
| **Cannot name the missing record** | We know the settlement and the gap, not which record is absent. Two withheld transactions summing to the same figure are indistinguishable |
| Greedy assignment | May be globally suboptimal (§9.9). Phase E surfaces the damage |
| Unmodelled fee schedules | Fails loudly — nothing balances, recall collapses visibly. Never absorbs silently |
| Dense repeated pricing | Ambiguity rises, recall falls, refusals increase. Correct degradation, but degradation |
| G4 tolerance | The one gate that can admit a wrong answer (§8) |
| No auto-posting | By design. Proposes; a human approves |
| Precision unmeasurable in production | §11.1 |

**Milaan reasons from evidence in the input. When the evidence is absent, it says so rather
than substituting a plausible guess.** It does not invent records to close gaps, and it does
not invent distinctions to break ties.

---

## 18. Changelog, v1.2 → v1.3

**Review fixes (5):** B1 unclaimed-group-total tier · extended regex tier A3 ahead of the
model · prefix cascade §9.5 · G3 coherence constraint · Phase E residue gap +
`SETTLEMENT_CONTAMINATION`.

**Edge-case findings — all 13 ACCEPTED:** 8.1 signed targets and debit lines · 8.2
`NET_ZERO_SETTLEMENT` and `no_payout_expected` · 8.3 empty-subset guard · 8.4 ambiguity check
moves to B1 and truth marks the set unresolvable · 8.5 tier C3 · 8.6 sort tie-break and
node-budget-only regression · 8.7 greedy acknowledged · 8.8 four-way residue partition ·
8.9 property test vs brute force · 8.10 G1 validates hypotheses · 8.11 I10 free-text
exclusion · 8.12 graceful deadline exhaustion · 8.13 precision unmeasurable in production.

**Architectural (4):** thesis reframed to deterministic verification with the monotonicity
taxonomy · G4 tolerance split out as the sole non-monotonic gate · `UNIQUENESS_UNPROVEN` ·
proposal/verification layer split with I9 and `source` confirmed output-only.

**Late additions (3):** `Proposer` protocol making the layer split structural · delta
diagnostics §10.2 · ambiguity sub-typed into `EQUIVALENT` / `CONSEQUENTIAL`.

**Rulings on the §10 checklist:** dataset stays 120 / 3,000 — B1 is a net reduction in load,
re-budgeted to 49 s. B1 uses an incremental index with O(1) removal on claim, no per-pass
rebuild. C3 accepted but placed first on the cut list. The §6.3 property test is
non-negotiable.

**Correction to earlier prose:** an exception can name the *settlement* and the *gap*, not the
missing record. Recorded in §17.
