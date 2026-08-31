"""The ladder's ordering, its propagation pass, and its deadline. §9.8, §9.10.

Two things are asserted here that no other file can assert, because they are
properties of the *run* rather than of a tier: that the same seed renders the same
bytes, and that the clock running out produces a partial report instead of a crash
or a hang.

One number is registered as a measurement rather than as a target: **propagation
pass 2 closes nothing on this data.** Measured on seeds 42, 7, 99 and 2026 — not one
line, and not one changed candidate count. That is a fact about the generator's
cycle spacing rather than about §9.8, and the test says which, so a dataset with
overlapping windows would move the number rather than break the file.

Every run here passes `deadline_ms=None` except the two that are about the deadline.
§11: a wall clock makes the result a property of the machine, so the reproducible
mode is node budget only, and that is the mode a pinned count may be asserted in.
"""

from __future__ import annotations

import time

import pytest

from core.models import BankLine, GatewayTxn
from core.subsetsum import DeadlineExceeded, SearchBudgetExceeded, solve_tolerance
from matcher.proposers.search_p import SearchProposer
from matcher.run import PROPAGATION_PASSES, Run, run_ladder
from scoring.score import anchors_recovered, render, score

LADDER = ("A1", "A2", "A3", "B1", "B2", "C1", "C2")


def _board(data, truth, ladder: Run) -> str:
    at_risk = {b.bank_line_id: abs(b.credit_paise - b.debit_paise)
               for b in data.bank_lines}
    report = score(truth, {b: c.composition
                           for b, (_, c, _) in ladder.matched.items()})
    anchors = anchors_recovered(ladder.trace, truth,
                               {t.entity_id: t.settlement_id for t in data.txns})
    return render(report, truth, ladder, anchors, at_risk, "data/runs/seed42")


@pytest.fixture(scope="session")
def twice(seed42):
    """The same dataset through the full ladder, twice, independently."""
    data, truth = seed42
    runs = [run_ladder(data.txns, data.bank_lines, deadline_ms=None)
            for _ in range(2)]
    return data, truth, runs


# --- reproducibility ---------------------------------------------------------


def test_two_runs_on_one_seed_render_the_same_bytes(twice):
    """Stage 9's acceptance condition.

    Assignment is exclusive and greedy (§9.9), so ordering decides outcomes. If any
    step of the ladder had an order that depended on set or dict iteration — the
    pool sort without its `bank_line_id` tie-break, `_anchors` without its `sorted`,
    G5's finalists without a total order — this is the assertion that would catch
    it, and it would catch it intermittently, which is why it compares whole
    rendered boards rather than a count.
    """
    data, truth, (first, second) = twice
    assert _board(data, truth, first) == _board(data, truth, second)
    assert first.matched.keys() == second.matched.keys()
    assert [(s["line"], s["tier"], s["pass"], s["candidates"], s["won"])
            for s in first.trace] == [(s["line"], s["tier"], s["pass"],
                                       s["candidates"], s["won"])
                                      for s in second.trace]


def test_the_elapsed_time_is_not_in_the_report(twice):
    """§11: wall-clock deadlines make results machine-dependent. The one number in
    a run that belongs to the box rather than to the method is kept out of the
    rendered board, which is what lets the assertion above be an equality."""
    data, truth, (first, _) = twice
    assert first.elapsed_ms > 0
    assert str(first.elapsed_ms) not in _board(data, truth, first)


# --- tier-major ordering, §9.8 -----------------------------------------------


def test_every_line_attempts_a_tier_before_any_line_attempts_the_next(twice):
    """Tier-major, not line-major. Under line-major ordering a speculative C2
    search on one line could consume transactions the next line had a hard UTR
    for, and the answer would depend on the sort order of the bank file."""
    _, _, (run, _) = twice
    seen = [(s["pass"], LADDER.index(s["tier"])) for s in run.trace]
    assert seen == sorted(seen), "the trace left ladder order"


def test_within_a_tier_the_most_constrained_line_goes_first(twice):
    """Ascending pool size, then `bank_line_id` (§9.8). A line with a pool of 3 has
    fewer ways to be wrong than one with a pool of 30, and resolving it shrinks the
    others.

    `trace["pool"]` is the size the sort saw — the tier's opening snapshot, not the
    live pool the tier searched, which is smaller for any line issued after a match
    in the same sweep. The ordering claim is about the sort key, so that is the
    number recorded. The trace holds only lines where something happened, so it is a
    subsequence of the issue order, and a subsequence of a sorted sequence is
    sorted.
    """
    _, _, (run, _) = twice
    for pass_no in (1, PROPAGATION_PASSES):
        for tier in LADDER:
            pools = [s["pool"] for s in run.trace
                     if s["tier"] == tier and s["pass"] == pass_no]
            assert pools == sorted(pools), f"{tier} pass {pass_no} left pool order"


def test_the_tie_break_is_bank_line_id(twice):
    """Equal pool sizes are the common case — the generator gives every cycle its
    own window — so the tie-break is what makes the order total, and a total order
    is what makes the byte-identical assertion above possible."""
    _, _, (run, _) = twice
    for tier in LADDER:
        steps = [s for s in run.trace if s["tier"] == tier and s["pass"] == 1]
        for a, b in zip(steps, steps[1:]):
            if a["pool"] == b["pool"]:
                assert a["line"] < b["line"]


# --- propagation, §9.8 -------------------------------------------------------


def test_propagation_pass_two_is_a_replay_on_this_data(twice):
    """**Measured, not assumed: pass 2 closes nothing.**

    §9.8's claim is sound — resolving one line shrinks every other pool, which can
    turn an ambiguous line into a determined one. It does not fire here, and the
    reason is the generator: cycles are spaced `window_days + 1` apart
    (`generator.config.cycle_spacing`), so a line's window pool holds its own cycle
    and nothing else. A claim in one cycle cannot shrink another cycle's pool. The
    ~10% of cycles carrying a second payout (`SHARED_WINDOW_RATE`) are the only
    place propagation *can* bite, and tier-major ordering already collects it inside
    pass 1: both lines are offered the same tier in the same sweep, so the later one
    already sees the earlier one's claims.

    What pass 2 would still catch, and what keeps it in the code: B1's index shrinks
    on claim, so a G5 tie between two equal-total settlements in pass 1 can become
    one candidate in pass 2 with no pool change at all. Seeds 42, 7, 99 and 2026
    never fire it. Stage 14's 10-seed regression is where this either earns its
    4 seconds or gets deleted.
    """
    _, _, (run, _) = twice
    assert run.passes_run == PROPAGATION_PASSES == 2
    assert [s["line"] for s in run.trace if s["won"] and s["pass"] == 2] == []

    first = {(s["line"], s["tier"]): s["candidates"]
             for s in run.trace if s["pass"] == 1}
    second = {(s["line"], s["tier"]): s["candidates"]
              for s in run.trace if s["pass"] == 2}
    assert second, "pass 2 ran no lines at all — the loop is not what is being tested"
    assert all(first[k] == v for k, v in second.items()), \
        "a candidate count moved between the passes; propagation is live, re-measure"


# --- the deadline, §9.10 -----------------------------------------------------


def test_a_tiny_deadline_gives_a_partial_report_not_a_crash(seed42):
    """Stage 9's other acceptance condition, and §9.10's whole point.

    A reconciler that dies on its own timeout has converted a partial answer into
    no answer. What comes back is the lines it proved, the lines it never reached
    named as `EXCEEDED_SEARCH_BUDGET`, and a banner saying so — and scoring runs on
    it unchanged, because a line with no approved composition is an FN whether the
    clock or the data is why (§11).
    """
    data, truth = seed42
    run = run_ladder(data.txns, data.bank_lines, deadline_ms=1)

    assert run.deadline_hit
    assert run.passes_run == 0
    assert len(run.exceeded) == len(data.bank_lines)
    assert set(run.exceeded).isdisjoint(run.matched)
    banner = run.banner()
    assert banner and "deadline reached" in banner[0]
    assert "EXCEEDED_SEARCH_BUDGET" in banner[1]

    # Scoring is not told the clock ran out and does not need to be.
    report = score(truth, {b: c.composition
                           for b, (_, c, _) in run.matched.items()})
    assert report.counts("headline")["FP"] == 0
    assert _board(data, truth, run)      # renders, banner and all


def test_a_completed_run_flies_no_banner(twice):
    _, _, (run, _) = twice
    assert not run.deadline_hit
    assert run.exceeded == ()
    assert run.banner() == []


def test_the_deadline_never_reaches_the_caller(seed42):
    """Never hang, never raise (§9.10). A deadline of zero is the degenerate case:
    no work is issued at all, and the answer is an empty board that says why."""
    data, _ = seed42
    run = run_ladder(data.txns, data.bank_lines, deadline_ms=0)
    assert run.matched == {} and run.deadline_hit
    # `deadline_ms=0` is a real zero-length deadline, not "no deadline" — the CLI
    # maps 0 to None before it gets here, and the two must not be the same thing.
    assert run.deadline_ms == 0


def test_a_cut_line_types_apart_from_a_node_budget_refusal(monkeypatch):
    """§10.1 types the two refusals differently and §9.10 is why.

    A node budget is a property of the problem and reproducible. A deadline is a
    property of the machine and is not — so a line the slice cuts here would read
    `UNIQUENESS_UNPROVEN` on a faster box. Both score FN, and a human triages "give
    it more time" differently from "unprovable at any budget", which is the whole
    reason they are not one string.

    The slice is driven directly rather than by racing a real clock: how many lines
    a 22-second deadline cuts is a property of the machine, and an assertion on it
    would be a flaky test dressed up as a measurement. (On the box that wrote this,
    it was three — `bl_0001`, `bl_0030`, `bl_9001`, the three most expensive
    searches on the board, all three already refusals at stage 8.)
    """
    pool = _pool(22)
    line = BankLine("bl_0001", DAY, DAY, "", None, 0, 100_000, 0)

    cut = SearchProposer("C2", pool)
    cut.deadline_ns = time.monotonic_ns() - 1
    assert cut.propose(line, pool) == []
    assert cut.refusals[line.bank_line_id].startswith("EXCEEDED_SEARCH_BUDGET")

    # Same line, same pool, no clock: the node budget is what stops it, and the
    # refusal says so instead.
    monkeypatch.setattr("matcher.proposers.search_p.SUBSET_NODE_BUDGET", 5_000)
    starved = SearchProposer("C2", pool)
    assert starved.propose(line, pool) == []
    assert starved.refusals[line.bank_line_id].startswith("UNIQUENESS_UNPROVEN")


# --- the solver's half of it --------------------------------------------------


DAY = "2026-01-05"


def _pool(n: int) -> list[GatewayTxn]:
    return [GatewayTxn(entity_id=f"pay_{i:03d}", type="payment",
                       amount_paise=(i + 1) * 1_000, method="upi",
                       settled_at="2026-01-05T18:30:00+05:30")
            for i in range(n)]


def test_an_expired_deadline_stops_the_search():
    """The clock is checked every 4096 nodes, so an already-expired deadline stops
    the tree at 4096 rather than at 2**22. The alternative — checking every node —
    costs more than the node it guards."""
    with pytest.raises(DeadlineExceeded) as exc:
        solve_tolerance(_pool(22), 100_000, 250_000,
                        deadline_ns=time.monotonic_ns() - 1)
    assert exc.value.nodes == 4096


def test_a_deadline_refusal_is_still_a_budget_refusal_to_an_old_handler():
    """Subclass on purpose: the consequence is identical — the tree was not
    exhausted, so uniqueness is unknown — and `generator/uniqueness.py` catches the
    base class. Only the typing differs (§10.1)."""
    assert issubclass(DeadlineExceeded, SearchBudgetExceeded)


def test_no_deadline_means_node_budget_only():
    """The generator's oracle and the regression harness pass `None`, and that is
    what makes their numbers reproducible (§11)."""
    with pytest.raises(SearchBudgetExceeded) as exc:
        solve_tolerance(_pool(22), 100_000, 5_000)
    assert not isinstance(exc.value, DeadlineExceeded)


def test_the_bank_line_type_is_untouched():
    """A guard on the one thing this stage could have been tempted to do: carry the
    deadline on the data. It is a property of the run, not of a line."""
    assert not hasattr(BankLine, "deadline_ns")
