"""Phase E, the delta diagnostics and the exception ledger. §9.7, §10, §10.2.

**The strongest assertion in the suite is `test_the_residue_gap_equals_the_withheld_net`.**
Everywhere else the tests check that a rule does what it says. That one checks
something different: a global sum over two populations, computed with no reference
to any individual line's analysis, independently derives the exact size of a hole
that the per-line analysis could only describe. If Phase E were wrong in any of the
four partition arms the number would not land, and it lands to the paisa.

It is asserted twice on purpose — once on a dataset carrying exactly one
`WITHHELD_RECORD` and no other break, where the arithmetic is unambiguous, and once
on the committed seed-42 board with all fifteen injectors live, where every other
break has to contribute exactly zero for the figure to survive. The second is the
real claim; the first is what tells you which half is broken when it fails.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.models import BankLine, GatewayTxn, Order, read_csv
from generator.breaks import BREAK_COUNTS
from generator.generate import generate
from matcher import ledger as exception_ledger
from core.subsetsum import TOLERANCE_PAISE
from matcher.audit import coherence_audit, no_payout_settlements, residue_gap
from matcher.diagnose import UNDIAGNOSED, diagnose
from matcher.run import run_ladder

STAMP = "2026-08-24T15:30:00+05:30"
SEED42 = Path("data/runs/seed42")

# Small and fast: the isolation test needs a board, not a big one. The uniqueness
# budget is the oracle's, and it only has to be large enough that this dataset's
# lines classify — nothing here reads `uniqueness`.
ISOLATED = dict(seed=7, payouts=40, records=1000, noise="high", window_days=2)


def _txn(entity_id: str, kind: str, amount: int, **kw) -> GatewayTxn:
    return GatewayTxn(entity_id=entity_id, type=kind, amount_paise=amount,
                      settled_at="2026-01-04T18:30:00+05:30", **kw)


def _line(bank_line_id: str, credit: int = 0, debit: int = 0,
          date: str = "2026-01-04", narration: str = "") -> BankLine:
    return BankLine(bank_line_id, date, date, narration, None, debit, credit, 0)


# --- E1, the residue gap -----------------------------------------------------


@pytest.fixture(scope="module")
def isolated():
    """`(dataset, the withheld transaction)` — one `WITHHELD_RECORD`, nothing else.

    The withheld record is found by diffing against the same dataset generated with
    no breaks at all. `build()` is deterministic in the seed, so the two share a
    base and the difference is exactly what the injector deleted — which is the only
    way to learn a record's net after it has been removed from every export.
    """
    clean, _ = generate(**ISOLATED, generated_at=STAMP, budget=500_000, breaks=False)
    data, truth = generate(**ISOLATED, generated_at=STAMP, budget=500_000,
                           break_counts={**{code: 0 for code in BREAK_COUNTS},
                                         "WITHHELD_RECORD": 1})
    gone = {t.entity_id for t in clean.txns} - {t.entity_id for t in data.txns}
    assert len(gone) == 1, "the isolation is the test; more than one deletion voids it"
    withheld = next(t for t in clean.txns if t.entity_id in gone)
    return data, truth, withheld


def _gap(txns, bank_lines, **kw):
    ladder = run_ladder(list(txns), list(bank_lines), 2, deadline_ms=None)
    compositions = {b: c.composition for b, (_, c, _) in ladder.matched.items()}
    claimed = [e for composition in compositions.values() for e in composition]
    return residue_gap(list(txns), list(bank_lines), compositions, claimed, **kw), ladder


def test_the_residue_gap_equals_the_withheld_net(isolated):
    """The acceptance criterion, in one assertion.

    A record is deleted from the gateway export and from the orders file. Its bank
    line still credits the full amount, so the settlement's remaining members total
    the credit *less that record's net*. E1 never looks at that settlement, never
    parses that narration and never runs a tier — it subtracts one global sum from
    another — and the difference is the deleted record's net contribution exactly.
    """
    data, _, withheld = isolated
    residue, _ = _gap(data.txns, data.bank_lines)
    assert residue.gap_paise == withheld.net
    assert residue.reconciles is False


@pytest.mark.slow
def test_the_gap_survives_every_other_break_on_the_committed_board():
    """Same claim, all fifteen injectors live.

    Marked `slow` by hand rather than by the fixture hook: it reads the committed
    CSVs directly and runs its own uncapped ladder, so there is no fixture for
    `conftest.pytest_collection_modifyitems` to key on. The weaker half of this
    claim still runs in the default sweep, on the isolated dataset above.

    Four `WITHHELD_RECORD`s are injected into seed 42 and truth records each one's
    shortfall in its `unresolvable_reason`. Every other open line on the board —
    the ambiguous ones, the split payouts, the duplicate credits and their
    reversals, the timing shifts — must contribute exactly zero to the gap, because
    an open line whose transactions are also unclaimed cancels on both sides. That
    it lands on the sum of the four is the check that the partition has no leak.
    """
    truth = json.loads((SEED42 / "truth.json").read_text(encoding="utf-8"))
    expected = sum(
        int(re.search(r"is short by (-?\d+) paise", rec["unresolvable_reason"]).group(1))
        for rec in truth["bank_lines"].values()
        if "WITHHELD_RECORD" in rec["injected_breaks"])

    txns = read_csv(SEED42 / "gateway_txns.csv", GatewayTxn)
    bank_lines = read_csv(SEED42 / "bank_statement.csv", BankLine)
    residue, _ = _gap(txns, bank_lines)
    assert residue.gap_paise == expected


def test_not_yet_due_transactions_are_not_in_the_denominator():
    """Finding 8.8's first exclusion. `settled = false` is not missing money.

    Counting it would make the gap permanently non-zero — a standing discrepancy no
    reconciliation could close — and a number that is always wrong gets ignored,
    which is the same as not computing it.
    """
    txns = [_txn("pay_1", "payment", 10_000),
            _txn("pay_2", "payment", 5_000, settled=False)]
    residue, _ = _gap(txns, [_line("bl_1", credit=10_000)])
    assert residue.census["not_yet_due"] == 1
    assert residue.gap_paise == 0


def test_a_net_zero_settlement_is_not_in_the_denominator():
    """Finding 8.8's second exclusion, and §5.1.

    A settlement netting to zero produces no payout and therefore no bank line,
    ever. Its members sit unclaimed forever; counting them corrupts the residue with
    a discrepancy that does not exist.
    """
    txns = [_txn("pay_1", "payment", 10_000, settlement_id="setl_a"),
            _txn("pay_2", "payment", 7_000, settlement_id="setl_z"),
            _txn("rfnd_1", "refund", 7_000, settlement_id="setl_z")]
    assert no_payout_settlements(txns) == {"setl_z": 0}
    residue, _ = _gap(txns, [_line("bl_1", credit=10_000)])
    assert residue.census["no_payout_expected"] == 2
    assert residue.gap_paise == 0


def test_phase_e_runs_on_partial_results(isolated):
    """§9.10, and the thing stage 9 deferred because `audit.py` did not exist.

    A one-millisecond deadline stops the ladder almost immediately. Phase E must
    still produce a full four-way partition rather than raising or being skipped.
    """
    data, _, _ = isolated
    ladder = run_ladder(list(data.txns), list(data.bank_lines), 2, deadline_ms=1)
    assert ladder.deadline_hit
    residue = residue_gap(list(data.txns), list(data.bank_lines), {}, [],
                          partial=True, cut_lines=[b.bank_line_id
                                                   for b in data.bank_lines])
    assert sum(residue.census.values()) == len(data.txns)
    assert any("open bank lines" in line for line in residue.lines())


def test_closing_a_line_moves_the_gap_by_that_line_s_delta_and_nothing_else(isolated):
    """The identity stage 11 found, and the reason a deadline-cut run is not
    indeterminate.

    Closing `L` removes `target(L)` from the open sum and `Σ net(C)` from the
    unclaimed sum, so the gap moves by exactly `Σ net(C) − target(L)` — the line's
    own delta. An exact match therefore moves it by **zero**, which means the figure
    is already final before the first tier runs and an unfinished line can only
    change it by whatever G4 would have absorbed.

    Stage 10 marked any deadline-cut run `reconciles = None` on the opposite
    assumption. That threw away a bound we can compute.
    """
    data, _, _ = isolated
    txns, bank_lines = list(data.txns), list(data.bank_lines)
    untouched = residue_gap(txns, bank_lines, {}, [])

    for deadline in (None, 2_000):
        ladder = run_ladder(txns, bank_lines, 2, deadline_ms=deadline)
        compositions = {b: c.composition for b, (_, c, _) in ladder.matched.items()}
        claimed = [e for c in compositions.values() for e in c]
        after = residue_gap(txns, bank_lines, compositions, claimed)
        deltas = sum(v.delta_paise for _, _, v in ladder.matched.values())
        assert after.gap_paise == untouched.gap_paise + deltas
        assert after.matcher_delta_paise == deltas
        assert after.baseline_gap_paise == untouched.gap_paise


def test_the_deadline_band_is_a_rupee_a_line_not_the_lines_targets(isolated):
    """§8.2 caps what one match may absorb at ₹1.00, so five cut lines put ₹5.00 of
    uncertainty on the gap — not the ₹1.75 lakh their targets total.

    `reconciles` is `None` only when that band actually swallows the gap.
    """
    data, _, _ = isolated
    txns, bank_lines = list(data.txns), list(data.bank_lines)
    cut = [b.bank_line_id for b in bank_lines[:3]]
    residue = residue_gap(txns, bank_lines, {}, [], partial=True, cut_lines=cut)
    assert residue.deadline_slack_paise == 3 * TOLERANCE_PAISE
    assert abs(residue.gap_paise) > residue.deadline_slack_paise
    assert residue.reconciles is False, "a gap past the band is a hole, clock or not"

    # A gap the band could account for is the one case that stays indeterminate.
    tiny = residue_gap([_txn("pay_1", "payment", 10_000)],
                       [_line("bl_1", credit=10_050)], {}, [],
                       partial=True, cut_lines=["bl_1"])
    assert tiny.gap_paise == 50 and tiny.reconciles is None


# --- E2, the coherence audit -------------------------------------------------


def test_a_settlement_split_across_two_lines_is_flagged():
    txns = {t.entity_id: t for t in
            [_txn("pay_1", "payment", 10_000, settlement_id="setl_a"),
             _txn("pay_2", "payment", 20_000, settlement_id="setl_a")]}
    splits = coherence_audit({"bl_1": ("pay_1",), "bl_2": ("pay_2",)}, txns)
    assert [s.settlement_id for s in splits] == ["setl_a"]
    assert splits[0].bank_line_ids == ("bl_1", "bl_2")


def test_a_line_drawing_from_a_second_group_flags_the_minority():
    """G3 accepts a whole settlement plus a stray from another group (§9.4). The
    audit's job is to say it happened — the *minority* group is the contamination,
    because a payout is one whole settlement and the odd item is the extra."""
    txns = {t.entity_id: t for t in
            [_txn("pay_1", "payment", 10_000, settlement_id="setl_a"),
             _txn("pay_2", "payment", 10_000, settlement_id="setl_a"),
             _txn("pay_3", "payment", 500, settlement_id="setl_b")]}
    splits = coherence_audit({"bl_1": ("pay_1", "pay_2", "pay_3")}, txns)
    assert [(s.settlement_id, s.kind) for s in splits] == [
        ("setl_b", "line_spans_settlements")]


# --- §10.2, the six delta diagnostics ---------------------------------------


def test_tds_and_gst_terms_are_named_from_the_transactions():
    txns = {t.entity_id: t for t in
            [_txn("pay_1", "payment", 100_000, method="card",
                  fee_paise=2000, tax_paise=360, tds_paise=100)]}
    assert diagnose(100, ("pay_1",), txns).code == "tds_term_missing"
    assert diagnose(-360, ("pay_1",), txns).code == "gst_not_applied"


def test_the_instant_premium_is_named_flat_and_with_gst():
    txns = {t.entity_id: t for t in [_txn("pay_1", "payment", 100_000)]}
    for delta in (2500, -2500, 2950):
        assert diagnose(delta, ("pay_1",), txns).code == "instant_settlement_premium"


def test_the_allocation_remainder_is_named():
    """§4.3's dropped remainder — bounded by n − 1 **and backed by an allocation.**

    Stage 17 added the second condition. `|delta| <= n` on its own is not a
    diagnosis, it is a restatement of §8.2's per-transaction cap, so a check that
    fired on it answered yes to every claim G4 was about to admit — and G4 asking
    for "a named cause" would then have admitted exactly the same set. §4.3's
    remainder exists only where a flat premium was split by integer division, and
    that leaves a signature in the fees: 2,499 paise of a 2,500 charge, the last
    one dropped.
    """
    txns = {f"pay_{i}": _txn(f"pay_{i}", "payment", 999, fee_paise=833)
            for i in range(3)}
    assert diagnose(3, tuple(txns), txns).code == "allocation_remainder"


def test_a_small_residual_with_no_allocation_behind_it_is_not_named():
    """The other half, and the one that stops G4 absorbing a missing record: the
    same three-paise gap over the same three payments, no premium allocated, and
    the honest answer is that nothing in the input accounts for it."""
    txns = {f"pay_{i}": _txn(f"pay_{i}", "payment", 999) for i in range(3)}
    assert diagnose(3, tuple(txns), txns).code == "no_matching_residual"


def test_an_unclaimed_net_is_named_as_a_candidate_never_as_the_answer():
    """§17: two withheld transactions summing to the same figure are
    indistinguishable, so check five names a candidate and says so."""
    txns = {t.entity_id: t for t in [_txn("pay_1", "payment", 100_000)]}
    spare = _txn("rfnd_9", "refund", 4_242)
    found = diagnose(-4_242, (), txns | {"rfnd_9": spare}, [spare])
    assert found.code == "likely_specific_missing_record"
    assert found.candidate_entity_id == "rfnd_9"
    assert "not a proof" in found.detail


def test_the_fx_markup_is_named_from_the_difference_the_flag_makes():
    """§10.2's "3% − 2% of gross". The markup folds into `fee_paise` (I7), so it is
    recomputed as the difference `international` makes rather than read off."""
    txn = _txn("pay_1", "payment", 100_000, method="intl_card", international=True)
    assert diagnose(1000, ("pay_1",), {"pay_1": txn}).code == "fx_markup_not_applied"


def test_an_unexplained_residual_says_so():
    """§10's own example value. Not looking and finding nothing are different, and
    the ledger must be able to tell a human which one happened."""
    txns = {t.entity_id: t for t in [_txn("pay_1", "payment", 100_000)]}
    assert diagnose(777_777, ("pay_1",), txns).code == UNDIAGNOSED


# --- §10, the exception ledger ----------------------------------------------


@pytest.fixture(scope="module")
def board():
    """The committed seed-42 ledger, built once."""
    txns = read_csv(SEED42 / "gateway_txns.csv", GatewayTxn)
    bank_lines = read_csv(SEED42 / "bank_statement.csv", BankLine)
    orders = read_csv(SEED42 / "orders.csv", Order)
    ladder = run_ladder(txns, bank_lines, 2, deadline_ms=None)
    compositions = {b: c.composition for b, (_, c, _) in ladder.matched.items()}
    splits = coherence_audit(compositions, {t.entity_id: t for t in txns})
    return exception_ledger.build(txns, bank_lines, orders, matched=compositions,
                                  trace=ladder.trace, exceeded=ladder.exceeded,
                                  splits=splits), bank_lines


def test_every_open_line_gets_exactly_one_exception(board):
    ledger, bank_lines = board
    closed = {e.bank_line_id for e in ledger.exceptions if e.bank_line_id}
    on_lines = [e for e in ledger.exceptions if e.bank_line_id]
    assert len(on_lines) == len(closed), "a line must not be typed twice"


def test_blocked_on_names_the_missing_input(board):
    """§10, verbatim: `blocked_on` must name the missing input in one sentence.
    "Could not match" is not acceptable output."""
    ledger, _ = board
    for exc in ledger.exceptions:
        assert exc.blocked_on.endswith(".") and len(exc.blocked_on.split()) >= 6
        assert "could not match" not in exc.blocked_on.lower()
        assert exc.proposed_action["kind"] and exc.proposed_action["detail"]


def test_every_exception_is_typed_priced_and_aged(board):
    ledger, _ = board
    kinds = {"WITHHELD_RECORD", "AMBIGUOUS_EQUIVALENT", "AMBIGUOUS_CONSEQUENTIAL",
             "UNIQUENESS_UNPROVEN", "EXCEEDED_SEARCH_BUDGET", "DUPLICATE_CREDIT",
             "SETTLEMENT_CONTAMINATION", "ORPHAN_ORDER", "SPLIT_PAYOUT"}
    for exc in ledger.exceptions:
        assert exc.exception_type in kinds
        assert exc.type_confidence in ("high", "medium", "low")
        assert exc.amount_at_risk_paise >= 0 and isinstance(exc.amount_at_risk_paise, int)
        assert exc.age_days >= 0 and exc.age_bucket
        assert exc.evidence


def test_the_ambiguity_split_is_derived_not_read(board):
    """§10.1. The ledger has no access to truth, so `AMBIGUOUS_EQUIVALENT` comes
    from comparing the tied compositions' own book shapes — and it agrees with the
    `ambiguity_class` the generator's oracle stamped by the same rule."""
    ledger, _ = board
    truth = json.loads((SEED42 / "truth.json").read_text(encoding="utf-8"))
    typed = {e.bank_line_id: e.exception_type for e in ledger.exceptions}
    checked = 0
    for bid, rec in truth["bank_lines"].items():
        want = rec.get("ambiguity_class")
        if want is None or not typed.get(bid, "").startswith("AMBIGUOUS_"):
            continue
        assert typed[bid] == f"AMBIGUOUS_{want.upper()}", bid
        checked += 1
    assert checked >= 12, "the split is only meaningful if it ran on real ties"


def test_uniqueness_unproven_is_its_own_state(board):
    """§10.1. One answer found, budget expired before a second could be ruled out —
    a different state from a match and from having found nothing."""
    ledger, _ = board
    rows = ledger.by_type().get("UNIQUENESS_UNPROVEN", [])
    assert rows, "G5's other refusal must be reachable on this board"
    assert all("ruled out" in " ".join(r.evidence) or "ruled out" in r.blocked_on
               for r in rows)


def test_deadline_cut_exceptions_disclose_that_the_type_moves_with_the_hardware():
    """Exception typing is scored and the live run carries a wall clock (§11), so a
    row the deadline produced has to say it might not survive a faster box — and it
    must not be able to claim `high` confidence for a fact about this machine."""
    txns = [_txn("pay_1", "payment", 10_000)]
    bank_lines = [_line("bl_1", credit=99_999)]
    ledger = exception_ledger.build(txns, bank_lines, [], matched={}, trace=[],
                                    exceeded=["bl_1"], deadline_hit=True)
    exc = ledger.exceptions[0]
    assert exc.exception_type == "EXCEEDED_SEARCH_BUDGET"
    assert exc.type_confidence == "low"
    assert any("faster hardware" in token for token in exc.evidence)


def _ambiguous_board():
    """One credit two compositions balance against, plus one orphan order.

    `pay_2` and `pay_3` are the same type, method, amount and settlement date, so
    they have the same book shape and swapping them changes no figure. `rfnd_1` is
    a refund of the same magnitude — it balances the same credit and books
    differently, which is the whole EQUIVALENT / CONSEQUENTIAL split (§10.1).
    """
    txns = [_txn("pay_1", "payment", 60_000, settlement_id="setl_1"),
            _txn("pay_2", "payment", 40_000, settlement_id="setl_1"),
            _txn("pay_3", "payment", 40_000, settlement_id="setl_1"),
            _txn("rfnd_1", "refund", 40_000, settlement_id="setl_1")]
    lines = [_line("bl_1", credit=100_000)]
    orders = [Order("ord_9001", "2026-01-02", "cust_1", 9_900, "INR", "paid", None)]
    return txns, lines, orders


def _tied_trace(bank_line_id: str, alternatives: list[list[str]]) -> list[dict]:
    """One C1 trace row reporting a G5 tie — the shape `run_ladder` writes when
    `resolve` refuses because two approved claims sat at the same |delta|."""
    return [{"line": bank_line_id, "tier": "C1", "pass": 1, "pool": 4,
             "candidates": len(alternatives), "won": False, "stale": 0,
             "refused": True, "anchors": [], "unproven": None,
             "tied": alternatives, "census": None}]


def test_an_equivalent_ambiguity_is_typed_low_and_a_consequential_one_high():
    """The badge has to distinguish them or it carries no information.

    Both are "two compositions balance and G5 refused", and they are not equally
    well evidenced. `CONSEQUENTIAL` is existential — one differing pair proves the
    alternatives book differently — and the counterexample is in hand.
    `EQUIVALENT` is universal, and it is established over whatever the search
    stopped at: `solve_exact` takes two, because two is already a refusal. On
    `bl_0048` the census counts 279 compositions that balance and the shape
    comparison saw two of them.
    """
    txns, lines, orders = _ambiguous_board()
    trace = _tied_trace("bl_1", [["pay_1", "pay_2"], ["pay_1", "pay_3"]])
    # By bank line, not by position: §10.2 sorts the ledger and the orphan outranks
    # this row.
    equivalent = next(e for e in exception_ledger.build(
        txns, lines, orders, matched={}, trace=trace).exceptions
        if e.bank_line_id == "bl_1")
    assert equivalent.exception_type == "AMBIGUOUS_EQUIVALENT"
    assert equivalent.type_confidence == "low"
    assert any("the search stopped at" in e for e in equivalent.evidence), \
        "the row must say why it is low, not just be low"

    # Same shape of refusal, one alternative swapped for a refund — different book
    # shape, so the typing flips and the counterexample is in hand.
    trace = _tied_trace("bl_1", [["pay_1", "pay_2"], ["pay_1", "rfnd_1"]])
    consequential = next(e for e in exception_ledger.build(
        txns, lines, orders, matched={}, trace=trace).exceptions
        if e.bank_line_id == "bl_1")
    assert consequential.exception_type == "AMBIGUOUS_CONSEQUENTIAL"
    assert consequential.type_confidence == "high"


def test_an_orphan_order_carries_the_order_id_it_is_about():
    """`bank_line_id` is `None` for this type and correctly so — the break is that
    the bank statement has nothing. But §13 renders an identifier column, and a dash
    there reads as missing data rather than as not-applicable. The order id is what
    a human goes and looks up."""
    txns, lines, orders = _ambiguous_board()
    ledger = exception_ledger.build(txns, lines, orders, matched={}, trace=[])
    orphan = next(e for e in ledger.exceptions
                  if e.exception_type == "ORPHAN_ORDER")
    assert orphan.bank_line_id is None
    assert orphan.order_id == "ord_9001"
    assert orphan.as_dict()["order_id"] == "ord_9001"
    # And the CLI board prints it in the same column §13 does.
    assert any("ord_9001" in row for row in exception_ledger.render(ledger))


def test_a_reversal_pair_is_typed_duplicate_credit_not_a_missing_record():
    """§3.2. Equal magnitude, opposite sign, adjacent calendar day. The balance
    column cannot detect it — a duplicate posting is a real posting."""
    txns = [_txn("pay_1", "payment", 10_000)]
    lines = [_line("bl_1", credit=50_000, date="2026-01-04"),
             _line("bl_2", debit=50_000, date="2026-01-05")]
    ledger = exception_ledger.build(txns, lines, [], matched={}, trace=[])
    assert {e.exception_type for e in ledger.exceptions
            if e.bank_line_id in ("bl_1", "bl_2")} == {"DUPLICATE_CREDIT"}


def test_the_orders_tie_out_finds_a_paid_order_with_no_payment():
    """§3.3. One query, and the only break neither the bank statement nor the
    gateway ledger can see on its own."""
    orders = [Order("order_1", "2026-01-02", "cust_1", 9_900, "INR", "paid", None),
              Order("order_2", "2026-01-02", "cust_2", 9_900, "INR", "cancelled", None)]
    ledger = exception_ledger.build([_txn("pay_1", "payment", 10_000)],
                                    [_line("bl_1", credit=10_000)], orders,
                                    matched={"bl_1": ("pay_1",)}, trace=[])
    orphans = ledger.by_type()["ORPHAN_ORDER"]
    assert [e.bank_line_id for e in orphans] == [None]
    assert "order_1" in orphans[0].blocked_on


def test_the_sort_is_the_one_ten_point_two_asks_for(board):
    """`WITHHELD_RECORD` and `AMBIGUOUS_CONSEQUENTIAL` first by amount descending;
    `AMBIGUOUS_EQUIVALENT` and `SPLIT_PAYOUT` last, because both are documentation
    tasks — the money is accounted for and what is missing is a note in a file."""
    ledger, _ = board
    tiers = [0 if e.exception_type in ("WITHHELD_RECORD", "AMBIGUOUS_CONSEQUENTIAL")
             else 2 if e.exception_type in ("AMBIGUOUS_EQUIVALENT", "SPLIT_PAYOUT")
             else 1
             for e in ledger.exceptions]
    assert tiers == sorted(tiers)
    first = [e.amount_at_risk_paise for e, t in zip(ledger.exceptions, tiers) if t == 0]
    assert first == sorted(first, reverse=True)


def test_the_ledger_is_reproducible_across_two_builds(board):
    """§11: nothing machine-dependent on the board. Ageing is measured from the
    statement's own last value date, so two builds of one dataset render one text."""
    ledger, _ = board
    txns = read_csv(SEED42 / "gateway_txns.csv", GatewayTxn)
    bank_lines = read_csv(SEED42 / "bank_statement.csv", BankLine)
    orders = read_csv(SEED42 / "orders.csv", Order)
    ladder = run_ladder(txns, bank_lines, 2, deadline_ms=None)
    compositions = {b: c.composition for b, (_, c, _) in ladder.matched.items()}
    splits = coherence_audit(compositions, {t.entity_id: t for t in txns})
    again = exception_ledger.build(txns, bank_lines, orders, matched=compositions,
                                   trace=ladder.trace, exceeded=ladder.exceeded,
                                   splits=splits)
    assert exception_ledger.render(again) == exception_ledger.render(ledger)


# --- the risk split, §13's OPEN ITEMS column ---------------------------------


def test_a_reversal_pair_is_documentation_not_money_at_risk():
    """Stage 10 typed the pairs correctly and then priced them as risk.

    Both halves of a contra are open bank lines, so both are listed, and summing
    their face amounts counted ₹1,25,737.50 twice for a pair that nets to zero by
    construction (§3.2). On seed 42 that put ₹5,13,970.88 of phantom exposure in a
    headline meant to say what the books cannot account for.
    """
    txns = [_txn("pay_1", "payment", 10_000)]
    lines = [_line("bl_1", credit=50_000, date="2026-01-04"),
             _line("bl_2", debit=50_000, date="2026-01-05")]
    ledger = exception_ledger.build(txns, lines, [], matched={}, trace=[])
    rows = ledger.by_type()["DUPLICATE_CREDIT"]

    assert {r.risk_class for r in rows} == {"documentation"}
    assert ledger.at_risk_paise == 0, "a posting and its contra is not exposure"
    assert ledger.documentation_paise == 100_000, "both open lines are still listed"
    assert ledger.nets_to_zero_paise == 50_000, "and half of that cancels"
    # Each row names its partner: one half alone reads as an unexplained credit.
    assert {r.bank_line_id: r.reverses for r in rows} == {"bl_1": "bl_2", "bl_2": "bl_1"}


def test_the_risk_split_covers_every_type_and_defaults_to_at_risk(board):
    """A new exception type is money until somebody argues otherwise. Only the
    three with a stated reason are documentation."""
    ledger, _ = board
    for exc in ledger.exceptions:
        assert exc.risk_class == exception_ledger.risk_class(exc.exception_type)
    docs = {e.exception_type for e in ledger.exceptions
            if e.risk_class == "documentation"}
    assert docs <= set(exception_ledger.DOCUMENTATION)
    assert ledger.at_risk_paise + ledger.documentation_paise == sum(
        e.amount_at_risk_paise for e in ledger.exceptions)


def test_a_contaminated_line_is_documentation_because_it_balanced(board):
    """§9.4: the line is closed with a zero delta. The flag asks a human to confirm
    a tagging; the amount is what a repair would move, not what is unaccounted for."""
    ledger, _ = board
    rows = ledger.by_type().get("SETTLEMENT_CONTAMINATION", [])
    assert rows and all(r.risk_class == "documentation" for r in rows)
