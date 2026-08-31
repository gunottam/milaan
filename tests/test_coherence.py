"""G3 coherence, §9.4 — and the reason the oracle has to apply it too."""

from __future__ import annotations

from core.coherence import is_plausible_payout
from core.models import BankLine, GatewayTxn
from core.subsetsum import solve_exact
from generator.uniqueness import classify

BIG = 10_000_000


def universe(*txns: GatewayTxn) -> dict[str, GatewayTxn]:
    return {t.entity_id: t for t in txns}


def payment(entity_id: str, amount: int, settlement_id: str | None) -> GatewayTxn:
    return GatewayTxn(entity_id=entity_id, type="payment", amount_paise=amount,
                      settlement_id=settlement_id, settled_at="2026-01-01T18:30:00+05:30")


def refund(entity_id: str, amount: int, settlement_id: str | None) -> GatewayTxn:
    return GatewayTxn(entity_id=entity_id, type="refund", amount_paise=amount,
                      settlement_id=settlement_id, settled_at="2026-01-01T18:30:00+05:30")


# --- §9.4, row by row --------------------------------------------------------


def test_one_complete_settlement_is_accepted():
    txns = universe(payment("p1", 100, "s1"), payment("p2", 60, "s1"))
    assert is_plausible_payout(("p1", "p2"), txns)


def test_a_complete_settlement_plus_one_or_two_strays_is_accepted():
    txns = universe(payment("p1", 100, "s1"), payment("p2", 60, "s1"),
                    refund("r1", 20, None), refund("r2", 30, None))
    assert is_plausible_payout(("p1", "p2", "r1"), txns)
    assert is_plausible_payout(("p1", "p2", "r1", "r2"), txns)


def test_a_complete_settlement_plus_three_strays_is_rejected():
    txns = universe(payment("p1", 100, "s1"), refund("r1", 1, None),
                    refund("r2", 2, None), refund("r3", 3, None))
    assert not is_plausible_payout(("p1", "r1", "r2", "r3"), txns)


def test_a_complete_settlement_plus_an_item_from_another_group_is_accepted():
    # Accepted, and flagged SETTLEMENT_CONTAMINATION downstream for a human.
    txns = universe(payment("p1", 100, "s1"), payment("p2", 60, "s2"),
                    payment("p3", 70, "s2"))
    assert is_plausible_payout(("p1", "p2"), txns)


def test_a_partial_slice_of_one_settlement_is_rejected():
    # The case that matters: arithmetically it can balance, but a payout is never
    # a subset of a settlement group.
    txns = universe(payment("p1", 100, "s1"), payment("p2", 60, "s1"),
                    refund("r1", 60, "s1"))
    assert not is_plausible_payout(("p1",), txns)
    assert is_plausible_payout(("p1", "p2", "r1"), txns)


def test_partial_slices_of_three_settlements_are_rejected():
    txns = universe(*[payment(f"p{i}", 10 + i, f"s{i}") for i in range(3)],
                    *[payment(f"q{i}", 20 + i, f"s{i}") for i in range(3)])
    assert not is_plausible_payout(("p0", "p1", "p2"), txns)


def test_two_complete_settlements_are_rejected():
    txns = universe(payment("p1", 100, "s1"), payment("p2", 60, "s2"))
    assert not is_plausible_payout(("p1", "p2"), txns)


def test_unassigned_items_can_stand_alone():
    # B2: a chargeback posted as a bank debit matches one cross-cycle item with a
    # negative net, and belongs to no settlement group at all.
    txns = universe(refund("d1", 4500, None), refund("d2", 100, None))
    assert is_plausible_payout(("d1",), txns)
    assert is_plausible_payout(("d1", "d2"), txns)


def test_an_empty_composition_is_not_a_payout():
    assert not is_plausible_payout((), universe(payment("p1", 100, "s1")))


# --- the oracle must agree with the gate -------------------------------------


def test_the_gate_does_not_count_an_incoherent_superset_as_a_second_solution():
    """A refund cancelling a payment inside the same payout makes the payout's own
    prefix balance. The raw solver reports two answers; G3 rejects one, so truth
    must record a verified single answer — otherwise the matcher's correct match
    scores as a false positive."""
    txns = universe(payment("p1", 100, "s1"), payment("p2", 60, "s1"),
                    refund("r1", 60, "s1"))
    pool = list(txns.values())
    line = BankLine("bl_0001", "2026-01-01", "2026-01-01", "", None, 0, 100, 100)

    raw = solve_exact(pool, 100, budget=BIG, max_solutions=10)
    assert len(raw) == 2, raw            # {p1} and {p1, p2, r1} both sum to 100

    record = classify(line, txns, pool, ("p1", "p2", "r1"))
    assert record["resolvable"] is True
    assert record["uniqueness"] == "verified"
    assert record["composition"] == ["p1", "p2", "r1"]
    assert "ambiguity_class" not in record
