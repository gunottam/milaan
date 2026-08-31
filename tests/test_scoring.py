"""Scoring against truth. §11.

The four outcomes are hand-built, because a scorer measured only against a run it
agrees with is a scorer nobody has checked. The seed-42 cases at the bottom pin the
stage-7 baseline.
"""

from __future__ import annotations

from collections import Counter

import pytest

from core.models import BANK_COLUMNS, BankLine, GatewayTxn, read_csv
from generator.generate import emit, generate
from matcher.run import run_ladder
from scoring.score import (BUCKETS, anchors_recovered, bucket, outcome,
                           precision, recall, render, score)

STAMP = "2026-08-24T15:30:00+05:30"

RESOLVABLE = {"resolvable": True, "uniqueness": "verified", "injected_breaks": [],
              "composition": ["pay_1", "pay_2"], "expected_delta_paise": 0}
UNRESOLVABLE = {"resolvable": False, "composition": None,
                "injected_breaks": ["WITHHELD_RECORD"]}


def truth_of(**lines) -> dict:
    return {"seed": 42, "config": {"bank_lines": len(lines), "records": 0,
                                   "noise": "high", "window_days": 2},
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
        "injected": 2, "lines": 3, "caught": 2, "missed": 1}


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


# --- seed 42 -----------------------------------------------------------------


@pytest.fixture(scope="module")
def baseline():
    # 2M, not the 40M offline budget: at 2M more lines read `unproven` and fewer
    # read `AMBIGUOUS_SUBSET`, so the bucket sizes here are smaller than the
    # committed run's. The CSVs are the same bytes and the matcher sees no
    # difference — only truth's confidence about them changes.
    data, truth = generate(42, 120, 3000, "high", 2, STAMP, 2_000_000)
    matched, trace = run_ladder(data.txns, data.bank_lines)
    compositions = {bid: claim.composition for bid, (_, claim, _) in matched.items()}
    return data, truth, matched, trace, score(truth, compositions)


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
    """The stage-7 number, before Phase C exists. 42 of the open lines have a
    recovered anchor and a composition that nets one or two cross-cycle strays —
    C1's, in stage 8."""
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
    the candidates. The gap between 93 recovered and 64 closed is not parsing."""
    data, truth, _, trace, _ = baseline
    got = anchors_recovered(trace, truth,
                            {t.entity_id: t.settlement_id for t in data.txns})
    assert got["recovered"] == 93 and got["wrong"] == 0


def test_the_scoreboard_renders(baseline):
    data, truth, matched, trace, report = baseline
    anchors = anchors_recovered(trace, truth,
                                {t.entity_id: t.settlement_id for t in data.txns})
    at_risk = {l.bank_line_id: abs(l.credit_paise - l.debit_paise)
               for l in data.bank_lines}
    text = render(report, truth, matched, trace, anchors, at_risk, "data/runs/seed42")
    assert "precision" in text and "AMBIGUOUS_SUBSET" in text
    assert "anchors recovered 93" in text


def test_the_csvs_read_back_into_the_types_that_wrote_them(tmp_path, baseline):
    """Scoring reads the emitted artifacts rather than regenerating, so the round
    trip is load-bearing: a column parsed to the wrong type is a silently different
    dataset."""
    data, truth, _, _, _ = baseline
    emit(tmp_path, data, truth)
    assert read_csv(tmp_path / "gateway_txns.csv", GatewayTxn) == list(data.txns)
    assert read_csv(tmp_path / "bank_statement.csv", BankLine) == list(data.bank_lines)
    assert BANK_COLUMNS[0] == "bank_line_id"
