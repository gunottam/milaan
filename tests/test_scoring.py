"""Scoring against truth. §11.

The four outcomes are hand-built, because a scorer measured only against a run it
agrees with is a scorer nobody has checked. The seed-42 cases at the bottom pin the
stage-7 baseline.
"""

from __future__ import annotations

from collections import Counter

import pytest

from core.models import BANK_COLUMNS, BankLine, GatewayTxn, read_csv
from generator.config import UNIQUENESS_NODE_BUDGET_OFFLINE
from generator.generate import emit
from matcher.run import Run, build_tiers, run_ladder
from scoring.score import (BUCKETS, anchors_recovered, bucket, budget_banner,
                           outcome, phase_e, precision, recall, render, score)


RESOLVABLE = {"resolvable": True, "uniqueness": "verified", "injected_breaks": [],
              "composition": ["pay_1", "pay_2"], "expected_delta_paise": 0}
UNRESOLVABLE = {"resolvable": False, "composition": None,
                "injected_breaks": ["WITHHELD_RECORD"]}


def truth_of(**lines) -> dict:
    return {"seed": 42,
            "config": {"bank_lines": len(lines), "records": 0, "noise": "high",
                       "window_days": 2,
                       "uniqueness_node_budget": UNIQUENESS_NODE_BUDGET_OFFLINE},
            "bank_lines": lines, "break_manifest": {}, "emergent_breaks": {}}


# --- the four outcomes -------------------------------------------------------


def test_tp_is_set_equality_and_nothing_less():
    """I5. Order is not part of a composition; membership is."""
    assert outcome(RESOLVABLE, ("pay_2", "pay_1")) == "TP"


def test_fp_when_the_composition_differs_by_one_element():
    """No partial credit. Twenty-eight right and one wrong is a false match, and a
    false match books wrong silently — the severe failure of §1."""
    assert outcome(RESOLVABLE, ("pay_1", "pay_3")) == "FP"
    assert outcome(RESOLVABLE, ("pay_1",)) == "FP"
    assert outcome(RESOLVABLE, ("pay_1", "pay_2", "pay_3")) == "FP"


def test_fn_when_a_resolvable_line_produced_an_exception():
    assert outcome(RESOLVABLE, None) == "FN"


def test_tn_when_an_unresolvable_line_was_refused():
    assert outcome(UNRESOLVABLE, None) == "TN"


def test_fp_when_an_unresolvable_line_was_matched():
    """§11: a fabricated match. Weighted visibly — it is the only way an
    unresolvable line can score anything but TN."""
    assert outcome(UNRESOLVABLE, ("pay_1",)) == "FP"


def test_exceeded_budget_and_uniqueness_unproven_both_score_fn():
    """§11, stated explicitly because both look like near-misses and neither is.
    Both are states in which no composition was approved, so both reach `outcome`
    as `None` and need no special case: an answer whose uniqueness was never
    established is not a match."""
    for exception_type in ("EXCEEDED_SEARCH_BUDGET", "UNIQUENESS_UNPROVEN"):
        record = {**RESOLVABLE, "injected_breaks": [exception_type]}
        assert outcome(record, None) == "FN"


def test_precision_and_recall_are_none_on_an_empty_denominator():
    assert precision(Counter()) is None and recall(Counter()) is None
    assert precision(Counter({"TP": 3, "FP": 1})) == 0.75
    assert recall(Counter({"TP": 3, "FN": 1})) == 0.75


# --- the buckets -------------------------------------------------------------


def test_every_line_lands_in_exactly_one_named_bucket():
    cases = {
        "headline": RESOLVABLE,
        "unproven": {**RESOLVABLE, "uniqueness": "unproven"},
        "by_construction_c3": {**RESOLVABLE, "uniqueness": "by_construction",
                               "requires_tier": "C3"},
        "by_construction_single": {**RESOLVABLE, "uniqueness": "by_construction"},
        "emergent": {**UNRESOLVABLE, "injected_breaks": ["AMBIGUOUS_SUBSET"]},
        "excluded": {**RESOLVABLE, "excluded_from_scoring": True},
    }
    assert {name: bucket(rec) for name, rec in cases.items()} == \
        {name: name for name in cases}
    assert set(cases) == set(BUCKETS)


def test_a_refused_unresolvable_line_is_a_headline_true_negative():
    """Refusing a withheld record is the headline's only source of TN, and it is
    what keeps precision honest: without it, precision would be measured over
    resolvable lines alone and a fabricated match would cost nothing."""
    report = score(truth_of(bl_1=UNRESOLVABLE), {})
    assert report.counts("headline") == Counter({"TN": 1})


def test_an_excluded_line_leaves_every_denominator():
    """§11. The generator no longer emits the flag, so this is the path staying
    proven rather than a measurement."""
    report = score(truth_of(bl_1={**RESOLVABLE, "excluded_from_scoring": True}), {})
    assert report.counts() == Counter()
    assert report.lines("excluded") == ["bl_1"]


def test_the_disclosed_buckets_are_scored_and_not_dropped():
    """Held out of the headline, still counted by name — nothing is silently
    excluded, which is the whole reason the buckets exist."""
    report = score(truth_of(
        bl_1={**RESOLVABLE, "uniqueness": "unproven"},
        bl_2={**RESOLVABLE, "uniqueness": "by_construction", "requires_tier": "C3"},
    ), {"bl_1": ("pay_1", "pay_2")})
    assert report.counts("headline") == Counter()
    assert report.counts("unproven") == Counter({"TP": 1})
    assert report.counts("by_construction_c3") == Counter({"FN": 1})


# --- the two manifests -------------------------------------------------------


def test_break_manifest_caught_and_missed_are_filled_per_line():
    truth = truth_of(
        bl_1={**RESOLVABLE, "injected_breaks": ["TIMING_SHIFT"]},
        bl_2={**RESOLVABLE, "injected_breaks": ["TIMING_SHIFT"]},
        bl_3={**UNRESOLVABLE, "injected_breaks": ["TIMING_SHIFT"]},
    )
    truth["break_manifest"] = {"TIMING_SHIFT": {"injected": 2, "caught": None,
                                               "missed": None}}
    report = score(truth, {"bl_1": ("pay_1", "pay_2")})
    # Two injections, three lines: `injected` counts injections and is untouched.
    # bl_1 matched (TP) and bl_3 was correctly refused (TN) — both caught.
    assert report.break_manifest["TIMING_SHIFT"] == {
        "injected": 2, "lines": 3, "caught": 2, "missed": 1,
        "caught_by_match": 1, "caught_by_refusal": 1,
        "scored_by_refusal": False, "no_bank_line": False}


def test_a_break_caught_only_by_refusing_is_flagged():
    """The metric a missing rule can win. §3.2's reversal-pair detection does not
    exist, truth marks both halves of a DUPLICATE_CREDIT unresolvable, and refusing
    them scores exactly as well as detecting them would. The flag is what stops
    stage 14's regression table showing greens for code nobody wrote."""
    truth = truth_of(bl_1=UNRESOLVABLE, bl_2=UNRESOLVABLE)
    truth["break_manifest"] = {"DUPLICATE_CREDIT": {"injected": 1}}
    for rec in truth["bank_lines"].values():
        rec["injected_breaks"] = ["DUPLICATE_CREDIT"]
    entry = score(truth, {}).break_manifest["DUPLICATE_CREDIT"]
    assert entry["caught"] == 2 and entry["caught_by_match"] == 0
    assert entry["scored_by_refusal"] is True

    # One composed match is enough to stop being refusal-only.
    truth["bank_lines"]["bl_2"] = {**RESOLVABLE,
                                   "injected_breaks": ["DUPLICATE_CREDIT"]}
    entry = score(truth, {"bl_2": ("pay_1", "pay_2")}).break_manifest["DUPLICATE_CREDIT"]
    assert entry["caught_by_match"] == 1 and entry["scored_by_refusal"] is False


def test_a_break_with_no_bank_line_is_flagged_rather_than_scored_zero():
    """§5.1: a net-zero settlement produces no payout and therefore no bank line,
    ever. Nothing to catch and nothing to miss — 0 of 0 is not 0% recall."""
    truth = truth_of(bl_1=RESOLVABLE)
    truth["break_manifest"] = {"NET_ZERO_SETTLEMENT": {"injected": 2}}
    entry = score(truth, {}).break_manifest["NET_ZERO_SETTLEMENT"]
    assert entry == {"injected": 2, "lines": 0, "caught": 0, "missed": 0,
                     "caught_by_match": 0, "caught_by_refusal": 0,
                     "scored_by_refusal": False, "no_bank_line": True}


def test_emergent_breaks_split_refused_from_matched():
    truth = truth_of(
        bl_1={**UNRESOLVABLE, "injected_breaks": ["AMBIGUOUS_SUBSET"]},
        bl_2={**UNRESOLVABLE, "injected_breaks": ["AMBIGUOUS_SUBSET"]},
    )
    truth["emergent_breaks"] = {"AMBIGUOUS_SUBSET": {"count": 2, "refused": None,
                                                     "matched": None}}
    report = score(truth, {"bl_2": ("pay_9",)})
    assert report.emergent_breaks["AMBIGUOUS_SUBSET"] == {
        "count": 2, "refused": 1, "matched": 1}
    # A match on an ambiguous line is a fabricated one, and it costs precision.
    assert report.counts("emergent") == Counter({"TN": 1, "FP": 1})


# --- anchors recovered, §9.1's amendment -------------------------------------


def test_anchors_are_reported_beside_closures_and_a_wrong_one_is_named():
    trace = [{"line": "bl_1", "tier": "A1", "won": True, "anchors": ["setl_a"]},
             {"line": "bl_2", "tier": "A3", "won": False,
              "anchors": ["setl_a", "setl_b"]},
             {"line": "bl_3", "tier": "A1", "won": False, "anchors": ["setl_z"]},
             {"line": "bl_4", "tier": "A1", "won": False, "anchors": ["setl_a"]},
             {"line": "bl_5", "tier": "B1", "won": True, "anchors": ["setl_b"]}]
    truth = truth_of(bl_1=RESOLVABLE, bl_2=RESOLVABLE, bl_3=RESOLVABLE,
                     bl_4=UNRESOLVABLE, bl_5=RESOLVABLE)
    got = anchors_recovered(trace, truth, {"pay_1": "setl_a", "pay_2": "setl_a"})
    assert got["recovered"] == 4          # B1 is amount lookup, not identifier
    assert got["true_anchor_present"] == 2
    assert got["wrong"] == 1              # bl_3 cited a settlement that is not its own
    assert got["no_true_anchor"] == 1     # bl_4 has no composition to be right about


# --- the node budget is part of the run's identity ---------------------------


def test_a_truth_file_at_the_offline_budget_says_so_quietly():
    assert budget_banner(truth_of()) == \
        [f"  uniqueness verified at {UNIQUENESS_NODE_BUDGET_OFFLINE:,} nodes  "
         "(the offline budget — comparable)"]


def test_a_truth_file_at_any_other_budget_says_so_loudly():
    """§10.1: the budget decides whether the uniqueness guarantee holds, so it
    decides how many lines truth calls `verified` rather than `unproven`. The CSVs
    and the matcher are identical across the boundary and the buckets are not —
    which makes a budget change look exactly like a regression."""
    truth = truth_of()
    truth["config"]["uniqueness_node_budget"] = 2_000_000
    banner = budget_banner(truth)
    assert "2,000,000" in banner[0]
    assert banner[1].startswith("  !! NOT the 40,000,000 offline budget")


def test_a_truth_file_with_no_budget_recorded_is_comparable_with_nothing():
    truth = truth_of()
    del truth["config"]["uniqueness_node_budget"]
    assert budget_banner(truth)[0].startswith("  !! truth records no node budget")


# --- seed 42 -----------------------------------------------------------------


@pytest.fixture(scope="module")
def baseline(seed42):
    # 2M, not the 40M offline budget: at 2M more lines read `unproven` and fewer
    # read `AMBIGUOUS_SUBSET`, so the bucket sizes here are smaller than the
    # committed run's. The CSVs are the same bytes and the matcher sees no
    # difference — only truth's confidence about them changes.
    data, truth = seed42
    # Pinned, not incidental: every bucket size below is a function of it, and the
    # scoreboard's committed run uses the 40M offline budget. `budget_banner` is
    # what says so at the top of the board.
    assert truth["config"]["uniqueness_node_budget"] == 2_000_000
    # A1..B2 only. Phase C is stage 8's; this fixture is stage 7's measurement and
    # stays that way, so a change to C moves `test_phase_c.py` and not this file.
    r = run_ladder(data.txns, data.bank_lines,
                   tiers=build_tiers(data.txns)[:5], deadline_ms=None)
    compositions = {b: c.composition for b, (_, c, _) in r.matched.items()}
    return data, truth, r.matched, r.trace, score(truth, compositions)


def test_the_buckets_partition_every_bank_line(baseline):
    data, truth, _, _, report = baseline
    assert len(report.buckets) == len(data.bank_lines) == 134
    assert set(report.outcomes) == set(truth["bank_lines"])
    assert sum(report.counts(b).total() for b in BUCKETS) == 134


def test_phase_a_and_b_fabricate_nothing(baseline):
    """Precision is the number that must not move. Every closure on this seed is
    set-equal to truth, in every bucket — including the 16 ambiguous lines, where a
    match would be an answer to a question truth says has two."""
    _, _, matched, _, report = baseline
    assert Counter(report.outcomes.values())["FP"] == 0
    assert precision(report.counts("headline")) == 1.0
    assert sum(report.counts(b)["TP"] for b in BUCKETS) == len(matched) == 64


def test_the_baseline_recall(baseline):
    """The stage-7 number, Phase A and B only. 42 of the open lines have a
    recovered anchor and a composition that nets one or two cross-cycle strays —
    C1's, and `test_phase_c.py` is where that is scored."""
    _, _, _, _, report = baseline
    head = report.counts("headline")
    assert head == Counter({"TP": 54, "FN": 34, "TN": 13})
    assert recall(head) == pytest.approx(0.6136, abs=1e-4)


def test_split_payout_halves_score_fn_until_c3(baseline):
    """Stage 4's ruling: truth describes the data, not the matcher's reach. These
    six flip to TP in stage 13 with no change to the truth file."""
    _, _, _, _, report = baseline
    assert report.counts("by_construction_c3") == Counter({"FN": 6})


def test_g5_refused_every_ambiguous_line(baseline):
    _, _, _, _, report = baseline
    amb = report.emergent_breaks["AMBIGUOUS_SUBSET"]
    assert amb["matched"] == 0 and amb["refused"] == amb["count"]


def test_no_anchor_is_wrong_on_seed_42(baseline):
    """§9.1's amendment: wherever a fragment resolved, the true settlement was among
    the candidates. The gap between 101 recovered and 64 closed is not parsing.

    **`wrong == 0` is the load-bearing half and it is stage 11's revert condition.**
    Widening `FRAGMENT_RX` hands the cascade far more candidates; the experiment was
    to be reverted on a single wrong anchor. There is none — filters 2-4 of §9.5 are
    G1 and G2, and neither is weakened by being offered more to reject.
    """
    data, truth, _, trace, _ = baseline
    got = anchors_recovered(trace, truth,
                            {t.entity_id: t.settlement_id for t in data.txns})
    assert got["recovered"] == 101 and got["wrong"] == 0


def test_the_scoreboard_renders(baseline):
    data, truth, matched, trace, report = baseline
    anchors = anchors_recovered(trace, truth,
                                {t.entity_id: t.settlement_id for t in data.txns})
    at_risk = {l.bank_line_id: abs(l.credit_paise - l.debit_paise)
               for l in data.bank_lines}
    ladder = Run(matched, list(trace), passes_run=2)
    residue, ledger = phase_e(list(data.txns), list(data.bank_lines),
                              list(data.orders), ladder)
    text = render(report, truth, ladder,
                  anchors, at_risk, "data/runs/seed42", residue, ledger)
    assert "precision" in text and "AMBIGUOUS_SUBSET" in text
    assert "anchors recovered 101" in text


def test_the_csvs_read_back_into_the_types_that_wrote_them(tmp_path, baseline):
    """Scoring reads the emitted artifacts rather than regenerating, so the round
    trip is load-bearing: a column parsed to the wrong type is a silently different
    dataset."""
    data, truth, _, _, _ = baseline
    emit(tmp_path, data, truth)
    assert read_csv(tmp_path / "gateway_txns.csv", GatewayTxn) == list(data.txns)
    assert read_csv(tmp_path / "bank_statement.csv", BankLine) == list(data.bank_lines)
    assert BANK_COLUMNS[0] == "bank_line_id"
