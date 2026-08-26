"""Generation knobs. §15 of the spec, plus the dataset shape."""

from __future__ import annotations

from datetime import date

SETTLEMENT_WINDOW_DAYS = 2

# The oracle's budget is not the matcher's. Offline generation has no wall clock
# to answer to, and an exhausted budget excludes the line from scoring — an
# exclusion that correlates with difficulty (cost tracks the count of negative-net
# items, not pool size), so a live-sized budget quietly inflates recall by
# dropping the hardest lines. Generate offline; keep the live number honest.
UNIQUENESS_NODE_BUDGET_OFFLINE = 2_000_000
UNIQUENESS_NODE_BUDGET_LIVE = 20_000

C2_MAX_POOL = 35   # Above this, unanchored subset-sum cannot establish uniqueness:
                   # 2**len(pool) exceeds the target range, so by pigeonhole every
                   # target has many representations. Not a budget problem — an
                   # information-theoretic one. C2 must refuse rather than search.
DEFAULT_BANK_LINES = 120
DEFAULT_RECORDS = 3_000
TARGET_AMBIGUOUS_RATE = 0.08

EPOCH = date(2026, 1, 1)          # first settlement cycle; fixed so runs are reproducible

# Cycles are spaced `window_days + 1` apart, so a line's window pool holds its own
# settlement and nothing else. This is not cosmetic. A payout of ~25 transactions
# inside a 2-day window that also caught its neighbours would give a pool of ~75:
# 2**75 subsets against a sum range of ~1e7 paise, so by pigeonhole EVERY target
# has many representations and no amount of node budget can establish uniqueness.
# Subset-sum only carries information while 2**len(pool) stays near the sum range.
def cycle_spacing(window_days: int) -> int:
    return window_days + 1

CYCLE_HOUR = "18:30:00"           # payouts land at the end of the banking day
OPENING_BALANCE = 42_00_000_00    # ₹42,00,000 — presentational only
MERCHANT_BANK = "HDFC"

METHOD_WEIGHTS = (
    ("upi", 45), ("card", 25), ("netbanking", 10), ("wallet", 8),
    ("rupay_debit", 7), ("emi", 3), ("intl_card", 2),
)
CARD_NETWORKS = ("VISA", "MASTERCARD", "RUPAY", "AMEX")

# Catalogue prices in paise. Every amount is jittered off one of these EXCEPT the
# sticky ones below, so exact net collisions are rare rather than pervasive.
PRICE_POINTS = (
    149_00, 249_00, 499_00, 899_00, 999_00, 1_499_00, 1_999_00,
    2_499_00, 3_999_00, 4_999_00, 9_999_00, 12_000_00,
)
JITTER_PAISE = 500                # ±₹5 around the catalogue price

# §6.2 rate control. A sticky-priced UPI payment carries no jitter and zero MDR,
# so two of them have IDENTICAL net contributions — which is how AMBIGUOUS_SUBSET
# arises naturally. Ambiguity is roughly quadratic in this share, hence the small
# value; stage 4 tunes it against TARGET_AMBIGUOUS_RATE across five seeds.
STICKY_PRICES = (999_00, 499_00)
STICKY_PRICE_RATE = 0.012

REFUND_RATE = 0.06                # share of records that are refunds
FX_RATE_MICROS = 83_500_000       # ₹83.50/USD, jittered per transaction

# Narration degradation, §3.4. `drop`/`blank` are what makes a line unparseable by
# regex alone; at high noise they must total ~30%.
NOISE_PROFILES = {
    "low":    {"drop": 0.01, "blank": 0.00, "truncate": 0.04, "transpose": 0.01,
               "collapse": 0.05, "upper": 0.05, "abbrev": 0.05, "ref_no": 0.90},
    "medium": {"drop": 0.07, "blank": 0.03, "truncate": 0.15, "transpose": 0.05,
               "collapse": 0.20, "upper": 0.20, "abbrev": 0.20, "ref_no": 0.55},
    "high":   {"drop": 0.16, "blank": 0.06, "truncate": 0.28, "transpose": 0.08,
               "collapse": 0.45, "upper": 0.45, "abbrev": 0.45, "ref_no": 0.25},
}
