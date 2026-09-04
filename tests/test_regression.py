"""The ten-seed harness: the arithmetic and the table, not the board.

Nothing here runs a ladder. The figures `regression.json` holds are measured by
`offline()` and pinned per seed in the slow set; what this module checks is the
part a reader trusts without being able to re-derive it — the mean, the σ, the
range, the false-match claim, and whether the table prints what the file says.

**Population σ, not sample σ.** The ten seeds are the whole harness, not a draw
from a larger population we are inferring about, so `pstdev` is right and `stdev`
would report a figure ~5% larger for no reason anybody could defend.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scoring.regression import (SCORING_RULE, aggregate, dataset, render,
                                spread)


def row(seed: int, *, recall: float, headline: float = 1.0, fp: int = 0,
        ambiguity: float = 0.08, closed: int = 100,
        withheld: tuple[str, ...] = ()) -> dict:
    """One offline row, cut down to the fields the aggregation reads."""
    return {
        "seed": seed, "bank_lines": 134, "closed": closed,
        "all_lines": {"recall": recall, "precision": 1.0 if not fp else 0.9,
                      "counts": {"TP": closed, "FP": fp, "FN": 5, "TN": 29}},
        "headline": {"recall": headline, "precision": 1.0,
                     "counts": {"TP": 88, "TN": 13}},
        "ambiguity": {"lines": int(ambiguity * 134), "of": 134, "rate": ambiguity},
        "split_refusals": [],
        # Stage 15's pre-match exclusion. `withheld` is the *cost*: lines it kept
        # from every tier that truth says had a composition.
        "excluded": {"lines": [f"bl_900{i}" for i in range(4, 10)], "pairs": 3,
                     "withheld_resolvable": list(withheld)},
    }


def test_spread_is_mean_population_sigma_and_range():
    figure = spread([0.90, 0.94, 0.98])
    assert figure["mean"] == pytest.approx(0.94)
    # pstdev, not stdev: 0.0327 against 0.04.
    assert figure["sigma"] == pytest.approx(0.03265986, abs=1e-6)
    assert (figure["min"], figure["max"], figure["n"]) == (0.90, 0.98, 3)


def test_spread_of_one_seed_is_zero_not_undefined():
    """`stdev` raises on a single value. A one-seed run is a legitimate thing to
    ask for — `--seeds 42` while iterating — and it must render."""
    assert spread([0.95]) == {"mean": 0.95, "sigma": 0.0, "min": 0.95,
                             "max": 0.95, "n": 1}


def test_a_missing_figure_is_dropped_rather_than_counted_as_zero():
    """`recall` is `None` when a bucket has no TP and no FN, and averaging that in
    as 0.0 would report a collapse that did not happen."""
    assert spread([0.9, None, 0.7])["n"] == 2
    assert spread([None, None])["mean"] is None


def test_the_spread_is_reported_because_the_mean_hides_it():
    """Stage 4's five seeds ran 4.5% to 11.9% on the ambiguity rate. A mean of 8%
    describes none of those boards, which is why the range travels with it."""
    summary = aggregate([row(1, recall=0.95, ambiguity=0.045),
                         row(2, recall=0.95, ambiguity=0.119)])
    rate = summary["ambiguity_rate"]
    assert rate["mean"] == pytest.approx(0.082)
    assert (rate["min"], rate["max"]) == (0.045, 0.119)
    assert rate["sigma"] > 0.03


def test_one_false_match_anywhere_breaks_the_claim():
    """§1: a missed match costs minutes, a false match puts the books wrong
    silently. So the claim is per-seed and boolean, never a mean — 100% on nine
    seeds and 96% on one averages to something that reads fine."""
    clean = aggregate([row(1, recall=0.95), row(2, recall=0.93)])
    assert clean["false_matches"] == {"per_seed": {1: 0, 2: 0}, "total": 0,
                                     "clean_on_every_seed": True}
    dirty = aggregate([row(1, recall=0.95), row(2, recall=0.93, fp=1)])
    assert dirty["false_matches"]["total"] == 1
    assert dirty["false_matches"]["clean_on_every_seed"] is False


def test_the_live_clock_is_summarised_only_when_it_was_measured():
    """Offline rows carry no wall clock at all (§11), so `--no-live` must not
    invent one."""
    assert "live_total_s" not in aggregate([row(1, recall=0.95)])
    timed = aggregate([row(1, recall=0.95)], [{"seed": 1, "total_s": 31.4}])
    assert timed["live_total_s"]["mean"] == pytest.approx(31.4)


# --- the table ---------------------------------------------------------------


def harness(**live) -> dict:
    return {"seeds": [42], "scoring_rule": SCORING_RULE,
            "offline": {"deadline_ms": None, "uniqueness_node_budget": 40_000_000,
                        "detective": False, "note": ""},
            "live": {"deadline_ms": 22_000, "uniqueness_node_budget": 5_000_000,
                     "detective": True, "ceiling_s": 60, "note": "", **live}}


def rendered(rows, live_rows=()) -> str:
    return "\n".join(render({"harness": harness(), "seeds": rows,
                             "live": list(live_rows),
                             "summary": aggregate(rows, live_rows)}))


def test_the_table_carries_every_figure_with_its_spread():
    text = rendered([row(1, recall=0.95, ambiguity=0.045),
                     row(2, recall=0.93, ambiguity=0.119)])
    for label in ("all-lines recall", "headline recall", "precision",
                  "ambiguity rate"):
        assert label in text
    assert "mean ± σ" in text
    assert text.count("range") >= 4
    # The node budget is part of the run's identity (§10.1) and the table says it,
    # so two tables at different budgets cannot be read as one series.
    assert "40,000,000 nodes" in text
    assert "no wall clock" in text


def test_the_table_says_which_scoring_rule_produced_the_numbers():
    """Stage 14 nearly changed it. A regression file that does not name its rule is
    a series with a discontinuity nobody can see."""
    text = rendered([row(1, recall=0.95)])
    assert "per-line composition set equality (I5)" in text


def test_a_breached_ceiling_is_named_not_averaged():
    """§15's ceiling is 60 s and the mean can sit under it while a seed sails past.
    The seed is what a judge would have run."""
    rows = [row(1, recall=0.95), row(2, recall=0.95)]
    live = [{"seed": 1, "total_s": 30.0}, {"seed": 2, "total_s": 71.0}]
    text = rendered(rows, live)
    assert "BREACHED on 1 of 2 seeds: seed 2 at 71.0s" in text
    text_clean = rendered(rows, [{"seed": 1, "total_s": 30.0},
                                 {"seed": 2, "total_s": 40.0}])
    assert "BREACHED" not in text_clean


def test_the_refusals_are_on_the_table_with_their_reason():
    """Stage 14 reports these *instead of* the recall point pair scoring would have
    bought, so the reason has to be legible on the page rather than in a ledger
    somebody opens afterwards."""
    refused = row(1, recall=0.95)
    refused["split_refusals"] = [{
        "bank_line_id": "bl_0048", "settlement_id": "setl_0048",
        "amount_paise": 4_445_390,
        "reason": "setl_0048 ties to this credit and bl_9003 jointly to the paisa, "
                  "but 279 divisions of the payout balance against this credit, and "
                  "the statement does not say which of them this credit carried",
        "blocked_on": "A bank advice naming the transactions behind each credit."}]
    text = rendered([refused])
    assert "REFUSED — SPLIT_PAYOUT" in text
    assert "279 divisions" in text and "bl_0048" in text and "setl_0048" in text


# --- stage 15: the exclusion, and the clock it stopped comparing -------------


def test_the_exclusion_reports_a_cost_of_zero_rather_than_reporting_nothing():
    """An exclusion trades recall for correctness by construction, so the trade has
    to be a figure in the file. "We checked and it was zero" and "we did not check"
    produce the same silence otherwise."""
    clean = aggregate([row(1, recall=0.95), row(2, recall=0.93)])["excluded"]
    assert clean["withheld_resolvable_total"] == 0
    assert clean["costs_no_recall_on_any_seed"] is True
    assert clean["lines_per_seed"] == {1: 6, 2: 6}

    costly = aggregate([row(1, recall=0.95),
                        row(2, recall=0.93, withheld=("bl_0106",))])["excluded"]
    assert costly["withheld_resolvable_total"] == 1
    assert costly["costs_no_recall_on_any_seed"] is False


def test_a_withheld_real_payout_is_named_on_the_table_not_averaged():
    """The exclusion's only possible failure. It reads like the false-match line
    because it is the same kind of claim: one seed is enough to break it."""
    text = rendered([row(1, recall=0.95),
                     row(2, recall=0.93, withheld=("bl_0106",))])
    assert "COST RECALL" in text and "seed 2: 1" in text
    clean = rendered([row(1, recall=0.95), row(2, recall=0.93)])
    assert "cost zero recall" in clean and "COST RECALL" not in clean


def test_with_phase_d_off_the_table_does_not_compare_the_run_with_itself():
    """From stage 15 the shipped configuration is Phase D off, and then the ablated
    clock *is* the live clock. Printing "the difference is the model's round trips"
    over a difference of zero is a sentence about nothing."""
    rows = [row(1, recall=0.95)]
    live = [{"seed": 1, "total_s": 21.4, "total_ablated_s": 21.4}]
    off = "\n".join(render({"harness": harness(detective=False), "seeds": rows,
                            "live": live, "summary": aggregate(rows, live)}))
    assert "round trips" not in off
    assert "use_llm: false" in off and "zero extra lines" in off
    assert "one run" in off, "it has to say why the two columns agree"
    # And the refusal block still renders under the shorter exit.
    refused = row(1, recall=0.95)
    refused["split_refusals"] = [{"bank_line_id": "bl_0048",
                                  "settlement_id": "setl_0048",
                                  "amount_paise": 1, "reason": "279 divisions",
                                  "blocked_on": "A bank advice."}]
    both = "\n".join(render({"harness": harness(detective=False),
                             "seeds": [refused], "live": live,
                             "summary": aggregate([refused], live)}))
    assert "REFUSED — SPLIT_PAYOUT" in both


def test_the_committed_board_is_the_seed_42_row():
    """Seed 42 reads `data/runs/seed42` rather than a regenerated copy.

    Generation is deterministic, so a copy would hold the same bytes — but the row
    a reader checks first is the one the slow set pins, and pointing at that
    directory is the only thing that stops the two drifting.
    """
    assert dataset(42).as_posix() == "data/runs/seed42"


def test_the_shipped_regression_file_matches_the_harness_that_wrote_it():
    """`regression.json` is committed, so it can go stale in a way no other number
    here can. If it is present it must still render, and it must name the ten seeds
    and the offline budget the harness runs at."""
    path = Path("regression.json")
    if not path.is_file():
        pytest.skip("no regression.json — run python -m scoring.regression")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["seeds"]) == len(data["harness"]["seeds"]) == 10
    assert data["harness"]["offline"]["deadline_ms"] is None
    assert all(r["uniqueness_node_budget"] == 40_000_000 for r in data["seeds"])
    assert "mean ± σ" in "\n".join(render(data))
    # Stage 15's two claims, on the committed file rather than on a fixture. These
    # are the numbers that go on a slide, so a stale file must fail rather than
    # render.
    assert data["summary"]["false_matches"]["clean_on_every_seed"] is True
    assert data["summary"]["excluded"]["costs_no_recall_on_any_seed"] is True
