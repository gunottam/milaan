"""C3, the pairwise split. §9.3, finding 8.5.

Two halves of the file, and they answer different questions.

**The hand-built cases** are about the representation: a split payout is the one
composition whose coherence cannot be judged from one bank line, so `Claim` carries
the partner half and G3 asks its question of the pair. The load-bearing test is that
the *same half without* `joint_with` is refused — if that ever passes, the
representation stopped being necessary and something else has gone soft.

**The board case** is about the measurement, and the number is unflattering: C3
closes one of the six `SPLIT_PAYOUT` halves on seed 42 and refuses five. The five
are not a search failure. A statement records a credit, not which of the
settlement's transactions the bank put behind it, and where several subsets of the
payout balance against the credit there is nothing in the input that picks one.
Truth's `by_construction` uniqueness is an assertion about how the generator cut
the payout — the bank-line side of finding 8.4. `docs/journal/stage-13.md` has the
per-line arithmetic.
"""

from __future__ import annotations

from collections import Counter

import pytest

from core.models import BankLine, GatewayTxn
from matcher.proposers.base import Claim
from matcher.proposers.split_p import SplitProposer
from matcher.run import build_tiers, run_ladder
from matcher.uniqueness import resolve
from matcher.verify import check
from scoring.score import all_lines, phase_e, precision, score

DAY = "2026-03-04"


def payment(entity_id: str, amount: int, settlement_id: str | None,
            day: str = DAY) -> GatewayTxn:
    return GatewayTxn(entity_id=entity_id, type="payment", amount_paise=amount,
                      settlement_id=settlement_id,
                      settled_at=f"{day}T18:30:00+05:30")


def refund(entity_id: str, amount: int, settlement_id: str | None,
           day: str = DAY) -> GatewayTxn:
    return GatewayTxn(entity_id=entity_id, type="refund", amount_paise=amount,
                      settlement_id=settlement_id,
                      settled_at=f"{day}T18:30:00+05:30")


def credit(bank_line_id: str, amount: int, day: str = DAY) -> BankLine:
    return BankLine(bank_line_id=bank_line_id, txn_date=day, value_date=day,
                    narration="NEFT-RAZORPAYSOFTW-RZPSETTLE", ref_no=None,
                    debit_paise=0, credit_paise=amount, balance_paise=0)


def plan_for(txns, lines, *, claimed=frozenset()):
    """Run one C3 sweep the way the ladder does and hand back the tier."""
    tier = SplitProposer(txns)
    pools = {b.bank_line_id: [t for t in txns if t.entity_id not in claimed]
             for b in lines}
    tier.prepare(lines, pools, frozenset(claimed), 1)
    return tier


# --- the representation ------------------------------------------------------


def _unique_pair():
    """A settlement of four whose division across two credits is unambiguous.

    Distinct powers of ten, so exactly one subset sums to each credit — the case
    where C3 has an answer at all.
    """
    txns = [payment("pay_a", 1_000_00, "setl_x"),
            payment("pay_b", 2_000_00, "setl_x"),
            payment("pay_c", 40_000_00, "setl_x"),
            payment("pay_d", 800_000_00, "setl_x")]
    lines = [credit("bl_0001", 3_000_00), credit("bl_0002", 840_000_00)]
    return txns, lines


def test_the_pair_walks_the_gate_chain_and_both_halves_close():
    """§9.3's C3, end to end: two credits, one settlement, both halves approved
    with a delta of zero and an anchor naming the settlement."""
    txns, lines = _unique_pair()
    by_id = {t.entity_id: t for t in txns}
    tier = plan_for(txns, lines)

    for line in lines:
        claims = tier.propose(line, txns)
        assert len(claims) == 1, claims
        claim, verdict = resolve([(c, check(c, line, by_id)) for c in claims])
        assert verdict.ok and verdict.delta_paise == 0
        assert verdict.confidence == "exact"
        assert claim.anchor_settlement_id == "setl_x"

    assert tier.propose(lines[0], txns)[0].composition == ("pay_a", "pay_b")
    assert tier.propose(lines[1], txns)[0].composition == ("pay_c", "pay_d")
    assert tier.partners == {"bl_0001": "bl_0002", "bl_0002": "bl_0001"}
    assert tier.refusals == {}


def test_the_same_half_without_its_partner_is_refused_by_g3():
    """**The representation is load-bearing.** Half of a split credit is a partial
    slice of a settlement, and G3 refuses partial slices by design (§9.4). That is
    why the pair has to be expressible at all — and if this ever starts passing,
    C3 stopped being the thing that made the pair verifiable."""
    txns, lines = _unique_pair()
    by_id = {t.entity_id: t for t in txns}
    bare = Claim("bl_0001", ("pay_a", "pay_b"), anchor_settlement_id="setl_x",
                 window_days=2)
    verdict = check(bare, lines[0], by_id)
    assert not verdict.ok and verdict.gate == "G3"
    # Same composition, same line, same arithmetic — the partner half is the only
    # difference, and it is what makes the payout a payout.
    joined = Claim("bl_0001", ("pay_a", "pay_b"), anchor_settlement_id="setl_x",
                   window_days=2, joint_with=("pay_c", "pay_d"))
    assert check(joined, lines[0], by_id).ok


def test_the_partner_half_is_cited_never_spent():
    """G1 exempts `joint_with` from exclusivity, and nothing is double-spent by it.

    The second of the two lines reaches the gate chain after the first has claimed
    its half, so a `claimed` test over `joint_with` would refuse the pair on the
    strength of its own success. G2 still sums `composition` alone, which is what
    keeps the exemption from creating money.
    """
    txns, lines = _unique_pair()
    by_id = {t.entity_id: t for t in txns}
    tier = plan_for(txns, lines)
    first = tier.propose(lines[0], txns)[0]
    assert check(first, lines[0], by_id).ok

    spent = set(first.composition)
    second = tier.propose(lines[1], txns)[0]
    verdict = check(second, lines[1], by_id, spent)
    assert verdict.ok and verdict.delta_paise == 0
    # And the exemption is only for the half it does not spend.
    assert not check(second, lines[1], by_id, spent | {"pay_c"}).ok


def test_g1_rejects_a_malformed_joint_claim():
    """§7.4: G1 validates what a claim asserts before any of it is trusted."""
    txns, lines = _unique_pair()
    by_id = {t.entity_id: t for t in txns}

    unknown = Claim("bl_0001", ("pay_a", "pay_b"), anchor_settlement_id="setl_x",
                    window_days=2, joint_with=("pay_ghost",))
    assert check(unknown, lines[0], by_id).gate == "G1"

    overlapping = Claim("bl_0001", ("pay_a", "pay_b"),
                        anchor_settlement_id="setl_x", window_days=2,
                        joint_with=("pay_b", "pay_c"))
    assert check(overlapping, lines[0], by_id).gate == "G1"

    unanchored = Claim("bl_0001", ("pay_a", "pay_b"), window_days=2,
                       joint_with=("pay_c", "pay_d"))
    assert check(unanchored, lines[0], by_id).gate == "G1"


def test_the_residual_is_a_cross_cycle_stray_not_a_second_group():
    """A payout is a settlement group plus whatever it nets (§9.1's amendment), so
    the joint credit is rarely the group total. C3 composes the difference from
    unassigned items only — narrower than G3 on purpose, and on seed 42 the sole
    source of spurious pairings was the alternative."""
    txns = [payment("pay_a", 1_000_00, "setl_x"),
            payment("pay_b", 2_000_00, "setl_x"),
            payment("pay_c", 40_000_00, "setl_x"),
            payment("pay_d", 800_000_00, "setl_x"),
            refund("rfnd_z", 500_00, None)]
    lines = [credit("bl_0001", 2_500_00), credit("bl_0002", 840_000_00)]
    tier = plan_for(txns, lines)
    claims = tier.propose(lines[0], txns)
    assert len(claims) == 1
    assert claims[0].composition == ("pay_a", "pay_b", "rfnd_z")
    assert claims[0].joint_with == ("pay_c", "pay_d")

    # The same difference sitting inside another settlement group is not offered.
    tagged = [*txns[:4], refund("rfnd_z", 500_00, "setl_y"),
              payment("pay_y", 9_000_00, "setl_y")]
    assert plan_for(tagged, lines).propose(lines[0], tagged) == []


def test_an_ambiguous_division_is_refused_not_picked():
    """Two payments of the same net are interchangeable between the halves, so
    which credit carried which is not determined. G5 withdraws approval — §17,
    Milaan does not invent distinctions to break ties."""
    txns = [payment("pay_a", 5_000_00, "setl_x"),
            payment("pay_b", 5_000_00, "setl_x"),
            payment("pay_c", 7_000_00, "setl_x"),
            payment("pay_d", 7_000_00, "setl_x")]
    lines = [credit("bl_0001", 12_000_00), credit("bl_0002", 12_000_00)]
    by_id = {t.entity_id: t for t in txns}
    tier = plan_for(txns, lines)

    claims = tier.propose(lines[0], txns)
    assert len(claims) >= 2
    won, verdict = resolve([(c, check(c, lines[0], by_id)) for c in claims])
    assert won is None and verdict.gate == "G5"
    assert tier.refusals["bl_0001"].startswith("SPLIT_PAYOUT: setl_x ties to this")
    assert "bl_0002" in tier.refusals["bl_0001"]


def test_c3_proposes_nothing_when_no_pair_composes_a_settlement():
    txns = [payment("pay_a", 1_000_00, "setl_x"),
            payment("pay_b", 2_000_00, "setl_x")]
    lines = [credit("bl_0001", 1_000_00), credit("bl_0002", 9_999_00)]
    tier = plan_for(txns, lines)
    assert tier.plan == {} and tier.refusals == {}


def test_a_pair_outside_the_window_is_not_a_pair():
    """One payout cannot produce two credits a week apart (§2's window)."""
    txns, _ = _unique_pair()
    lines = [credit("bl_0001", 3_000_00), credit("bl_0002", 840_000_00, "2026-03-20")]
    assert plan_for(txns, lines).plan == {}


def test_a_settlement_already_claimed_is_not_offered_as_an_anchor():
    """C3's anchors are settlements whose members are all unclaimed. A group one
    line already holds is not half of anything."""
    txns, lines = _unique_pair()
    tier = plan_for(txns, lines, claimed={"pay_a"})
    assert tier.plan == {}


# --- the board, §11 ----------------------------------------------------------


@pytest.fixture(scope="session")
def with_c3(seed42):
    """The whole ladder including C3, uncapped, plus Phase E over what it proved."""
    generated, truth = seed42
    run = run_ladder(generated.txns, generated.bank_lines,
                     tiers=build_tiers(generated.txns), deadline_ms=None)
    report = score(truth, {b: c.composition
                           for b, (_, c, _) in run.matched.items()})
    _, ledger = phase_e(generated.txns, generated.bank_lines, generated.orders, run)
    return run, report, ledger


def test_c3_closes_one_split_half_and_refuses_five(with_c3):
    """**The measurement, and it is not the one stage 12 hoped for.**

    Six `SPLIT_PAYOUT` halves score FN before C3. C3 closes one of them and refuses
    five, and the five are refused for the same reason every time: more than one
    subset of the payout balances against the credit, so the division is
    undetermined and `resolve` will not pick. Only `bl_0101` — whose half is a
    single transaction — has a division the input settles.

    Recall moves one line, not six. Precision does not move at all, and that is the
    property the refusals protect: five committed halves would each have been a
    false match, and a false match puts the books wrong silently (§1).
    """
    run, report, _ = with_c3
    halves = report.lines("by_construction_c3")
    assert len(halves) == 6
    assert Counter(report.outcomes[b] for b in halves) == Counter({"TP": 1, "FN": 5})
    assert report.outcomes["bl_0101"] == "TP"
    assert run.matched["bl_0101"][0] == "C3"


def test_c3_fabricates_nothing(with_c3):
    """FP 0, precision 100%. C3 is the first tier that can approve a composition no
    single bank line balances against, so this is the measurement that matters."""
    _, report, _ = with_c3
    counts = all_lines(report)
    assert counts["FP"] == 0
    assert precision(counts) == 1.0
    amb = report.emergent_breaks["AMBIGUOUS_SUBSET"]
    assert amb["matched"] == 0 and amb["refused"] == amb["count"]


def test_the_ladder_through_c3_closes_100_of_134(with_c3):
    """The pre-C3 board is pinned at 99 in `test_phase_c.py`; this is the delta.

    One line, and the all-lines recall figure moves with it. It shows up in the
    disclosed `by_construction_c3` bucket — the headline bucket holds no
    `SPLIT_PAYOUT` line and does not move.
    """
    run, report, _ = with_c3
    assert len(run.matched) == 100
    assert report.counts("headline") == Counter({"TP": 88, "TN": 13})


def test_the_five_refusals_are_typed_split_payout(with_c3):
    """The other half of the stage: they leave `UNIQUENESS_UNPROVEN` behind.

    Stage 10 measured five of these as `UNIQUENESS_UNPROVEN` and one as
    `WITHHELD_RECORD` — refusals wearing a label that sends a human looking for a
    record that is not missing. C3's refusal names the settlement, names the partner
    credit and says what is actually absent; the ledger types it `SPLIT_PAYOUT` and
    prices it as documentation rather than as money at risk, because the pair
    contributes exactly zero to §9.7's gap.
    """
    run, _, ledger = with_c3
    touched = {s["line"] for s in run.trace if s["tier"] == "C3"}
    assert touched >= {"bl_0019", "bl_9002", "bl_0048", "bl_9003", "bl_0101",
                       "bl_9001"}
    for step in run.trace:
        if step["tier"] == "C3" and step["unproven"]:
            assert step["unproven"].startswith("SPLIT_PAYOUT: setl_")
            assert step["line"] != "bl_0101", "a closed line kept a refusal string"

    rows = {e.bank_line_id: e for e in ledger.exceptions
            if e.exception_type == "SPLIT_PAYOUT"}
    assert set(rows) == {"bl_0019", "bl_9002", "bl_0048", "bl_9003", "bl_9001"}
    for row in rows.values():
        assert row.risk_class == "documentation"
        assert row.type_confidence == "high"
        # C3's own anchor, and it agrees with the sentence. `anchors[0]` over the
        # whole trace picked A3's alphabetically-first prefix candidate instead —
        # `setl_0000` on a row whose payout is `setl_0101`.
        assert row.settlement_id and row.settlement_id in row.evidence[0]
        assert row.delta_diagnosis == "split_across_two_credits"
        assert "bank advice" in row.blocked_on
        assert any("jointly to the paisa" in e or "jointly across" in e
                   for e in row.evidence)
        assert any("balance against this credit exactly" in e
                   for e in row.evidence)
    # And nothing is typed by the labels they used to wear.
    assert not any(e.bank_line_id in rows and e.exception_type != "SPLIT_PAYOUT"
                   for e in ledger.exceptions)
