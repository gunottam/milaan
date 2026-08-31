"""Phase A — identifier recovery. §9.1, and the prefix cascade of §9.5.

Three tiers over one implementation, because they differ only in how a settlement
id is recovered from text:

    A1  a clean UTR in `ref_no` or the narration, exact
    A2  a `setl_*` token in the narration
    A3  a truncated or alternate-format fragment, resolved by prefix — §9.5

**Phase A selects a candidate set. It does not establish a match** (§9.1). A
recovered identifier says which settlement to try and nothing more: the claim walks
the same four gates a subset-sum candidate does, so a wrong id means the wrong set
was grabbed and G2 drops it (I8, and `bl_06` of `docs/workflow.md`).

§9.5's cascade is four filters — prefix, date window, exclusivity, arithmetic — and
only the first is implemented here. The other three already exist: the window and
exclusivity are G1, the arithmetic is G2, and "2+ survivors" is G5. A tier that
filtered on its own arithmetic would be a second, unaudited copy of the gate chain.

Settlement membership is read out of the gateway export — `settlement_id` and
`settlement_utr` are columns — so nothing here reaches into the generator.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from core.models import BankLine, GatewayTxn, settlement_members
from matcher.proposers.base import Claim, Pool

# `N` + bank code + yymmdd + sequence, and the same thing with the leading N gone,
# which is how the UPI narration template carries it.
FRAGMENT_RX = re.compile(r"N?[A-Z]{2,6}\d{2,}")
SETL_RX = re.compile(r"setl_[A-Za-z0-9]+", re.IGNORECASE)

MIN_FRAGMENT = 5     # §3.4 truncates to 5-8 characters; below that a prefix is noise


class RegexProposer:
    """A1, A2 or A3 depending on `tier`. Tier-major ordering (§9.8) runs every line
    through one instance before any line reaches the next, so the tiers are separate
    objects rather than one pass with three branches."""

    def __init__(self, tier: str, txns: Iterable[GatewayTxn]) -> None:
        self.name = tier
        txns = list(txns)
        self.members = settlement_members(txns)
        self._utr = {t.settlement_id: t.settlement_utr for t in txns
                     if t.settlement_id is not None and t.settlement_utr}

    def propose(self, line: BankLine, pool: Pool) -> list[Claim]:
        """`pool` is unused: once an identifier is recovered, membership is a fact
        rather than an inference (§9.3), and G1 exempts the anchor's own members
        from the window for exactly that reason."""
        if self.name == "A2":
            found = self._by_token(line)
        else:
            found = self._by_utr(line)
        return [self._claim(line, sid) for sid in sorted(found)]

    # --- the three recovery routes -------------------------------------------

    def _by_token(self, line: BankLine) -> set[str]:
        """A2. A settlement id written into the narration outright."""
        return {token.lower() for token in SETL_RX.findall(line.narration)
                if token.lower() in self.members}

    def _by_utr(self, line: BankLine) -> set[str]:
        """A1 exact, or A3 by prefix. A1's hits are excluded from A3 — the tier
        already tried them, and re-proposing a set G2 rejected changes nothing."""
        found: set[str] = set()
        for fragment in self._fragments(line):
            exact = {sid for sid, utr in self._utr.items()
                     if fragment in (utr, utr[1:])}
            if self.name == "A1":
                found |= exact
                continue
            if exact:
                continue
            found |= self._prefix(fragment)
        return found

    def _prefix(self, fragment: str) -> set[str]:
        """§9.5 filter 1. Every settlement from one bank on one day shares a long
        prefix by construction, so this set is routinely large — filters 2 to 4 are
        G1 and G2, and 2+ survivors is a G5 refusal.

        ponytail: a linear scan over ~120 settlements per fragment. A trie or a
        sorted-list bisect is the upgrade if the settlement count ever reaches the
        thousands.
        """
        return {sid for sid, utr in self._utr.items()
                if utr.startswith(fragment) or utr[1:].startswith(fragment)}

    def _fragments(self, line: BankLine) -> list[str]:
        """Candidate identifier tokens, longest first, deduplicated.

        I10 does not apply — `narration` and `ref_no` are bank-authored columns, not
        the merchant free text that never enters a prompt.
        """
        text = f"{line.ref_no or ''} {line.narration}".upper()
        seen = {f for f in FRAGMENT_RX.findall(text) if len(f) >= MIN_FRAGMENT}
        return sorted(seen, key=lambda f: (-len(f), f))

    def _claim(self, line: BankLine, settlement_id: str) -> Claim:
        # `window_days=0`: every cited entity belongs to the anchor settlement, and
        # G1 exempts those from the window test, so no window is being asserted.
        return Claim(line.bank_line_id, self.members[settlement_id],
                     anchor_settlement_id=settlement_id, window_days=0)
