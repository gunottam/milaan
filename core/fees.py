"""Fee, tax and allocation. §4 of the spec.

The only module permitted to use `Decimal` for rate multiplication (I1).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from core.money import Paise, round_paise

MDR_BY_METHOD = {
    "upi": Decimal("0.0000"), "rupay_debit": Decimal("0.0000"),
    "card": Decimal("0.0200"), "netbanking": Decimal("0.0200"),
    "wallet": Decimal("0.0200"), "emi": Decimal("0.0300"),
    "intl_card": Decimal("0.0300"),
}
GST_ON_FEE = Decimal("0.18")
TDS_194O = Decimal("0.001")     # 0.1% since Oct 2024. CONFIG — verify before demo day
TCS_GST = Decimal("0.005")      # marketplace TCS, off by default
FX_MARKUP = Decimal("0.0100")   # folded into fee_paise, never a separate term (I7)
INSTANT_FLAT = 25_00            # ₹25 per instant settlement, allocated per §4.3


class Txn(Protocol):
    entity_id: str
    method: str
    amount_paise: Paise
    international: bool


def expected_fee(txn: Txn) -> tuple[Paise, Paise, Paise]:
    """(fee, tax, tds). Payments only — everything else carries fee_paise = 0.

    GST is taken on the already-rounded fee. Reversing that order makes
    ROUNDING_DRIFT unfireable.
    """
    rate = MDR_BY_METHOD[txn.method] + (FX_MARKUP if txn.international else Decimal(0))
    fee = round_paise(txn.amount_paise * rate)
    tax = round_paise(fee * GST_ON_FEE)
    tds = round_paise(txn.amount_paise * TDS_194O)
    return fee, tax, tds


def allocate(total: Paise, txns: list[Txn]) -> dict[str, Paise]:
    """Even split; the `total % n` remainder is DELIBERATELY discarded (§4.3).

    That dropped remainder is the ROUNDING_DRIFT break and what G4's band catches.
    """
    per = total // len(txns)
    return {t.entity_id: per for t in txns}
