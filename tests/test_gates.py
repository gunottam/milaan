"""Each gate rejects what it should. §7.3 and §8.2.

The verification layer is the only place that can approve, so this file is where
the design is actually load-bearing. Every case asserts a *rejection* except the two
that pin what G4 and G5 are allowed to let through.
"""

from __future__ import annotations

import dataclasses

import pytest

from core.models import BankLine, GatewayTxn
from matcher.gates import (MAX_WINDOW_OVERRIDE_DAYS, TOLERANCE_PAISE, g1_exclusivity,
                           g2_delta, g3_coherence, g4_outcome, g4_tolerance)
from matcher.proposers.base import Claim
from matcher.uniqueness import resolve
from matcher.verify import check

DAY = "2026-01-05"


def payment(entity_id: str, amount: int, settlement_id: str | None,
            settled: str = DAY, **kw) -> GatewayTxn:
    return GatewayTxn(entity_id=entity_id, type="payment", amount_paise=amount,
                      settlement_id=settlement_id,
                      settled_at=f"{settled}T18:30:00+05:30", **kw)


def refund(entity_id: str, amount: int, settlement_id: str | None,
           settled: str = DAY) -> GatewayTxn:
    return GatewayTxn(entity_id=entity_id, type="refund", amount_paise=amount,
                      settlement_id=settlement_id,
                      settled_at=f"{settled}T18:30:00+05:30")


def universe(*txns: GatewayTxn) -> dict[str, GatewayTxn]:
    return {t.entity_id: t for t in txns}


def bank_line(credit: int, debit: int = 0) -> BankLine:
    return BankLine("bl_0001", DAY, DAY, "NEFT-RAZORPAYSOFTW-RZPSETTLE", None,
                    debit, credit, 0)


def claim(*entity_ids: str, anchor: str | None = None, window_days: int = 2) -> Claim:
    return Claim("bl_0001", tuple(entity_ids), anchor, window_days)


# One settlement of three, netting 200 paise. The baseline every gate test bends.
TRIO = universe(payment("pay_1", 100, "setl_a"), payment("pay_2", 60, "setl_a"),
                payment("pay_3", 40, "setl_a"))


# --- G1 exclusivity ----------------------------------------------------------


def test_g1_rejects_a_stale_entity():
    reason = g1_exclusivity(claim("pay_1", "pay_2", "pay_3"), bank_line(200), TRIO,
                            claimed={"pay_2"})
    assert reason and "pay_2" in reason and "already claimed" in reason
    assert check(claim("pay_1", "pay_2", "pay_3"), bank_line(200), TRIO,
                 claimed={"pay_2"}).gate == "G1"


def test_g1_rejects_an_unknown_entity():
    # §7.4: a hypothesis can cite an entity that does not exist. G1 is where that
    # dies, before any solver runs.
    assert "unknown entity pay_9" in g1_exclusivity(
        claim("pay_1", "pay_9"), bank_line(200), TRIO)


def test_g1_rejects_an_entity_settled_outside_the_window():
    txns = universe(payment("pay_1", 100, "setl_a"),
                    payment("pay_2", 100, "setl_a", settled="2026-01-01"))
    assert "outside the 2-day window" in g1_exclusivity(
        claim("pay_1", "pay_2"), bank_line(200), txns)


def test_g1_lets_the_anchor_settlements_own_members_ignore_the_window():
    """§9.3: once the settlement id is known, membership is a fact rather than an
    inference — which is the only reason an on-hold release settled outside the
    window is recoverable at C1."""
    txns = universe(payment("pay_1", 100, "setl_a"),
                    payment("pay_2", 100, "setl_a", settled="2026-01-01"))
    assert g1_exclusivity(claim("pay_1", "pay_2", anchor="setl_a"),
                          bank_line(200), txns) is None
    assert check(claim("pay_1", "pay_2", anchor="setl_a"), bank_line(200), txns).ok


def test_g1_rejects_a_composition_citing_one_entity_twice():
    assert "twice" in g1_exclusivity(claim("pay_1", "pay_1"), bank_line(200), TRIO)


def test_g1_rejects_a_window_override_beyond_the_cap():
    over = MAX_WINDOW_OVERRIDE_DAYS + 1
    assert "outside the permitted" in g1_exclusivity(
        claim("pay_1", window_days=over), bank_line(100), TRIO)


def test_g1_rejects_an_empty_composition():
    assert g1_exclusivity(claim(), bank_line(0), TRIO) == "empty composition"


# --- G2 arithmetic -----------------------------------------------------------


def test_g2_rejects_a_delta_of_one_paise():
    """G2 is strict equality, so one paise is not a match to it.

    It is not a *rejection*, though: §7.3 sends a non-zero delta to G4, and one
    paise clears the double cap for any non-empty composition. So what the chain
    must never do is call it exact — the verdict is stamped `tolerance` and counted
    on its own scoreboard line (§8.3).
    """
    c, line = claim("pay_1", "pay_2", "pay_3"), bank_line(201)
    assert g2_delta(c, line, TRIO) == -1
    verdict = check(c, line, TRIO)
    assert verdict.ok and verdict.confidence == "tolerance"
    assert verdict.delta_paise == -1 and verdict.tolerance == "applied"


def test_g2_is_what_kills_a_clean_identifier_hit_that_does_not_balance():
    # I8, and `bl_06` of docs/workflow.md: a perfectly valid anchor whose members
    # come up short is not a match.
    verdict = check(claim("pay_1", "pay_2", "pay_3", anchor="setl_a"),
                    bank_line(20_000), TRIO)
    assert not verdict.ok and verdict.gate == "G4" and verdict.delta_paise == -19_800
    # Not a near miss, and the verdict says which cap decided rather than leaving
    # ₹198 and 4 paise indistinguishable behind one gate name.
    assert verdict.tolerance == "over_rupee_cap"


def test_g2_ignores_extra_terms():
    # I7: a deduction sits on the transaction that incurred it. A settlement-level
    # term would let a claim invent money to close its own gap.
    c = dataclasses.replace(claim("pay_1", "pay_2", "pay_3"),
                            extra_terms=("instant premium 2500",))
    assert g2_delta(c, bank_line(200), TRIO) == 0


# --- G3 coherence ------------------------------------------------------------


def test_g3_rejects_partial_slices_of_three_settlements():
    txns = universe(*[payment(f"pay_{i}", 100, f"setl_{i}") for i in range(3)],
                    *[payment(f"pad_{i}", 500, f"setl_{i}") for i in range(3)])
    c, line = claim("pay_0", "pay_1", "pay_2"), bank_line(300)
    assert g2_delta(c, line, txns) == 0             # it balances perfectly
    reason = g3_coherence(c, txns)
    assert reason and "spans 3 settlements" in reason
    verdict = check(c, line, txns)
    assert verdict.gate == "G3"                     # and is still not a match
    # G4 was never consulted, and the residual G2 measured is still on the record.
    assert verdict.tolerance is None and verdict.delta_paise == 0


def test_g3_is_the_same_function_the_oracle_applies():
    from core import coherence
    from matcher import gates
    assert gates.is_plausible_payout is coherence.is_plausible_payout


# --- G4 tolerance ------------------------------------------------------------


def test_g4_accepts_two_paise_across_three_transactions():
    c, line = claim("pay_1", "pay_2", "pay_3"), bank_line(202)
    assert g4_tolerance(c, g2_delta(c, line, TRIO)) is None
    verdict = check(c, line, TRIO)
    assert verdict.ok and verdict.confidence == "tolerance"
    assert verdict.delta_paise == -2 and verdict.tolerance == "applied"


def test_g4_rejects_eighty_seven_paise_across_three_transactions():
    """Within ₹1 and still a wrong subset. The second cap is the one working."""
    c, line = claim("pay_1", "pay_2", "pay_3"), bank_line(287)
    delta = g2_delta(c, line, TRIO)
    assert abs(delta) <= TOLERANCE_PAISE            # the first cap would admit it
    reason = g4_tolerance(c, delta)
    assert reason and "more than one paise each" in reason
    verdict = check(c, line, TRIO)
    assert verdict.gate == "G4"
    # Rounding-shaped in magnitude, wrong in spread — the label separates this from
    # a residual that was never close.
    assert verdict.tolerance == "over_per_txn_cap"


def test_g4_rejects_a_delta_over_the_rupee_cap():
    c = claim(*[f"pay_{i}" for i in range(1, 4)])
    assert "exceeds the 100 paise tolerance" in g4_tolerance(c, 101)
    assert g4_outcome(c, 101) == "over_rupee_cap"


def test_the_g4_label_and_the_g4_reason_cannot_disagree():
    """One classification produces both, so a verdict cannot say `applied` while
    carrying a rejection reason."""
    c = claim("pay_1", "pay_2", "pay_3")
    for delta in (-101, -87, -3, -1, 0, 1, 3, 87, 101):
        assert (g4_tolerance(c, delta) is None) == (g4_outcome(c, delta) == "applied")


# --- the shapes --------------------------------------------------------------


def test_claim_is_frozen_and_carries_no_provenance():
    """I9. `Claim` is the whole contract between the two layers: if the checker
    could learn where a candidate came from, someone would write a gate that trusts
    one origin over another."""
    c = claim("pay_1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.composition = ("pay_2",)                  # type: ignore[misc]
    assert not any(f.name == "source" for f in dataclasses.fields(Claim))


def test_a_passing_verdict_carries_a_balanced_proof():
    # The §1 golden card payment: ₹12,000 at 2% MDR, GST on the rounded fee, TDS.
    txns = universe(payment("pay_c", 12_000_00, "setl_c", fee_paise=24_000,
                            tax_paise=4_320, tds_paise=1_200))
    verdict = check(claim("pay_c", anchor="setl_c"), bank_line(11_70_480), txns)
    assert verdict.ok and verdict.confidence == "exact" and verdict.delta_paise == 0
    proof = verdict.proof
    assert sum(amount for _, _, amount in proof.rows) == proof.total_paise
    assert proof.total_paise == proof.target_paise == 11_70_480
    assert [label for label, _, _ in proof.rows] == [
        "payments captured", "MDR", "GST @ 18% on MDR", "TDS @ 0.10% u/s 194-O"]


def test_g3_rejects_a_composition_spanning_three_partial_settlements():
    """The pre-C2 proof that the coherence path works.

    G3 fired **once** in the whole stage-6 run, which is not coverage — Phase A and
    B1 propose whole settlement groups by construction, so nothing incoherent is
    reachable from those tiers. C2 in stage 8 is the first tier that proposes
    arbitrary subsets, and this asserts the rejection before it exists.
    """
    txns = universe(
        payment("pay_a1", 500, "setl_a"), payment("pay_a2", 700, "setl_a"),
        payment("pay_b1", 300, "setl_b"), payment("pay_b2", 900, "setl_b"),
        payment("pay_c1", 200, "setl_c"), payment("pay_c2", 400, "setl_c"))
    c, line = claim("pay_a1", "pay_b1", "pay_c1"), bank_line(1_000)

    assert g2_delta(c, line, txns) == 0          # one slice from each: it balances
    verdict = check(c, line, txns)
    assert not verdict.ok and verdict.gate == "G3"
    assert "spans 3 settlements and 0 unassigned items" in verdict.reason
    # Each group is left incomplete, which is the shape §9.4 refuses outright.
    assert all(len({e for e in c.composition if txns[e].settlement_id == sid}) == 1
               for sid in ("setl_a", "setl_b", "setl_c"))


def test_a_rejected_verdict_still_carries_its_delta():
    # I6: nothing is silently absorbed, including by a refusal.
    assert check(claim("pay_1", "pay_2", "pay_3"), bank_line(999), TRIO).delta_paise \
        == 200 - 999


# --- G5 uniqueness, over the set -------------------------------------------


# One settlement plus two interchangeable cross-cycle strays: the only ambiguity
# G3 permits, and the shape every ambiguous line in the generated data has.
STRAYS = universe(payment("pay_1", 300, "setl_a"), refund("rfnd_1", 100, None),
                  refund("rfnd_2", 100, None), refund("rfnd_3", 101, None))


def _verdicts(*compositions: tuple[str, ...]) -> list:
    line = bank_line(200)
    return [(claim(*c), check(claim(*c), line, STRAYS)) for c in compositions]


def test_g5_refuses_two_distinct_compositions_at_the_same_delta():
    passing = _verdicts(("pay_1", "rfnd_1"), ("pay_1", "rfnd_2"))
    assert all(v.ok for _, v in passing)
    won, verdict = resolve(passing)
    assert won is None
    assert verdict.gate == "G5" and not verdict.ok
    assert "2 compositions tie" in verdict.reason


def test_g5_treats_the_same_set_from_two_proposers_as_one_answer():
    line = bank_line(200)
    both = ("pay_1", "rfnd_1")
    passing = [(claim(*both), check(claim(*both), line, STRAYS)),
               (claim(*reversed(both), anchor="setl_a"),
                check(claim(*reversed(both), anchor="setl_a"), line, STRAYS))]
    won, verdict = resolve(passing)
    assert won is not None and verdict.ok and set(won.composition) == set(both)


def test_g5_prefers_the_exact_answer_over_a_tolerance_one():
    # §9.3 takes the minimum |delta| and refuses only on ties AT that minimum.
    passing = _verdicts(("pay_1", "rfnd_1"), ("pay_1", "rfnd_3"))
    assert [v.confidence for _, v in passing] == ["exact", "tolerance"]
    won, verdict = resolve(passing)
    assert won.composition == ("pay_1", "rfnd_1") and verdict.delta_paise == 0


def test_g5_has_nothing_to_say_when_nothing_passed():
    assert resolve([]) == (None, None)
    failed = _verdicts(("pay_1", "rfnd_1", "rfnd_2"))
    assert not failed[0][1].ok
    assert resolve(failed) == (None, None)
