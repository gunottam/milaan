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
from matcher.ledger import reversal_pairs
from matcher.proposers.search_p import SearchProposer
from matcher.run import PROPAGATION_PASSES, Run, run_ladder
from scoring.score import anchors_recovered, phase_e, render, score

LADDER = ("A1", "A2", "A3", "B1", "B2", "C1", "C2", "C3")


def _board(data, truth, ladder: Run) -> str:
    at_risk = {b.bank_line_id: abs(b.credit_paise - b.debit_paise)
               for b in data.bank_lines}
    report = score(truth, {b: c.composition
                           for b, (_, c, _) in ladder.matched.items()})
    anchors = anchors_recovered(ladder.trace, truth,
                               {t.entity_id: t.settlement_id for t in data.txns})
    residue, ledger = phase_e(list(data.txns), list(data.bank_lines),
                              list(data.orders), ladder)
    return render(report, truth, ladder, anchors, at_risk, "data/runs/seed42",
                  residue, ledger)


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

    **Stage 13 ended the byte-for-byte replay.** C3 closes `bl_0101`, and that is
    the first closure on this board to remove a transaction from a *different*
    line's window pool — `bl_0100` shares the cycle, and one transaction lighter
    its C2 search finds two solutions in pass 2 where it found none in pass 1. So
    §9.8's mechanism is demonstrably live on seed 42 now. Its payoff is still
    zero: G5 refuses both solutions and nothing closes. The movement is pinned
    exactly rather than tolerated, because the next one is a finding and not noise.
    """
    _, _, (run, _) = twice
    assert run.passes_run == PROPAGATION_PASSES == 2
    assert [s["line"] for s in run.trace if s["won"] and s["pass"] == 2] == []

    first = {(s["line"], s["tier"]): s["candidates"]
             for s in run.trace if s["pass"] == 1}
    second = {(s["line"], s["tier"]): s["candidates"]
              for s in run.trace if s["pass"] == 2}
    assert second, "pass 2 ran no lines at all — the loop is not what is being tested"
    moved = {k: (first.get(k), v) for k, v in second.items() if first.get(k) != v}
    assert moved == {("bl_0100", "C2"): (0, 2)}, \
        f"a candidate count moved between the passes that stage 13 did not: {moved}"


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
    # Every line the ladder *could* have attempted, and not one more. The six
    # reversal-pair lines are excluded before the first tier opens (stage 15), so
    # they are not lines the clock stopped — calling them `EXCEEDED_SEARCH_BUDGET`
    # would print "deadline reached, 6 lines unattempted" about work that never
    # existed. 134 - 6 = 128.
    assert len(run.excluded) == 6
    assert len(run.exceeded) == len(data.bank_lines) - len(run.excluded)
    assert set(run.exceeded).isdisjoint(run.matched)
    assert set(run.exceeded).isdisjoint(run.excluded)
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


# --- stage 15: §3.2's reversal-pair rule as a pre-match exclusion ------------


def _line(bid: str, day: str, credit: int = 0, debit: int = 0,
          narration: str = "NEFT SETTLEMENT") -> BankLine:
    return BankLine(bank_line_id=bid, txn_date=day, value_date=day,
                    narration=narration, ref_no=None, debit_paise=debit,
                    credit_paise=credit, balance_paise=0)


def _duplicate_board() -> tuple[list[GatewayTxn], list[BankLine]]:
    """One settlement of two payments, and three credits that could compose it.

    `bl_real` is the payout. `bl_dupe` is the bank posting it twice and `bl_rev` is
    the T+1 contra — equal magnitude, opposite sign, adjacent day, which is the
    whole of §3.2's rule. Without the exclusion §9.8's sort decides which of the two
    identical credits gets the settlement, and one of the two answers is wrong.
    """
    txns = [GatewayTxn(entity_id="pay_001", type="payment", amount_paise=600_000,
                       settled_at="2026-01-05T18:30:00+05:30",
                       settlement_id="setl_01", settlement_utr="UTR001"),
            GatewayTxn(entity_id="pay_002", type="payment", amount_paise=400_000,
                       settled_at="2026-01-05T18:30:00+05:30",
                       settlement_id="setl_01", settlement_utr="UTR001")]
    lines = [_line("bl_dupe", "2026-01-05", credit=1_000_000),
             _line("bl_real", "2026-01-05", credit=1_000_000),
             _line("bl_rev", "2026-01-06", debit=1_000_000)]
    return txns, lines


def test_a_reversal_pair_is_never_offered_a_tier():
    """The stage-15 rule, on the smallest board that has the bug.

    Both halves stay open and the *real* payout closes. That second half is the
    point: the transactions the duplicate would have consumed are still there for
    the line that earned them, which is why the exclusion buys recall as well as
    precision.
    """
    txns, lines = _duplicate_board()
    run = run_ladder(txns, lines, 2, deadline_ms=None)

    assert set(run.excluded) == {"bl_dupe", "bl_rev"}
    assert run.excluded["bl_dupe"] == "bl_rev" and run.excluded["bl_rev"] == "bl_dupe"
    assert set(run.matched) == {"bl_real"}
    assert {s["line"] for s in run.trace}.isdisjoint(run.excluded), \
        "no tier may propose on an excluded line, so it leaves no trace row"


def test_an_excluded_line_is_not_a_deadline_casualty():
    """`EXCEEDED_SEARCH_BUDGET` is "the clock stopped this" and it scores as FN with
    a banner saying so (§9.10). An excluded line was never work. Folding the two
    together would put a false sentence in front of a reader."""
    txns, lines = _duplicate_board()
    run = run_ladder(txns, lines, 2, deadline_ms=None)
    assert set(run.exceeded).isdisjoint(run.excluded)
    assert set(run.cut).isdisjoint(run.excluded)
    assert run.exceeded == () and run.banner() == []


def test_the_exclusion_only_ever_removes_candidates():
    """§1's monotonicity, as a property of this rule rather than a claim about it:
    a board with no reversal pair is matched identically with the rule in place, so
    the exclusion cannot create a match or change one."""
    txns, lines = _duplicate_board()
    without_pair = [b for b in lines if b.bank_line_id != "bl_rev"]
    run = run_ladder(txns, without_pair, 2, deadline_ms=None)
    assert run.excluded == {}
    # Two identical credits, nothing to tell them apart, and G5 has no view on it
    # — one of them takes the settlement. That is the pre-stage-15 behaviour and it
    # is *unchanged*: the rule did not fire, so it removed nothing.
    assert len(run.matched) == 1


def test_reversal_pairs_defaults_to_every_line():
    """One implementation, two scopes (§3.2). The default is the pre-match scope."""
    _, lines = _duplicate_board()
    every = reversal_pairs(lines)
    assert every == reversal_pairs(lines, [b.bank_line_id for b in lines])
    # An explicit set is what the ledger hands in, and it restricts.
    assert reversal_pairs(lines, ["bl_dupe", "bl_real"]) == {}


def test_the_ledger_types_exactly_what_the_ladder_excluded(twice):
    """The drift guard the `reversal_pairs` docstring promises.

    `matcher/run.py` calls it over every line, before anything has matched; §10
    calls it over the lines still open, after. The two scopes agree only because an
    excluded line is never matched and so is still open when the ledger looks — and
    "only because" is the kind of reasoning that survives until someone changes one
    of the two call sites. So it is asserted on the 134-line board rather than
    argued in a docstring.
    """
    data, truth, runs = twice
    run = runs[0]
    _, ledger = phase_e(list(data.txns), list(data.bank_lines),
                        list(data.orders), run)
    typed = {e.bank_line_id for e in ledger.exceptions
             if e.exception_type == "DUPLICATE_CREDIT"}
    assert set(run.excluded) == typed
    # Seed 42 injects three pairs, six lines. Pinned, so a generator change that
    # stopped injecting them cannot make this test pass by having nothing to find.
    assert len(typed) == 6
    assert set(run.matched).isdisjoint(run.excluded)


def test_the_excluded_lines_are_the_ones_truth_calls_duplicates(twice):
    """The rule is derived from the statement alone (I3) — this test is the only
    place the two are compared, and it is scoring's side of the fence."""
    data, truth, runs = twice
    injected = {bid for bid, rec in truth["bank_lines"].items()
                if "DUPLICATE_CREDIT" in rec["injected_breaks"]}
    assert set(runs[0].excluded) == injected
