"""Phase C against seed 42, plus the cases the seed does not fire.

§9.3, §9.4. Two numbers here were **registered in `docs/journal/stage-07.md` before
this code existed** and are pinned as predictions, not as observations: C1's reach,
and that C2 refuses far more than it closes. A change that moves either should have
to argue with the prediction rather than quietly re-baseline it.

The ladder is `matcher.run.run_ladder` — single pass, no propagation, no deadline.
Stage 9 owns the real ordering and any number here can move when it lands.
"""

from __future__ import annotations

from collections import Counter

import pytest

from core.models import BankLine, GatewayTxn
from core.subsetsum import C2_MAX_POOL
from matcher.proposers.base import Claim
from matcher.proposers.search_p import SearchProposer
from matcher.run import build_tiers, run_ladder
from matcher.uniqueness import resolve
from matcher.verify import check
from scoring.score import recall, score
from tests.test_invariants import grep

DAY = "2026-01-05"
BEFORE = "2026-01-01"          # outside a 2-day window ending on DAY


def _score(seed42, n_tiers):
    generated, truth = seed42
    r = run_ladder(generated.txns, generated.bank_lines,
                   tiers=build_tiers(generated.txns)[:n_tiers], deadline_ms=None)
    report = score(truth, {b: c.composition for b, (_, c, _) in r.matched.items()})
    return r.matched, r.trace, report


@pytest.fixture(scope="session")
def with_c1(seed42):
    return _score(seed42, 6)


@pytest.fixture(scope="session")
def full(seed42):
    return _score(seed42, 7)


# --- the two registered predictions ------------------------------------------


def test_c1_closes_every_line_that_already_had_an_anchor(with_c1):
    """**Prediction 1**, registered at stage 7: C1 alone takes the headline from
    TP 57 / FN 35 to TP 82 / FN 10 on the committed 40M run — recall 62.0% → 89.1%.

    Stage 7 measured that 25 of the 35 headline misses already carried the anchor
    C1 needs and were missing only the residual search. C1 closed exactly 25.

    **The prediction held and then its input changed.** C1 now closes 28, not 25 —
    not because the residual search improved but because stage 11 widened
    `FRAGMENT_RX` and Phase A hands C1 eight more anchors than it had when the
    prediction was registered. The claim under test was "every line that already
    had an anchor closes", and it still holds; the population of lines that have
    one grew. Re-baselining without saying so would have quietly converted a
    falsifiable prediction into a description of whatever the code does.
    """
    matched, trace, report = with_c1
    assert Counter(s["tier"] for s in trace if s["won"])["C1"] == 28
    head = report.counts("headline")
    assert head == Counter({"TP": 82, "FN": 6, "TN": 13})
    assert recall(head) == pytest.approx(0.9318, abs=1e-4)


def test_c2_refuses_far_more_than_it_closes(full):
    """**Prediction 3**, registered at stage 7: C2 attempts these lines rather than
    declining them by rule — every pool is under `C2_MAX_POOL` — and stage 4's
    pigeonhole finding says the outcome is refusals, not closures.

    It holds, and it holds harder after stage 11 widened Phase A: C2 refuses 21 of
    the 28 lines it reaches a verdict on — 6 to G5, and 15 by declining to search at
    all. **Not one of the 15 was refused by the pool cap** — every one exhausted the
    node budget. Two lines left C2's board entirely because C1 closed them on an
    anchor Phase A could not previously recover, which is the ladder working as
    ordered: a line with an identifier should never reach an unanchored search.
    The pigeonhole bound is real; it bills as cost rather than as a pool count.
    """
    matched, trace, _ = full
    # Pass 1: what C2 does on the board Phase A, B and C1 leave it. The second
    # propagation pass (§9.8) re-offers the same open lines and is measured in
    # `test_propagation_pass_two_closes_nothing_here`, not folded in here.
    steps = [s for s in trace if s["tier"] == "C2" and s["pass"] == 1]
    closed = [s for s in steps if s["won"]]
    declined = [s for s in steps if s["unproven"]]
    assert len(closed) == 7
    assert len(steps) - len(closed) == 21
    assert len(declined) == 15
    assert all("node budget" in s["unproven"] for s in declined)
    assert not any("C2_MAX_POOL" in s["unproven"] for s in declined)


def test_phase_c_fabricates_nothing(full):
    """Precision is the number the design exists to protect, and C2 is the first
    tier in the project that can propose an arbitrary subset — so this is the first
    measurement of it that means anything (stage 7 said so in advance)."""
    matched, _, report = full
    assert Counter(report.outcomes.values())["FP"] == 0
    amb = report.emergent_breaks["AMBIGUOUS_SUBSET"]
    assert amb["matched"] == 0 and amb["refused"] == amb["count"]


def test_the_full_ladder_closes_99_of_134(full):
    """**Zero headline FN at this budget.** The two that survived stages 8-10 were
    `bl_0083` and `bl_0102`, both `TIMING_SHIFT` with a 6-character truncated UTR
    that `FRAGMENT_RX` refused to emit; stage 11 widened it and both close at C1.

    The 8 remaining FN are all in the disclosed buckets, not the headline: 6 are
    `SPLIT_PAYOUT` halves waiting on C3 (stage 13) and 8 sit in `unproven`, whose
    denominator is a property of the 2M fixture budget rather than of the matcher.
    """
    matched, _, report = full
    assert len(matched) == 88 + 7 + 4        # headline TP + unproven TP + B2 singles
    assert report.counts("headline") == Counter({"TP": 88, "TN": 13})


# --- the cases seed 42 does not fire -----------------------------------------


def payment(entity_id: str, amount: int, settlement_id: str | None,
            utr: str | None = None, day: str = DAY) -> GatewayTxn:
    return GatewayTxn(entity_id=entity_id, type="payment", amount_paise=amount,
                      settlement_id=settlement_id, settlement_utr=utr,
                      settled_at=f"{day}T18:30:00+05:30")


def refund(entity_id: str, amount: int, settlement_id: str | None,
           day: str = DAY) -> GatewayTxn:
    return GatewayTxn(entity_id=entity_id, type="refund", amount_paise=amount,
                      settlement_id=settlement_id,
                      settled_at=f"{day}T18:30:00+05:30")


def bank_line(credit: int, narration: str = "", ref_no: str | None = None) -> BankLine:
    return BankLine("bl_0001", DAY, DAY, narration, ref_no, 0, credit, 0)


UTR = "NHDFC26010500001"
# One settlement group, plus a cross-cycle refund never tagged to it. §9.4's second
# row exactly: one complete settlement + one stray.
GROUP = [payment("pay_a1", 6_000, "setl_a", UTR),
         payment("pay_a2", 4_000, "setl_a", UTR)]
STRAY = refund("rfnd_x", 1_500, None)


def _decide(claims, line, txns, claimed=frozenset()):
    return resolve([(c, check(c, line, txns, claimed)) for c in claims])


def test_c1_seeds_the_group_and_searches_only_the_residual():
    """The shape every one of stage 7's 35 misses had: Phase A recovers the
    settlement, the group's own total is ₹15 short of the credit, and the residual
    is one cross-cycle refund."""
    pool = GROUP + [STRAY]
    txns = {t.entity_id: t for t in pool}
    line = bank_line(8_500, ref_no=UTR)

    claims = SearchProposer("C1", pool).propose(line, pool)
    assert len(claims) == 1
    assert claims[0].anchor_settlement_id == "setl_a"
    assert set(claims[0].composition) == {"pay_a1", "pay_a2", "rfnd_x"}

    won, verdict = _decide(claims, line, txns)
    assert verdict.ok and verdict.confidence == "exact" and verdict.delta_paise == 0
    assert won.composition == claims[0].composition


def test_c1_reaches_a_member_the_window_excludes_and_c2_cannot():
    """§9.3's whole reason for the anchor exemption. `pay_a2` was held and settled
    four days before the payout, so it is outside the window and invisible to any
    unanchored search — but membership of `setl_a` is a fact, not an inference, so
    C1 reaches it through G1's exemption."""
    held = payment("pay_a2", 4_000, "setl_a", UTR, day=BEFORE)
    universe = [GROUP[0], held, STRAY]
    txns = {t.entity_id: t for t in universe}
    line = bank_line(8_500, ref_no=UTR)
    in_window = [GROUP[0], STRAY]          # what `window_pool` would hand a tier

    won, verdict = _decide(SearchProposer("C1", universe).propose(line, in_window),
                           line, txns)
    assert verdict.ok and set(won.composition) == {"pay_a1", "pay_a2", "rfnd_x"}

    # C2 sees the same line with only the in-window pool and has nothing to find.
    assert SearchProposer("C2", universe).propose(line, in_window) == []


def test_c1_does_not_re_propose_the_bare_group():
    """A residual of zero is A1's and B1's claim, already through the gate chain.
    Re-proposing a set the gates ruled on changes nothing."""
    txns = GROUP + [STRAY]
    assert SearchProposer("C1", txns).propose(bank_line(10_000, ref_no=UTR), txns) == []


def test_c2_refuses_above_the_pool_cap_without_searching():
    """§9.3's information-theoretic bound. The pool below is one past the cap and
    is full of solutions — a tier that searched would return claims. Returning none
    *and* recording why is what "refuses rather than searches" has to mean."""
    pool = [payment(f"pay_{i:02d}", 100, None) for i in range(C2_MAX_POOL + 1)]
    line = bank_line(200)          # any two of them; G3 allows up to two strays
    c2 = SearchProposer("C2", pool)

    assert c2.propose(line, pool) == []
    reason = c2.refusals["bl_0001"]
    assert reason.startswith("UNIQUENESS_UNPROVEN")
    assert f"pool of {len(pool)} exceeds C2_MAX_POOL" in reason
    # One below the cap and the same tier does search — the cap is what refused.
    assert SearchProposer("C2", pool[:-1]).propose(line, pool[:-1]) != []


def test_g3_filters_c2_inside_the_search():
    """§9.4's third row. Three settlements of two, and a target reachable only by
    taking one slice from each — arithmetic alone would propose it. G3 runs as the
    search's `keep`, so the candidate is never emitted rather than emitted and
    rejected: a candidate G3 refuses must not consume the two-solution cutoff.
    """
    pool = [payment("pay_a1", 100, "setl_a"), payment("pay_a2", 900, "setl_a"),
            payment("pay_b1", 100, "setl_b"), payment("pay_b2", 900, "setl_b"),
            payment("pay_c1", 100, "setl_c"), payment("pay_c2", 900, "setl_c")]
    txns = {t.entity_id: t for t in pool}
    line = bank_line(300)          # only pay_a1 + pay_b1 + pay_c1 sums to it

    assert SearchProposer("C2", pool).propose(line, pool) == []
    # The arithmetic is real; it is the shape that is refused. Proposed by hand,
    # the same composition reaches G3 and is rejected there.
    claim = Claim("bl_0001", ("pay_a1", "pay_b1", "pay_c1"), None, 2)
    verdict = check(claim, line, txns)
    assert not verdict.ok and verdict.gate == "G3"
    assert verdict.delta_paise == 0          # I6: balanced, and still refused


def test_the_tolerance_pass_closes_an_allocation_remainder():
    """§4.3's dropped remainder, the mechanism `ROUNDING_DRIFT` exists to produce.
    Exact search finds nothing; the tolerance pass finds the composition two paise
    short, and G4's double cap admits it because two paise over three transactions
    is one each."""
    pool = [payment("pay_a1", 5_000, "setl_a", UTR),
            payment("pay_a2", 3_000, "setl_a", UTR), refund("rfnd_x", 1_000, None)]
    txns = {t.entity_id: t for t in pool}
    line = bank_line(7_002, ref_no=UTR)

    won, verdict = _decide(SearchProposer("C1", pool).propose(line, pool), line, txns)
    assert set(won.composition) == {"pay_a1", "pay_a2", "rfnd_x"}
    assert verdict.ok and verdict.confidence == "tolerance"
    assert verdict.delta_paise == -2 and verdict.tolerance == "applied"


def test_g5_refuses_a_tolerance_tie():
    """§9.3: a wider band makes ambiguity more likely, so G5 applies to tolerance
    matches identically. Two strays one paise either side of the residual tie at
    |1| and neither is an answer."""
    pool = [payment("pay_a1", 8_000, "setl_a", UTR),
            refund("rfnd_x", 999, None), refund("rfnd_y", 1_001, None)]
    txns = {t.entity_id: t for t in pool}
    line = bank_line(7_000, ref_no=UTR)

    claims = SearchProposer("C1", pool).propose(line, pool)
    assert len(claims) == 2
    won, verdict = _decide(claims, line, txns)
    assert won is None and verdict.gate == "G5"
    assert verdict.delta_paise == 1          # the magnitude they tied at


def test_an_exact_answer_beats_a_tolerance_one_and_the_pass_never_runs():
    """§9.3: the tolerance pass runs only if `solve_exact` returned nothing. Here
    the exact answer and a one-paise near miss both exist; only the exact one is
    proposed, so G5 is never asked to choose between them."""
    pool = [payment("pay_a1", 8_000, "setl_a", UTR),
            refund("rfnd_x", 1_000, None), refund("rfnd_y", 1_001, None)]
    txns = {t.entity_id: t for t in pool}
    line = bank_line(7_000, ref_no=UTR)

    claims = SearchProposer("C1", pool).propose(line, pool)
    assert [set(c.composition) for c in claims] == [{"pay_a1", "rfnd_x"}]
    _, verdict = _decide(claims, line, txns)
    assert verdict.ok and verdict.confidence == "exact"


def test_an_ambiguous_line_is_not_rescued_by_a_wider_band():
    """The same rule at the top end, and the one that would cost precision if it
    were dropped: two exact solutions means the line is ambiguous, and the
    tolerance pass must not run and manufacture a single answer to it."""
    pool = [payment("pay_a1", 8_000, "setl_a", UTR),
            refund("rfnd_x", 1_000, None), refund("rfnd_y", 1_000, None)]
    txns = {t.entity_id: t for t in pool}
    line = bank_line(7_000, ref_no=UTR)

    claims = SearchProposer("C1", pool).propose(line, pool)
    assert len(claims) == 2
    won, verdict = _decide(claims, line, txns)
    assert won is None and verdict.gate == "G5"


def test_a_balanced_subset_is_not_a_match_until_the_gates_say_so():
    """I8. C1 seeds a settlement whose members are already spent; the arithmetic is
    perfect and G1 rejects it anyway."""
    pool = GROUP + [STRAY]
    txns = {t.entity_id: t for t in pool}
    line = bank_line(8_500, ref_no=UTR)
    claims = SearchProposer("C1", pool).propose(line, pool)

    won, verdict = _decide(claims, line, txns, claimed=frozenset({"pay_a2"}))
    assert won is None and verdict is None      # nothing passed; not G5's business
    assert check(claims[0], line, txns, frozenset({"pay_a2"})).gate == "G1"


def test_the_search_tier_constructs_no_verdict():
    """I2/I4 for the new file. A tier that could build its own passing verdict
    would make the gate chain optional."""
    assert not grep(r"Verdict\(", ["matcher/proposers/search_p.py"])
    assert not grep(r"\bsource\b", ["matcher/proposers/search_p.py"])
