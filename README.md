<div align="center">

# मिलान · Milaan

**Settlement reconciliation, proved to the paisa.**

*Milaan (मिलान) is what an Indian accountant calls this job — the matching.*

<br>

`NUMBERS_BADGE`

<br>

[Watch the 5-minute walkthrough](https://youtu.be/FJh4DyQDdck) · [Design spec](docs/spec.md) · [Build journals](docs/journal/)

</div>

<br>

---

<br>

## The question

A business sells online. Tuesday, **₹56,044.38** lands in their bank account from their payment gateway.

Their store dashboard says they sold more than that.

So where's the difference?

Nobody can answer that from either screen. Here is what the bank statement says:

```
bank_line_id | narration                              | credit
bl_0004      | MMT/IMPS/NHDFC2/RAZORPAY  SOFT/        | ₹56,044.38
```

One number, and a reference the bank has truncated to six characters. The finance person now opens Excel. This takes days. Every payout. Forever.

<br>

## Why it is hard, not just tedious

The money is short for five legitimate reasons, and none of them appear on the statement:

| | |
|---|---|
| **Refunds** | Netted off — sometimes for orders from a different week |
| **Dispute holds** | Withheld pending resolution |
| **MDR** | The gateway's cut. 2% on cards, 0% on UPI, 3% international |
| **GST** | 18% on that cut, computed on the already-rounded fee |
| **TDS u/s 194-O** | Withheld at source on gross |

And this is not one payment. That single credit is **25 separate payments minus two refunds**, with fees that differ per payment depending on how each customer paid.

There is no ID connecting the bank line to those orders. The bank does not know about orders. The store does not know about the bank.

<br>

## What Milaan does

Three files in — bank statement, gateway ledger, order list. For every bank line, one of exactly three outputs.

<br>

**A closed line, with the arithmetic:**

```
  bl_0004                                    A3 · exact · deterministic

       25  payments captured                            69,233.19
    −   2  refunds netted                               11,995.00
    −       MDR                                            953.03
    −       GST @ 18% on MDR                               171.55
    −       TDS @ 0.10% u/s 194-O                           69.23
                                              ─────────────────────
                                                     ₹56,044.38
                                              ═════════════════════
  ✓ ties to the credit of 13-Jan-2026 · setl_0004        0 paise delta
```

<br>

**A refusal, with what is undetermined:**

```
  setl_0048   bl_0048 + bl_9003              ₹44,453.90 + ₹43,377.70

  279  DIVISIONS BALANCE

  setl_0048 ties to this credit and bl_9003 jointly to the paisa, but 279
  divisions of the payout balance against this credit, and the statement
  does not say which of them this credit carried.

  Refused. Blocked on: a bank advice naming the transactions behind each credit.
```

The 279 is counted, not guessed. The search stops at two solutions — two is already a refusal — so it can only ever report *"at least 2"*. A separate meet-in-the-middle census counts the rest exactly, and it returns a count and no compositions, so nothing downstream can act on it. *"The solver gave up"* and *"the input does not contain the answer"* are different findings, and only the second one is true here.

<br>

**An exception, with what is blocking it:**

```
  exc_0001  bl_0061      ₹1,24,363.46   WITHHELD_RECORD   low   >30d

  · No settlement id recovered; 0 tiers proposed 0 candidates and none balanced
  · −12436346 paise matches no fee, tax, premium, remainder or unclaimed net
  · The gap can be sized and located, not attributed: a record absent from
    every export leaves nothing to name

  blocked on: An identifier for this credit — nothing in the narration, the
              reference or the amount index resolves ₹1,24,363.46 to a settlement.
  api_call:   GET /v1/settlements?from=2026-06-18&amount=12436346
```

<br>

> **Milaan is not an authority. It is an accelerator with its work shown.**
>
> It posts nothing, moves nothing and signs off on nothing. A human approves. The claim is not *trust the model* — it is *you don't have to, because the arithmetic is on screen.* Days of searching become minutes of reviewing.

<br>

## The controlling idea

> **Anything may propose a candidate. Only deterministic verification may approve one.**

Not *only arithmetic* — arithmetic is necessary and never sufficient. Two compositions can both balance perfectly and one still be wrong.

Four things propose candidates. **One thing approves them, and it cannot tell which proposed what.**

```
   regex        lookup        search        model
     │            │             │             │
     └────────────┴──────┬──────┴─────────────┘
                         ▼
                  Claim  (frozen, no source field)
                         │
                         ▼
              G1  exclusivity      entities exist and are unclaimed
              G2  arithmetic       sum of net equals target
              G3  coherence        shape of a real payout
              G4  tolerance        relaxes — the one risky gate
                         │
                         ▼
                      Verdict
                         │
                         ▼
              G5  uniqueness       over the verdict set, not one claim
```

A model hypothesis and a regex hit receive identical treatment, because the checker has no field to distinguish them. `source` is stamped on the *result* — for reporting only, never on the claim.

One rule sits in front of both layers rather than inside them: a credit with a T+1 equal-and-opposite counterpart is a duplicate posting and its contra, and no tier is offered either half. It is not a gate. A gate rejects a composition; this decides what may be proposed on.

<br>

### Every gate but one can only cost recall

| Gate | Kind | Failure direction |
|---|---|---|
| G1 exclusivity | Structural fact | — |
| G2 arithmetic | Proof, self-verifying | — |
| G3 coherence | Prior — an empirical claim | Rejects correct answers → lower recall |
| **G4 tolerance** | **Relaxation** | **Admits wrong answers → false match** |
| G5 uniqueness | Set-level refusal | Refuses → lower recall |

Every constraint is monotonically restrictive: it can remove candidates, never create one. So a wrong prior costs recall, not correctness — **except G4**, which is why it carries a double cap, a named-cause requirement, and its own scoreboard line.

<br>

## The numbers, and how they are measured

Milaan generates its own test data, so the correct answer for every payout is known **before the tool runs.** Accuracy is graded against an answer key rather than eyeballed.

NUMBERS_TABLE

**Two break types are deliberately unsolvable.** Getting them right means refusing to answer. A system that confidently resolves them is a system that will lie about real money.

<br>

## Honest results

Rigour means reporting the numbers that do not flatter.

NUMBERS_HONEST

**The LLM contributes 0.0 points of recall.** The deterministic tiers got there first. We report the zero rather than weakening the baseline to manufacture a gap.

It ships for two reasons. It repairs **transposed reference numbers** — where a bank has swapped two digits — which a `startswith` prefix cascade structurally cannot survive. And across **64 hypotheses it fabricated zero compositions**: when it did not know, it said so. The gates were never asked to reject a confident wrong answer, because none was offered.

**Some lines refuse permanently.** Not because the search is too slow — because the source data does not determine an answer. For one split payout, 279 divisions balance the credit and the statement records none of them. The only transaction ordering that recovers the right one is the generator's own emission order: the answer key. A tie-break that reads the answer key is not a matcher, it is a leak.

**Precision was 100% by luck before it was 100% by design.** On three of ten seeds a duplicate bank posting closed and the real payout scored a miss. Our primary seed was clean only because two lines happened to tie on pool size and sort by id. The fix reused a rule already in the codebase — a credit with a T+1 equal-and-opposite counterpart is a duplicate, not a payout — promoted from post-match typing to a pre-match exclusion. It cost no recall on any seed, and three seeds gained.

<br>

## Running it

```bash
git clone https://github.com/gunottam/milaan.git && cd milaan
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[detective,anthropic,api,test]'
```

Generate a dataset and score it:

```bash
python -m generator.generate --seed 42 --out data/runs/seed42
python -m scoring.score --run data/runs/seed42
```

The board:

```bash
uvicorn api.main:app --port 8000        # terminal 1
cd web && npm install && npm run dev    # terminal 2
```

Then `localhost:5173`. The proof strip is designed for **150% browser zoom** — below that the arithmetic will not survive a projector.

Tests:

```bash
pytest -q                # 247 fast, ~17s
pytest -q -m slow        # 79 slow, ~6m — the 40M-node budget set
npm --prefix web run check
```

<br>

## Layout

```
generator/     the data, the breaks, and the uniqueness gate that
               verifies truth before recording it
core/          integer paise, the fee engine, coherence, proofs
matcher/
  proposers/   regex · lookup · search — one protocol, one Claim
  gates.py     G1–G4
  verify.py    check() — the only passing verdict
  uniqueness.py  G5, set-level
  audit.py     Phase E — the residue gap
detective/     the model. Two passes, text only, no privileged path
scoring/       graded against truth. Never reachable from matcher/
docs/          spec.md · workflow.md · 17 build journals
```

<br>

## Ten invariants, enforced by tests

<details>
<summary><strong>Expand</strong></summary>

<br>

| | | |
|---|---|---|
| I1 | Integer paise | No floats outside the fee engine |
| I2 | Only `verify.check()` may pass a verdict | `Verdict` is not importable in `gates.py` |
| I3 | The detective never sees the answer key | No `truth` reference under `detective/` |
| I4 | Proposers emit claims, never matches | No verdict field on `Claim` |
| I5 | Set equality — no partial credit | 212 of 213 payments is a false match |
| I6 | Nothing is silently absorbed | Every verdict carries its delta |
| I7 | Every deduction sits on its transaction | No settlement-level terms at match time |
| I8 | No tier matches without a balanced proof | Tiers **select**; only gates **approve** |
| I9 | The verifier cannot write to the candidate | `Claim` is frozen and carries no `source` |
| I10 | Merchant free text never enters a prompt | Injection surface closed by construction |

**I8 is the load-bearing one.** A clean reference-number match that does not balance is not a match. Under a design that trusted the identifier, one payout in our dataset books at ₹29,262 when ₹49,242 arrived — and nobody ever finds out.

</details>

<br>

## Known limits, stated deliberately

| | |
|---|---|
| Cannot repair contamination | Detects it, names the settlement and the amount, refuses |
| Cannot name a missing record | The gap can be sized, not attributed |
| Greedy assignment | May be globally suboptimal, and on one seed it manufactured a false match by consuming the evidence of ambiguity. Measured, mitigation stated, not built — `docs/spec.md` §18.2 |
| Unmodelled fee schedules | Fails loudly — recall collapses visibly, never absorbed |
| Dense repeated pricing | Ambiguity rises, refusals increase. Correct degradation, but degradation |
| No auto-posting | By design. It proposes; a human approves |
| Precision unmeasurable in production | Real data has no answer key — that is why the tool was needed |

<br>

---

<div align="center">

<br>

**Milaan reasons from evidence in the input.**
**When the evidence is absent, it says so rather than substituting a plausible guess.**

<br>

It does not invent records to close gaps, and it does not invent distinctions to break ties.

<br>

Built for the Razorpay Buildathon · Track 04, AI Finance Controller

<br>

</div>
