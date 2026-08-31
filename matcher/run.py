"""The ladder: run every line through one tier before any line reaches the next.

Tier-major ordering, propagation passes and the run-level deadline are §9.8/§9.10
and belong to stage 9. This is the smallest driver that can measure a tier —
single pass, lines in `bank_line_id` order, no deadline — lifted out of
`tests/test_phase_ab.py` when the scoreboard became its second caller. Stage 9
replaces the body; the signature is what scoring reads.
"""

from __future__ import annotations

from collections.abc import Sequence

from core.models import BankLine, GatewayTxn, window_pool
from matcher.proposers.base import Claim
from matcher.proposers.lookup_p import LookupProposer
from matcher.proposers.regex_p import RegexProposer
from matcher.uniqueness import resolve
from matcher.verify import Verdict, check

Matched = dict[str, tuple[str, Claim, Verdict]]


def run_ladder(txns: Sequence[GatewayTxn], bank_lines: Sequence[BankLine],
               window_days: int = 2) -> tuple[Matched, list[dict]]:
    """A1 → A2 → A3 → B1 → B2. Returns `(matched, trace)`.

    `matched` is `bank_line_id -> (tier, winning claim, verdict)`; the tier name is
    the match's `source` and lives here rather than on the `Claim` (I9). Each trace
    entry records one line's encounter with one tier, including the settlement ids
    that tier proposed as anchors — §9.1's amendment scores anchors recovered
    beside lines closed.
    """
    by_id = {t.entity_id: t for t in txns}
    b1 = LookupProposer("B1", txns, window_days)
    tiers = [RegexProposer("A1", txns), RegexProposer("A2", txns),
             RegexProposer("A3", txns), b1, LookupProposer("B2", txns, window_days)]
    claimed: set[str] = set()
    matched: Matched = {}
    trace: list[dict] = []

    for tier in tiers:
        for line in sorted(bank_lines, key=lambda l: l.bank_line_id):
            if line.bank_line_id in matched:
                continue
            pool = window_pool(line, txns, window_days, frozenset(claimed))
            claims = tier.propose(line, pool)
            if not claims:
                continue
            verdicts = [(claim, check(claim, line, by_id, claimed)) for claim in claims]
            won, verdict = resolve(verdicts)
            trace.append({
                "line": line.bank_line_id, "tier": tier.name,
                "candidates": len(claims), "won": won is not None,
                "stale": sum(1 for _, v in verdicts if v.gate == "G1"
                             and "already claimed" in (v.reason or "")),
                "refused": won is None and verdict is not None,
                "anchors": sorted({c.anchor_settlement_id for c in claims
                                   if c.anchor_settlement_id}),
            })
            if won is None:
                continue
            matched[line.bank_line_id] = (tier.name, won, verdict)
            claimed |= set(won.composition)
            if won.anchor_settlement_id:
                b1.release(won.anchor_settlement_id)
    return matched, trace
