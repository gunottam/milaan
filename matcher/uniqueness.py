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


def finalists(passing: Sequence[tuple[Claim, Verdict]]
              ) -> list[tuple[Claim, Verdict]]:
    """The approved pairs at the smallest `|delta|`, which is what G5 judges.

    Exposed because two callers need the same rule and a second copy of it would
    be a copy of the tie-break: `resolve` decides, and the exception ledger needs
    the tied compositions themselves to split `AMBIGUOUS_EQUIVALENT` from
    `AMBIGUOUS_CONSEQUENTIAL` (§10.1). A refusal that reported only "2 tie" would
    force the ledger to guess which two.

    Exact beats tolerance: §9.3 takes the minimum `|delta|` and refuses only on
    ties *at that minimum*. A delta-0 answer and a delta-2 answer do not tie — one
    is arithmetic and the other is a relaxation of it.
    """
    approved = [(claim, verdict) for claim, verdict in passing if verdict.ok]
    if not approved:
        return []
    best = min(abs(verdict.delta_paise) for _, verdict in approved)
    return [(c, v) for c, v in approved if abs(v.delta_paise) == best]


def resolve(passing: Sequence[tuple[Claim, Verdict]]
            ) -> tuple[Claim | None, Verdict | None]:
    """The single surviving `(claim, verdict)` for a line, or a G5 refusal.

    - `(None, None)` — nothing passed the gate chain. Not G5's business.
    - `(None, refusal)` — two or more distinct compositions tie. Refuse.
    - `(claim, verdict)` — one answer survives.

    Distinctness is set equality on the composition (I5), so the same set proposed
    by two proposers is one answer, not a tie; the first pair is returned, which
    under tier-major ordering is the earliest tier's.

    Exact beats tolerance — see `finalists`, which is where that rule lives.
    """
    tied = finalists(passing)
    if not tied:
        return None, None

    best = abs(tied[0][1].delta_paise)
    distinct = {frozenset(claim.composition) for claim, _ in tied}
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
    return tied[0]
