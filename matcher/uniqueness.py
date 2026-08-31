"""G5 uniqueness. §7.3 — a predicate over the *set* of passing verdicts for one
bank line, not part of `check()`.

Different arity, kept in a different file so that is visible. G5 never approves
anything: it withdraws approval when two distinct compositions tie. Nothing here
can turn a rejection into a match.
"""

from __future__ import annotations

from collections.abc import Sequence

from matcher.proposers.base import Claim
from matcher.verify import Verdict


def resolve(passing: Sequence[tuple[Claim, Verdict]]
            ) -> tuple[Claim | None, Verdict | None]:
    """The single surviving `(claim, verdict)` for a line, or a G5 refusal.

    - `(None, None)` — nothing passed the gate chain. Not G5's business.
    - `(None, refusal)` — two or more distinct compositions tie. Refuse.
    - `(claim, verdict)` — one answer survives.

    Distinctness is set equality on the composition (I5), so the same set proposed
    by two proposers is one answer, not a tie; the first pair is returned, which
    under tier-major ordering is the earliest tier's.

    Exact beats tolerance: §9.3 takes the minimum `|delta|` and refuses only on ties
    *at that minimum* with different sets. A delta-0 answer and a delta-2 answer do
    not tie — one of them is arithmetic and the other is a relaxation of it.
    """
    approved = [(claim, verdict) for claim, verdict in passing if verdict.ok]
    if not approved:
        return None, None

    best = min(abs(verdict.delta_paise) for _, verdict in approved)
    finalists = [(c, v) for c, v in approved if abs(v.delta_paise) == best]
    distinct = {frozenset(claim.composition) for claim, _ in finalists}
    if len(distinct) > 1:
        return None, Verdict(
            ok=False, gate="G5",
            reason=f"{len(distinct)} compositions tie at {best} paise",
            proof=None, confidence=None,
            # The magnitude the finalists tied at — the only figure common to them.
            delta_paise=best,
            # G4's outcome belongs to a claim, and this refusal belongs to a set.
            tolerance=None,
        )
    return finalists[0]
