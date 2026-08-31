"""§10.2's delta diagnostics. Six cheap arithmetic checks on an unclosed residual.

When a line fails to close, the residual is usually not a mystery — it is a term
somebody forgot. TDS is 0.1% of gross, GST is 18% of the fee, the instant premium is
₹25 flat. Each of those is a *specific number*, and testing the residual against it
converts a bare gap into a typed exception with a named cause. Exception typing is a
scored metric (§11), so this is a headline number for the price of six comparisons.

**Nothing here approves anything.** A diagnosis is a sentence about a gap, not a
composition and not a verdict — the only thing in the codebase that can approve is
`verify.check()` (I2). `allocation_remainder` says "retry via G4" and does not retry;
G4 already ran, and if it declined the answer is a refusal with an explanation.

**No rate multiplication.** I1 confines `Decimal` to `core/fees.py`, so every figure
compared here is read off the transactions (`tds_paise`, `tax_paise`) or obtained
from `core.fees` (`gst_on`, `expected_fee`). The per-transaction sums are also the
*correct* comparison: rounding is per transaction, never on an aggregate, so
`Σ round(amount × 0.001)` and `round(Σ amount × 0.001)` are different numbers and
only the first is what the books hold.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from core.fees import INSTANT_FLAT, expected_fee, gst_on
from core.models import GatewayTxn
from core.money import Paise

# §10 calls this field `delta_diagnosis`, and its example value is
# `no_matching_residual` — the honest default. §17: we can name the settlement and
# the gap, never the missing record. When none of the six fire, that is the answer,
# and it is a finding rather than a failure to look.
UNDIAGNOSED = "no_matching_residual"


@dataclass(frozen=True)
class Diagnosis:
    """One named cause for one residual.

    `candidate_entity_id` is set only by the fifth check, which is the sole
    diagnosis that can point at a specific record. Everything else names a *term*.
    """

    code: str
    detail: str
    candidate_entity_id: str | None = None

    @property
    def diagnosed(self) -> bool:
        return self.code != UNDIAGNOSED


def _payments(chosen: Sequence[GatewayTxn]) -> list[GatewayTxn]:
    """§4.2: the recompute check applies to payments only. Everything else carries
    `fee_paise = 0` by construction, so summing fees over refunds reports nothing."""
    return [t for t in chosen if t.type == "payment"]


def _fx_markup(txn: GatewayTxn) -> Paise:
    """The FX component of one transaction's fee — §10.2's "3% − 2% of gross".

    Derived as the difference the flag makes rather than as a literal 1%: FX_MARKUP
    folds into `fee_paise` (I7) and is never a separate term, so the only honest way
    to ask "what did the markup cost" is to recompute the fee without it. That also
    keeps the rate itself in `core/fees.py` where I1 requires it.
    """
    if not txn.international:
        return 0
    return expected_fee(txn)[0] - expected_fee(replace(txn, international=False))[0]


def diagnose(delta: Paise, composition: Iterable[str],
             txns: Mapping[str, GatewayTxn],
             unclaimed: Iterable[GatewayTxn] = ()) -> Diagnosis:
    """Name the cause of `delta`, or return `UNDIAGNOSED`.

    `delta` is G2's residual, `Σ net(composition) − target(line)`. A positive delta
    means the gateway accounts for more than the bank paid; negative means money
    arrived that the records do not explain. The checks compare magnitudes and the
    detail line carries the sign, because a missing TDS term and a doubled one
    produce the same |δ| and a human reads them differently.

    `composition` may be empty — a line nothing could compose still has a residual
    (its whole target), and check five is the one that can still say something about
    it. On a `WITHHELD_RECORD` it deliberately says nothing: the record is absent
    from the export, so no unclaimed net matches, and `no_matching_residual` is the
    correct and complete answer (§17).

    The order is §10.2's, top to bottom, first hit wins.
    """
    if delta == 0:
        return Diagnosis("balanced", "residual is zero")

    chosen = [txns[e] for e in composition]
    size = len(chosen)
    d = abs(delta)
    payments = _payments(chosen)

    # 1. δ = 0.1% of composition gross. Summed per transaction, already rounded.
    tds = sum(t.tds_paise for t in payments)
    if tds and d == tds:
        return Diagnosis(
            "tds_term_missing",
            f"{delta:+d} paise equals the {tds} paise of TDS u/s 194-O carried by "
            f"{len(payments)} payments; the matcher's target ignores a withheld term")

    # 2. δ = 18% of the computed fee.
    gst = sum(t.tax_paise for t in payments)
    if gst and d == gst:
        return Diagnosis(
            "gst_not_applied",
            f"{delta:+d} paise equals the {gst} paise of GST @ 18% on MDR across "
            f"{len(payments)} payments; the fee was deducted and its tax was not")

    # 3. δ = ₹25 flat, or ₹25 + GST. §4.3 allocates the premium, so a whole
    #    unallocated premium is the signature of an off-cycle instant settlement.
    for amount, label in ((INSTANT_FLAT, "the ₹25 instant-settlement premium"),
                          (INSTANT_FLAT + gst_on(INSTANT_FLAT),
                           "the ₹25 instant-settlement premium plus GST")):
        if d == amount:
            return Diagnosis("instant_settlement_premium",
                             f"{delta:+d} paise is exactly {label} ({amount} paise), "
                             "unallocated")

    # 4. δ ≤ len(composition), in paise — §4.3's dropped allocation remainder,
    #    bounded by n − 1. Note this is *unreachable for a claim that reached G4*:
    #    §8.2 accepts iff |δ| ≤ 100 AND |δ| ≤ n, so any rejected claim with |δ| ≤ n
    #    must have |δ| > 100, which needs a composition of over a hundred items and
    #    §15 caps payouts far below that. It fires on residuals that never met a
    #    gate — an open line's own target against the pool — and that is why it is
    #    kept rather than folded into G4.
    if size and d <= size:
        return Diagnosis(
            "allocation_remainder",
            f"{delta:+d} paise over {size} transactions is within §4.3's dropped "
            f"remainder of at most {size - 1} paise; retry via G4")

    # 5. δ equals some unclaimed transaction's net. The only check that can name a
    #    record — and §17's limit sits right here: two withheld transactions
    #    summing to the same figure are indistinguishable, so every match is
    #    reported as *a* candidate, never as *the* answer.
    named = sorted({t.entity_id for t in unclaimed if abs(t.net) == d})
    if named:
        first = named[0]
        more = f" (and {len(named) - 1} others of the same net)" if len(named) > 1 else ""
        return Diagnosis(
            "likely_specific_missing_record",
            f"{delta:+d} paise equals the net of unclaimed {first}{more}; a "
            "candidate for the gap, not a proof of it",
            candidate_entity_id=first)

    # 6. δ = 3% − 2% of a transaction's gross — the FX markup left out of the fee.
    for txn in payments:
        if d == _fx_markup(txn):
            return Diagnosis(
                "fx_markup_not_applied",
                f"{delta:+d} paise equals the FX markup on {txn.entity_id} "
                f"({txn.method}, {txn.source_currency or 'foreign'}); the markup "
                "folds into fee_paise (I7) and this target omits it")

    return Diagnosis(
        UNDIAGNOSED,
        f"{delta:+d} paise matches no fee, tax, premium, remainder or unclaimed "
        "net; nothing in the input accounts for it")
