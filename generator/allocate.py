"""§4.3 allocation — the mechanism behind ROUNDING_DRIFT."""

from __future__ import annotations

from core.models import GatewayTxn
from core.money import Paise


def allocate(total: Paise, txns: list[GatewayTxn]) -> dict[str, Paise]:
    """Even split; the `total % n` remainder is DELIBERATELY discarded.

    The dropped remainder is at most `n − 1` paise — a bounded, explainable drift
    between the sum of allocated figures and the bank credit, and exactly what
    G4's tolerance band exists to catch. Without allocation the drift is
    identically zero and the break is a no-op.
    """
    per = total // len(txns)
    return {t.entity_id: per for t in txns}
