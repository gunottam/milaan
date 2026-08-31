# Stage 6 — Phase A identifier recovery, Phase B amount lookup

Written for someone who knows `docs/spec.md` and has not read the code.

Spec sections read: **§9.1** (Phase A), **§9.2** (Phase B) and **§9.5** (the prefix cascade).

`pytest -q`: **110 passed, 0 skipped.** Fourteen of them are new, and eight run the two
tiers against seed 42 rather than against hand-built universes.

```
seed42: 134 bank lines, 3009 transactions
  closed 64/134   A1 40   A2 0   A3 4   B1 16   B2 4      wrong 0
  exact 61   tolerance 3   open 70
  identifier recovered on 93 lines (A1 81, A3 12)   wrong anchors 0   G5 refusals 0
  gate rejections: G4 860   G1 450   G3 1
```

**A wrong subset is rejected by G4, not G2** — G2 cannot reject, §7.3 sends every non-zero
delta to G4. `gate="G4"` therefore said nothing about whether the sum missed by four paise or
by ₹198, so `Verdict` now carries `tolerance` beside `delta_paise`: `applied`,
`over_rupee_cap`, or `over_per_txn_cap`, and `None` when G4 was never consulted. One
classification produces both the label and the reason, so they cannot disagree.

With the split, the 860 read:

```
  over_rupee_cap        860      |delta| > Rs 1.00
  over_per_txn_cap        0      within Rs 1.00, more than a paise per transaction
  applied                 3      admitted, counted separately (Sec 8.3)

  by magnitude:  <= Rs 100   4      <= Rs 10,000  136      > Rs 10,000  720
```

**Not one rejection was within ₹1.00 of closing.** G4 is the sole gate that can admit a wrong
answer, and on this data it is nowhere near the decision boundary — 720 of the 860 miss by more
than ₹10,000, which is a whole missing transaction, not a rounding artefact. Widening the band
would buy no recall and would spend the one gate whose bad policy produces a false match. The
three tolerance matches are `ROUNDING_DRIFT` and nothing else.

---

## The composed finding

Stage 4 ended on "identifier recovery has to carry the load, and search is a small-pool
fallback." Stage 6 measures the load, and the answer changes what Phase A is *for*.

**An identifier is not an amount.** Phase A recovered a settlement id on **93 of 134 lines**
and closed **44**. The 49-line gap is not parse failure — on every line where a fragment
resolved and truth records a composition, the true settlement was among the candidates, zero
wrong anchors. The gap is that **a payout is a settlement group plus whatever cross-cycle
items it nets**, and 70 such strays exist by baseline generation (stage 4). A settlement's own
total is the bank credit only when the payout happened to net nothing extra.

```
  A1 recovered an identifier      81 lines
     closed                       40
     cited a real settlement
     whose total is not the
     payout total                 41   ->  26 of them net 1-2 cross-cycle strays
                                          13 are unresolvable lines (correct refusals)
                                           2 are SETTLEMENT_CONTAMINATION
```

So Phase A's product is an **anchor**, not a composition. Its value is realised by C1's
anchored residual search in stage 8 — seed the known settlement, search only the residual —
which is precisely the tier stage 4 argued was the primary search path. The two findings
compose: *search cannot scale without an anchor, and an anchor cannot close a line without
search.* Neither phase is a fallback for the other; the recall number needs both, and
stage 7's baseline will read low for a reason that is now measured rather than guessed.

The 70 open lines partition cleanly, which is the useful part:

| open lines | why | lands in |
|---|---|---|
| 42 | resolvable, composition nets 1–2 cross-cycle strays | C1, stage 8 |
| 21 | `resolvable: false` — withheld records, ambiguous sets, duplicate credits | correct refusals, already true negatives |
| 4 | `SPLIT_PAYOUT` halves | C3, stage 13 |
| 3 | `SETTLEMENT_CONTAMINATION` — composition spans two settlements | C1 with a stray from another group |

### §9.5's cascade was already built, except the prefix

The spec describes four filters: prefix, date window, exclusivity, arithmetic. Only the first
is new code. The window and exclusivity are **G1**, the arithmetic is **G2**, and "2+
survivors" is **G5** — the same machinery a tied subset-sum uses, which is what §9.5 means by
"no new machinery". A tier that filtered on its own arithmetic would be a second, unaudited
copy of the gate chain, and I8 says tiers select while gates approve.

What that produces is deliberately wasteful and measured as such:

```
  A3 fired on 12 lines
    prefix candidates per line     median 123 of 123 settlements, min 2
    dropped by G1 as already claimed          448
    dropped by G2/G4 as not balancing         ~800
    closed                                      4
```

A five-character truncation like `NHDFC2` is a prefix of the entire book, because a UTR is
`N` + bank code + yymmdd + sequence and every settlement here is one bank on consecutive days.
§9.5 predicted "filter 3 does most of the work". On this dataset it does most of the **volume**
and none of the **deciding**: on all four closures the last surviving distinction was
arithmetic, not exclusivity. Exclusivity resolving a collision on its own needs two settlements
with the *same total* sharing a prefix, and seed 42 never presents one to a bank line — so
`test_exclusivity_is_what_resolves_a_prefix_collision` builds it by hand.

### B1's ambiguity is in the data and never fires

Finding 8.4 is the case where two unclaimed settlements share a total, and v1.2 would never
have seen it because ambiguity handling lived only in the search phase. Seed 42 **does** carry
one such bucket:

```
  B1 index: 122 buckets over 123 settlements
    49900 -> {setl_0020, setl_0108}       <- ₹499.00, the sticky price of stage 4
```

and **no bank line has a target of ₹499.00**, so the pair is never proposed and G5 never fires
at B1. That is worth stating rather than reporting "0 refusals" and moving on: the tier's
uniqueness guarantee has no evidence from this seed. Two tests cover it instead — one asserting
the duplicate bucket exists in the index, one building a bank line that asks for it and
asserting the refusal.

**Both tests stay permanently**, including the constructed one, and including the assertion
that seed 42's bucket exists. The ambiguity rate is a property of the modelled merchant (stage
4), so a later seed can present this case to a real bank line at any time — the path should be
proven before that happens rather than discovered by it.

---

## Files

### `matcher/proposers/regex_p.py` — §9.1, §9.5

One class, three tiers, chosen by `tier` at construction, because tier-major ordering (§9.8)
runs every line through A1 before any line reaches A2. Settlement membership is derived from
the gateway export — `settlement_id` and `settlement_utr` are columns — so nothing in
`matcher/` imports `generator/`.

A1 takes a fragment that equals a UTR exactly, in `ref_no` or the narration. A3 takes what is
left and prefix-matches it, **skipping any fragment A1 already resolved exactly**: re-proposing
a set the gates just rejected cannot produce a different answer.

The fragment pattern is `N?[A-Z]{2,6}\d{2,}`, which covers the leading-`N` form and the
UPI template's tail form (`UPI/CR/HDFC26011500042/…` drops the N). It also matches the
`HDFC0000060` IFSC sitting in the NEFT template — a decoy token that is a prefix of nothing and
dies in the cascade.

*Questionable:* **A2 matches zero lines on this dataset.** No narration template writes a
`setl_*` token, so the tier is dead weight against generated data and a reviewer could call it
unexercised code. It stays because §9.6's `direct_link` detective claim returns a
`settlement_id` to Phase A, and A2 is the tier that consumes one. It is tested against a
hand-built narration rather than the dataset, and the test says so.

**A measured deletion.** An earlier version retried an unmatched full-length fragment at eight
characters, to recover UTRs whose transposed digits (§3.4) fall late in the string. It changed
the total by nothing — 64 lines closed either way, one line moving from B1 to A3 — so it is
gone. A recovery path that only reshuffles which tier gets the credit is complexity with a
measurement against it.

### `matcher/proposers/lookup_p.py` — §9.2

B1 builds `total_paise -> {settlement_id}` once, plus `settlement_id -> total`, which is what
makes `release()` an O(1) dictionary hit rather than a scan over the index. Nothing rebuilds
per pass (§9.2, and the §18 ruling).

Settlements whose members net to **zero are excluded from the index** (§5.1): no payout is ever
produced for them, so they are not candidates for anything. Without that they would sit in the
`0` bucket waiting for a zero-target line.

B2 reads the signed target (finding 8.1) and proposes any single pool transaction whose net
equals it, so a chargeback posted as a bank debit needs no separate path — the four
`DISPUTE_DEBIT` lines close there on targets of −₹996.53, −₹244.75, −₹2,495.00 and −₹5,003.60.

*Questionable:* **B1 emits both candidates for a duplicate-total bucket and lets G5 refuse
them.** The tier could detect the collision itself and emit nothing. Emitting both is right:
the refusal then carries the same shape a tied subset-sum produces, one place decides
ambiguity for every tier, and a tier that silently withholds candidates is a tier that can hide
a match. The cost is that the orchestrator sees two claims where one line exists.

### `tests/test_phase_ab.py` — §9.1, §9.2, §9.5

Fourteen tests. Six pin the seed-42 measurements above, including a bare
`test_not_one_of_them_is_wrong` comparing every closed composition to truth by set equality —
scoring proper is stage 7, but a false match is the severe failure and it should not wait a
stage to be checked. The rest are hand-built: the B1 duplicate-total refusal, the prefix
collision cut by exclusivity, incremental index removal, a single negative net at B2, and a
grep asserting the string `Verdict` appears nowhere under `matcher/proposers/`.

*Questionable:* **the tier-major ladder lives in the test file.** It is 30 lines and stage 9
owns the real one — ordering by pool size, two propagation passes, a run-level deadline. Two
drivers will exist until then, and the test's one is deliberately dumb: single pass, lines in
`bank_line_id` order, no deadline. Every number in this file is from that driver, so any of
them can move when the real ordering lands.

---

## Deviated from the spec

**§9.5's filter 4 is not in the cascade.** "Drop those whose total does not close" is the gate
chain's job. The tier emits one claim per prefix-surviving settlement and G2 does the closing
test, which keeps I8 literal — no tier returns a match without a balanced proof, and no tier
runs arithmetic the gates do not audit. Outcomes are unchanged: 1 survivor is a match, 0 is a
fall-through, 2+ is a G5 refusal.

**Anchored claims carry `window_days=0`.** Every entity a Phase A or B1 claim cites belongs to
the anchor settlement, and G1 exempts those from the window test (§9.3, stage 5). Passing 2
would assert a window that is never consulted. B2's claims carry the real window, because a
lone transaction has no anchor and G1 does apply it.

**G3 is unexercised, not working.** It fired exactly once in the run — a B2 single that was a
member of a multi-item settlement, refused as a partial slice — and one firing is not coverage.
Phase A and B1 propose whole settlement groups **by construction**, so nothing incoherent is
reachable from those tiers; the coherence prior has had nothing to prove itself against. C2 in
stage 8 is the first tier that proposes arbitrary subsets, and it is the first real test of
§9.4.

`tests/test_gates.py::test_g3_rejects_a_composition_spanning_three_partial_settlements` builds
the case by hand: one slice from each of three settlements, summing to the bank credit exactly,
rejected on shape with `delta_paise == 0`. The path is proven before the tier that needs it
exists. Read the run's "G3 1" as *not yet measured*, not as *passing*.

## Deferred

**The 42 stray lines are C1's, not a Phase A failure.** Every one has a recovered anchor and a
composition of "this settlement plus one or two cross-cycle items". Stage 8's anchored residual
search is what closes them, and the recall number before it exists should be read as a
baseline, not a result.

**`window_pool` still lives in `generator/uniqueness.py`.** The test driver imports it from
there, which is the wrong direction for `matcher/` to depend. It is pure domain logic over
`BankLine` and `GatewayTxn` and belongs in `core/` — the move is stage 9's, when `run.py`
becomes the second caller. Leaving one definition in the wrong place beats two definitions.

**No propagation pass.** §9.8 runs the ladder twice because resolving one line shrinks every
other pool. The driver runs it once. Nothing on seed 42 is known to need the second pass at
these tiers — B1 and A-tier claims do not depend on pool size — but that is an argument for
measuring it in stage 9, not for assuming it.

**The B1 index goes stale when a partial settlement is consumed.** `release()` is called when
an anchored claim wins. If C1 later takes some members of a settlement as strays for another
line, the settlement stays in its bucket with a total it can no longer reach. G1 rejects the
resulting claim on the spent entity, so the failure is a wasted candidate rather than a wrong
match — but stage 8 should either release on any entity consumption or accept the waste
deliberately.

**`DUPLICATE_CREDIT` still has no rule.** Stage 4 flagged it: the T+1 reversal pair (equal
magnitude, opposite sign, adjacent day, similar narration) is a matcher rule and nothing
implements it. Both halves are `resolvable: false` in truth, so they currently score as correct
refusals — which flatters the number, and will keep flattering it until the rule lands.

---

## Amended after the fact

Three changes made after the stage was first written, none of them new behaviour:

1. **`Verdict.tolerance`** splits G2's residual from G4's verdict on it, so a rejection says
   both what the sum missed by and whether tolerance was close. The measured answer on seed 42
   — never close — is in the finding above. `matcher/uniqueness.py`'s G5 refusal sets it to
   `None`: G4's outcome belongs to a claim and that refusal belongs to a set.
2. **G3 recorded as unexercised** rather than working, with a hand-built three-settlement
   rejection in `tests/test_gates.py`.
3. **`docs/spec.md` §9.1 amended** with the anchors-not-compositions measurement, and with the
   consequence for stage 12: Pass A's recall lands as C1 closures under a deterministic tier,
   so the ablation delta is a floor on Pass A's value rather than a measure of it. Anchors
   recovered has to be reported next to lines closed or the model looks less useful than it is.
