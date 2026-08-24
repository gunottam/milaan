from datetime import date
from decimal import Decimal

import pytest

from core.fees import allocate, expected_fee
from core.money import fmt_inr, in_window, ist_date, round_paise, to_paise, window_key


class Txn:
    """Minimal stand-in until core/models.py exists."""

    def __init__(self, entity_id, method, amount_paise, international=False):
        self.entity_id = entity_id
        self.method = method
        self.amount_paise = amount_paise
        self.international = international


# --- §4.2 golden cases -------------------------------------------------------


def test_card_2pc_mdr_gst_tds():
    # ₹12,000 card: the done-when case.
    fee, tax, tds = expected_fee(Txn("pay_1", "card", 12_000_00))
    assert (fee, tax, tds) == (24000, 4320, 1200)
    assert 12_000_00 - fee - tax - tds == 1170480


def test_gst_is_computed_on_the_rounded_fee():
    # ₹251.25 card -> raw fee 502.5 paise. HALF_UP to 503, then 18% of 503 = 90.54 -> 91.
    # 18% of the UNROUNDED 502.5 is 90.45 -> 90. The order is load-bearing.
    fee, tax, _ = expected_fee(Txn("pay_2", "card", 25125))
    assert fee == 503
    assert tax == 91
    assert round_paise(Decimal("502.5") * Decimal("0.18")) == 90


def test_upi_is_zero_rated_but_still_withholds_tds():
    fee, tax, tds = expected_fee(Txn("pay_3", "upi", 99_900))
    assert (fee, tax) == (0, 0)
    assert tds == 100          # 99.9 paise, HALF_UP


def test_rupay_debit_is_zero_rated():
    fee, tax, _ = expected_fee(Txn("pay_4", "rupay_debit", 5_000_00))
    assert (fee, tax) == (0, 0)


def test_international_card_folds_fx_markup_into_fee():
    # 2% MDR + 1% FX markup = 3%, all inside fee_paise. No separate FX term (I7).
    fee, tax, tds = expected_fee(Txn("pay_5", "card", 10_000_00, international=True))
    assert fee == 30000
    assert tax == 5400
    assert tds == 1000


def test_intl_card_method_is_3pc_before_the_markup():
    domestic = expected_fee(Txn("pay_6", "intl_card", 10_000_00))[0]
    abroad = expected_fee(Txn("pay_7", "intl_card", 10_000_00, international=True))[0]
    assert domestic == 30000
    assert abroad == 40000


def test_tds_is_a_tenth_of_a_percent():
    assert expected_fee(Txn("pay_8", "upi", 1_00_000_00))[2] == 10000


def test_unknown_method_raises():
    with pytest.raises(KeyError):
        expected_fee(Txn("pay_9", "crypto", 100))


# --- §4.3 allocation ---------------------------------------------------------


def test_allocation_remainder_is_dropped_by_integer_division():
    txns = [Txn(f"pay_{i}", "card", 100) for i in range(3)]
    alloc = allocate(25_00, txns)
    assert alloc == {"pay_0": 833, "pay_1": 833, "pay_2": 833}
    assert 25_00 - sum(alloc.values()) == 1        # the ROUNDING_DRIFT paise


def test_allocation_drift_is_bounded_by_n_minus_1():
    for n in range(1, 12):
        txns = [Txn(f"pay_{i}", "upi", 100) for i in range(n)]
        assert 0 <= 25_00 - sum(allocate(25_00, txns).values()) <= n - 1


def test_allocation_of_an_exact_multiple_leaves_no_drift():
    txns = [Txn(f"pay_{i}", "upi", 100) for i in range(4)]
    alloc = allocate(2400, txns)
    assert set(alloc.values()) == {600}
    assert sum(alloc.values()) == 2400


# --- money -------------------------------------------------------------------


def test_round_paise_is_half_up_not_bankers():
    assert round_paise(Decimal("2.5")) == 3      # banker's rounding would give 2
    assert round_paise(Decimal("0.5")) == 1
    assert round_paise(Decimal("1.4999")) == 1
    assert round_paise(Decimal("-2.5")) == -3


def test_to_paise():
    assert to_paise("12000") == 1_200_000
    assert to_paise("46193.88") == 4_619_388
    assert to_paise(Decimal("0.005")) == 1


def test_fmt_inr_uses_indian_digit_grouping():
    assert fmt_inr(4_619_388) == "₹46,193.88"
    assert fmt_inr(46_193_880) == "₹4,61,938.80"      # never ₹461,938.80
    assert fmt_inr(1_234_567_890) == "₹1,23,45,678.90"
    assert fmt_inr(0) == "₹0.00"
    assert fmt_inr(5) == "₹0.05"
    assert fmt_inr(100) == "₹1.00"
    assert fmt_inr(99_999) == "₹999.99"
    assert fmt_inr(-450_000) == "₹-4,500.00"


# --- IST ---------------------------------------------------------------------


def test_ist_date_reads_the_ist_calendar_date():
    assert ist_date("2026-01-15T23:45:00+05:30") == date(2026, 1, 15)
    # Same instant expressed in UTC. Naively slicing the string gives 14-Jan.
    assert ist_date("2026-01-15T18:15:00+00:00") == date(2026, 1, 15)
    assert ist_date("2026-01-15") == date(2026, 1, 15)


def test_window_key_falls_back_to_txn_date():
    assert window_key("2026-01-16", "2026-01-15") == date(2026, 1, 16)
    assert window_key(None, "2026-01-15") == date(2026, 1, 15)
    assert window_key("", "2026-01-15") == date(2026, 1, 15)


def test_in_window_is_inclusive_and_looks_backwards_only():
    anchor = date(2026, 1, 15)
    assert in_window(date(2026, 1, 15), anchor, 2)
    assert in_window(date(2026, 1, 13), anchor, 2)
    assert not in_window(date(2026, 1, 12), anchor, 2)
    assert not in_window(date(2026, 1, 16), anchor, 2)
