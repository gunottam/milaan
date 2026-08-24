"""Money and time primitives. §2 of the spec.

All money is `int` paise (I1). `Decimal` appears here only to be rounded away;
rate multiplication lives in `core/fees.py`.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

Paise = int

IST = timezone(timedelta(hours=5, minutes=30), "IST")


def round_paise(d: Decimal | int) -> Paise:
    """The only rounding function. ROUND_HALF_UP, never `round()` (banker's)."""
    return int(Decimal(d).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def to_paise(rupees: str | Decimal) -> Paise:
    return round_paise(Decimal(rupees) * 100)


def fmt_inr(p: Paise) -> str:
    """4619388 -> '₹46,193.88'. Indian grouping: last 3 digits, then pairs."""
    sign = "-" if p < 0 else ""
    whole, frac = divmod(abs(p), 100)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = [head[max(i - 2, 0):i] for i in range(len(head), 0, -2)]
        s = ",".join(reversed(groups)) + "," + tail
    return f"₹{sign}{s}.{frac:02d}"


def ist_date(value: str | datetime | date) -> date:
    """IST calendar date. A UTC timestamp is converted, never truncated."""
    if isinstance(value, datetime):
        return value.astimezone(IST).date()
    if isinstance(value, date):
        return value
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.date()
    return parsed.astimezone(IST).date()


def window_key(value_date: str | date | None, txn_date: str | date) -> date:
    """§2: the window key is `value_date`, falling back to `txn_date`."""
    return ist_date(value_date or txn_date)


def in_window(d: date, anchor: date, window_days: int) -> bool:
    """`[anchor − window_days, anchor]`, inclusive, on the IST calendar date."""
    return anchor - timedelta(days=window_days) <= d <= anchor
