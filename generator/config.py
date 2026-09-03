"""Generation knobs. §15 of the spec, plus the dataset shape."""

from __future__ import annotations

from datetime import date

from core.subsetsum import C2_MAX_POOL      # noqa: F401 — re-exported; see below

SETTLEMENT_WINDOW_DAYS = 2

# The oracle's budget is not the matcher's. Offline generation has no wall clock
# to answer to, and an exhausted budget excludes the line from scoring — an
# exclusion that correlates with difficulty (cost tracks the count of negative-net
# items, not pool size), so a live-sized budget quietly inflates recall by
# dropping the hardest lines. Generate offline; keep the live number honest.
# Measured, not guessed: at 2M, 13 of 134 lines went unproven; at 40M, 12 of those
# 13 resolve — and three of them turn out to be genuinely ambiguous, so the lower
# budget was hiding true-negative evidence behind "excluded from scoring". The
# worst single line costs ~6s and offline wall clock buys nothing else.
UNIQUENESS_NODE_BUDGET_OFFLINE = 40_000_000
UNIQUENESS_NODE_BUDGET_LIVE = 20_000

# The budget a browser-triggered run generates at. **Measured, stage 11b**, seed 42,
# 120 payouts / 3,000 records, sweeping between the live 20k and the offline 40M:
#
#     budget       gen s   unproven   verified   ambiguous
#     20,000         0.8         57         52           2
#     50,000         1.1         44         65           2
#     100,000        1.7         37         70           4
#     250,000        2.9         26         80           5
#     500,000        4.5         22         84           5
#     1,000,000      7.4         20         86           5
#     2,000,000     12.3         15         88           8
#     5,000,000     18.7          6         92          13   <- the knee
#     10,000,000    25.8          4         92          15
#     20,000,000    35.2          3         92          16
#     40,000,000    53.9          3         92          16
#
# 20k put 57 of 134 lines in `unproven` and left `verified` at 52, so the demo was
# measuring a materially different board from the journals. **`verified` reaches its
# ceiling of 92 at 5M — the same figure the 40M offline run reports** — and beyond
# that only three lines move, out of `unproven` and into `AMBIGUOUS_SUBSET`. So 5M
# buys the whole headline population for 18.7 s.
#
# That overruns §15's 6 s generation line and fits its 60 s ceiling: 18.7 s to
# generate plus ~11 s to match is ~30 s end to end. The overrun is deliberate and
# stated rather than hidden — a demo that generates fast and then measures a
# different board than the one in the journals is the worse trade.
#
# **Two side findings, recorded and not acted on.** 20M is indistinguishable from
# 40M (3 unproven, 92 verified, 16 ambiguous) at 35 s against 54 s, so the offline
# budget is ~19 s of pure waste; and `verified` plateaus at 92, which means the 42
# lines outside it are not budget-limited at all. Changing the offline budget would
# regenerate the committed board and move every pinned count in the suite, so it is
# a separate decision.
UNIQUENESS_NODE_BUDGET_DEMO = 5_000_000

# `C2_MAX_POOL` is imported above, not declared here. Generation sizes its payouts
# so a window pool stays under it; C2 refuses above it rather than searching. Two
# copies of that number would let the dataset and the matcher disagree about where
# the pigeonhole bound is, and the disagreement would look like a recall result.
DEFAULT_PAYOUTS = 120
DEFAULT_RECORDS = 3_000

# Ambiguity needs a DECOY: a transaction in a line's window pool that its
# composition does not use. With one payout per window there are none — every
# settled transaction in the window belongs to that window's payout, so the pool
# IS the composition and G5 is unreachable. A fraction of windows therefore host a
# second, smaller payout. Two equal-net cross-cycle strays then sit in one window,
# one claimed by each payout, and swapping them leaves both settlements complete —
# the only ambiguity G3 permits. The cycle's record budget is SPLIT between the two
# payouts rather than added to, so the combined pool stays under C2_MAX_POOL.
SHARED_WINDOW_RATE = 0.10
SECOND_PAYOUT_MAX_ITEMS = 8
MAX_PAYOUT_ITEMS = 30       # keeps count + strays under C2_MAX_POOL, so the
                            # pigeonhole bound of §9.3 is never crossed by design

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

# A sticky-priced UPI payment carries no jitter and zero MDR, so two of them have
# IDENTICAL net contributions. On its own this produces no ambiguity at all — the
# swap it enables drops a member from its own settlement, and G3 rejects the
# partial slice (measured at 25x this rate: still zero). It matters only as the
# substrate for the shared-window mechanism above.
STICKY_PRICES = (999_00, 499_00)
STICKY_PRICE_RATE = 0.05

# A cross-cycle refund reverses a product purchase, and product purchases sit on
# catalogue prices — the ±₹5 jitter is the artefact here, not the collision. So
# EVERY cross-cycle refund prefers a catalogue-priced parent, in every window. The
# rule must not be conditional on the window being shared: that would rig the two
# payouts that can produce an ambiguity while leaving every other refund alone.
# Each payout draws independently from the same population; whether two draws
# collide is left to the rng, and the rate is reported rather than targeted.
PREFER_CATALOGUE_REFUND_PARENT = True

REFUND_RATE = 0.06                # share of records that are refunds

# A real payout routinely nets a refund from a prior cycle that was never tagged to
# the settlement batch: `settlement_id = null`, deducted from this payout anyway.
# §9.4's second row exists for exactly this shape — one complete settlement plus one
# or two strays — so it is baseline generation, not an injected break.
CROSS_CYCLE_REFUND_RATE = 0.35    # share of payouts that net one
CROSS_CYCLE_MAX_ITEMS = 2         # §9.4 accepts 1-2 strays, never 3
FX_RATE_MICROS = 83_500_000       # ₹83.50/USD, jittered per transaction

# Narration degradation, §3.4. `drop`/`blank` are what makes a line unparseable by
# regex alone; at high noise they must total ~30%.
NOISE_PROFILES = {
    "low":    {"drop": 0.01, "blank": 0.00, "truncate": 0.04, "transpose": 0.01,
               "collapse": 0.05, "upper": 0.05, "abbrev": 0.05, "ref_no": 0.90},
    "medium": {"drop": 0.07, "blank": 0.03, "truncate": 0.15, "transpose": 0.05,
               "collapse": 0.20, "upper": 0.20, "abbrev": 0.20, "ref_no": 0.55},
    "high":   {"drop": 0.19, "blank": 0.06, "truncate": 0.28, "transpose": 0.08,
               "collapse": 0.45, "upper": 0.45, "abbrev": 0.45, "ref_no": 0.25},
}
