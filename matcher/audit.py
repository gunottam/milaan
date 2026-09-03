"""Phase E — the global audit. §9.7.

Every line can balance individually while the books fail globally. That is
offsetting errors, and it is why accountants run a trial balance instead of trusting
each entry. E1 is that trial balance: one sum over the open bank lines against one
sum over the transactions that should have paid them out.

**E1 is a derivation, not a report.** The per-line analysis can describe a hole —
"this settlement is short by ₹19,980" — but it reaches that number from the line's
own arithmetic. E1 arrives at the same figure from the opposite direction, over the
whole board, with no knowledge of which line was short. When the two agree, the
size of the hole is established twice by independent routes. That is the strongest
check in the project and the reason §16 lists Phase E under "never cut".

**The partition is four-way (finding 8.8), and the two exclusions are the point.**
A transaction that has not settled is not missing, it is not yet due; a member of a
`no_payout_expected` settlement will never be paid out at all (§5.1). Counting
either as unclaimed makes the gap permanently non-zero and the check useless — it
would read as a standing discrepancy that no reconciliation could ever close, and a
number that is always wrong gets ignored.

**Runs on partial results.** §9.10: when the deadline fires, the ladder stops
issuing work and Phase E runs on what was proved.

**And the partial answer is very nearly the whole answer, which stage 10 got wrong.**
Stage 10 marked a deadline-cut run `reconciles = None` on the reasoning that "open
lines nobody looked at have their whole target in the gap". The algebra says
otherwise. Closing a line `L` with composition `C` removes `target(L)` from the open
sum and `Σ net(C)` from the unclaimed sum, so the gap moves by exactly

    Σ net(C) − target(L)  =  the line's own delta

and by nothing else. An exact match therefore leaves the gap **unchanged**, and the
figure is already final before the first tier runs. Measured on seed 42 at the live
budget: the gap before any matching is ₹1,990.90; after 99 closures it is ₹1,991.26,
and the 36-paise difference is precisely the sum of the tolerance deltas of the five
G4 matches. At a 2 s deadline, 79 closures, gap ₹1,991.12, Σδ = 22 paise. Every time.

So the deadline's exposure is not the target of the lines it cut — it is at most
`TOLERANCE_PAISE` per cut line, because §8.2 caps what a single match may absorb at
₹1.00. `reconciles` is `None` only when that band actually swallows the gap; a gap
larger than the band is a hole in the books whether or not the clock ran out, and
saying "indeterminate" there throws away a number we can bound.

**The one caveat, stated because it is the identity's only escape hatch:** the
cancellation holds when the composition was counted in `unclaimed_due`. A claim that
cites an unsettled transaction, or a member of a `no_payout_expected` settlement,
takes it from a bucket the gap never counted, so closing that line moves the gap by
`−target(L)` instead. G1 permits it for an anchor\'s own members (§9.3). Both those
buckets are empty on seed 42, so it cannot arise there; where they are not, the
census is what shows it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from core.models import BankLine, GatewayTxn, target
from core.money import Paise, fmt_inr
from core.subsetsum import TOLERANCE_PAISE

# §9.7's four states, in the order the table gives them. `settled=false` and
# `no_payout_expected` are the two exclusions finding 8.8 exists for.
STATES = ("claimed", "unclaimed_due", "not_yet_due", "no_payout_expected")


def no_payout_settlements(txns: Iterable[GatewayTxn]) -> dict[str, Paise]:
    """§5.1: settlements that will never produce a bank line, and their nets.

    Derived, not read from truth — `matcher/` has no access to it, and would not
    want it: this is the one classification the matcher must be able to make on its
    own, since a real merchant's export does not come with a note saying which
    cycles netted out. The rule is §5.1's, exactly: a settlement whose net is zero
    produces no payout, so it is excluded from the residue denominator and reported
    as its own line.

    Carry-forward negative settlements are classified the same way by §5.1. This
    generator has none — `NEGATIVE_SETTLEMENT` re-credits the cycle as a bank debit
    (finding 8.1's signed target), so every negative settlement here has a line to
    match against. A carry-forward would present as a negative-net settlement with
    no bank line of its own; it is not synthesised here because a rule with no data
    behind it is a rule that has never been run.

    **Measured ceiling on seed 42: this returns nothing, and the gap is right
    anyway.** Both `NET_ZERO_SETTLEMENT` groups net `+₹499` over their *tagged*
    members, because the refund that offsets them is a cross-cycle stray carrying
    `settlement_id = null` — the generator's `Settlement` counts it a member, the
    CSV does not, and the CSV is all the matcher has. The obvious repair, attaching
    a stray to its parent payment's settlement, was tried and rejected: it recovers
    one of the two groups, and it would let any ordinary cross-cycle refund drag an
    unrelated settlement toward zero. A rule that is right half the time about
    which transactions to *remove from the denominator* is worse than no rule.

    The consequence is bounded and it is why E1 still reads correctly: the group
    (`+₹499`) and its stray (`−₹499`) both land in `unclaimed_due` and cancel
    there. The census under-reports this arm; the gap does not move. Truth's
    `settlements` block carries the real classification and scoring may read it —
    this function may not.
    """
    nets: dict[str, Paise] = {}
    for txn in txns:
        if txn.settlement_id is not None:
            nets[txn.settlement_id] = nets.get(txn.settlement_id, 0) + txn.net
    return {sid: net for sid, net in nets.items() if net == 0}


@dataclass(frozen=True)
class Residue:
    """E1. The gap, and the four-way census it came out of.

    `gap = open_lines_paise − unclaimed_due_paise`. Positive means the bank paid
    more than the records account for — money arrived with no source, which is what
    a withheld record looks like from the outside. Negative means the gateway holds
    transactions no bank line collected.
    """

    gap_paise: Paise
    open_lines_paise: Paise
    unclaimed_due_paise: Paise
    open_lines: tuple[str, ...]
    census: Mapping[str, int]
    sums: Mapping[str, Paise]
    unclaimed_due: tuple[str, ...]
    no_payout_expected: tuple[str, ...]
    partial: bool = False
    # The gap as it stood before any line matched — `Σ every bank line` against
    # `Σ every due transaction`. Phase E is computable on an untouched board, and
    # the difference between this and `gap_paise` is the entire contribution the
    # matcher made to the figure.
    baseline_gap_paise: Paise = 0
    # Open bank lines the run\'s clock stopped. Their exposure is bounded by §8.2,
    # not by their targets — see the module docstring.
    cut_lines: tuple[str, ...] = ()

    @property
    def matcher_delta_paise(self) -> Paise:
        """Everything the matcher added to the baseline gap.

        By the identity in the module docstring this is exactly the sum of the
        tolerance deltas of the matches it made — an exact match contributes zero.
        It is therefore a *second* reading of how much G4 absorbed, derived globally
        rather than by adding up verdicts, and the two agree to the paisa.
        """
        return self.gap_paise - self.baseline_gap_paise

    @property
    def deadline_slack_paise(self) -> Paise:
        """The most the clock can still account for: §8.2\'s ₹1.00 cap, per cut line.

        Not the sum of their targets. A line that closes exactly moves the gap by
        zero, so the only way an unfinished line can change this figure is by
        eventually closing on a tolerance match, and G4 will not absorb more than
        `TOLERANCE_PAISE` on any one of them.
        """
        return TOLERANCE_PAISE * len(self.cut_lines)

    @property
    def reconciles(self) -> bool | None:
        """`True` when the gap is zero, `None` when the deadline band could still
        account for all of it, `False` otherwise.

        Three values, but not stage 10\'s three. `None` is now a narrow and earned
        state — the gap is non-zero and smaller than what the unfinished lines could
        still absorb — rather than the blanket "the clock ran, so who knows" that
        discarded a bound we can compute.
        """
        if self.gap_paise == 0:
            return True
        return None if abs(self.gap_paise) <= self.deadline_slack_paise else False

    def composition(self) -> list[str]:
        """What the gap is made of, in sentences a reader can check.

        §13 puts the gap in the header as the global honesty indicator, and an
        indicator nobody can decompose is a number people learn to ignore. Every
        line below is either one of the two sums or a consequence of the identity
        in the module docstring.
        """
        out = [f"    Σ {len(self.open_lines):>4} open bank lines"
               f"{fmt_inr(self.open_lines_paise):>18}",
               f"  − Σ {self.census['unclaimed_due']:>4} unclaimed and due transactions"
               f"{fmt_inr(self.unclaimed_due_paise):>18}"]
        for state in ("claimed", "not_yet_due", "no_payout_expected"):
            out.append(f"      {self.census[state]:>4} {state:<36}"
                       f"{fmt_inr(self.sums[state]):>14}   excluded (§9.7)")
        out.append(
            f"    {fmt_inr(self.baseline_gap_paise)} of this was the gap before any "
            f"line matched; closing a line moves it by")
        out.append(
            f"    that line's own delta and nothing else, so the whole matcher "
            f"contributed {fmt_inr(self.matcher_delta_paise)}.")
        if self.cut_lines:
            out.append(
                f"    {len(self.cut_lines)} lines were cut by the deadline. §8.2 caps "
                f"what one match may absorb at {fmt_inr(TOLERANCE_PAISE)}, so the "
                f"clock can still")
            out.append(
                f"    account for at most {fmt_inr(self.deadline_slack_paise)} of "
                + ("this — the rest is a hole in the books."
                   if self.reconciles is False else
                   "this, which covers the whole gap."))
        if self.no_payout_expected:
            out.append(f"      {len(self.no_payout_expected)} settlements net zero, so "
                       f"no payout is expected (§5.1): "
                       f"{', '.join(self.no_payout_expected[:4])}"
                       + (" …" if len(self.no_payout_expected) > 4 else ""))
        return out

    def lines(self) -> list[str]:
        """The header's honesty indicator (§13), and the census behind it."""
        verdict = ("indeterminate — inside the deadline's tolerance band"
                   if self.reconciles is None
                   else "reconciles" if self.reconciles
                   else "does NOT reconcile")
        return [f"  residue gap {fmt_inr(self.gap_paise)}   {verdict}",
                *self.composition()]


def residue_gap(txns: Sequence[GatewayTxn], bank_lines: Sequence[BankLine],
                matched: Iterable[str], claimed: Iterable[str], *,
                partial: bool = False,
                cut_lines: Iterable[str] = ()) -> Residue:
    """E1: `Σ open bank lines` against `Σ unclaimed-and-due transactions`.

    `matched` is the set of closed `bank_line_id`s; `claimed` the set of entity ids
    their compositions consumed. Both are passed in rather than recomputed, because
    a second derivation of "what did the ladder claim" is a second thing that can
    disagree with the ladder.

    The four states are evaluated in §9.7's order and they are exclusive: a claimed
    transaction is claimed even if its settlement nets zero, because it demonstrably
    paid out. Order matters for the census only — the gap reads one bucket.
    """
    closed = set(matched)
    spent = set(claimed)
    zero_net = no_payout_settlements(txns)

    buckets: dict[str, list[GatewayTxn]] = {state: [] for state in STATES}
    for txn in txns:
        if txn.entity_id in spent:
            state = "claimed"
        elif not txn.settled:
            state = "not_yet_due"
        elif txn.settlement_id in zero_net:
            state = "no_payout_expected"
        else:
            state = "unclaimed_due"
        buckets[state].append(txn)

    open_lines = tuple(sorted(b.bank_line_id for b in bank_lines
                              if b.bank_line_id not in closed))
    open_sum = sum(target(b) for b in bank_lines if b.bank_line_id in set(open_lines))
    due_sum = sum(t.net for t in buckets["unclaimed_due"])

    # The same subtraction with `claimed` empty: what the gap was before the ladder
    # ran. Computed here rather than by the caller so the two sums are formed by one
    # piece of code and cannot drift into disagreeing about the partition.
    baseline_due = sum(t.net for t in txns
                       if t.settled and t.settlement_id not in zero_net)
    baseline_open = sum(target(b) for b in bank_lines)

    cut = tuple(sorted(set(cut_lines) & set(open_lines)))
    return Residue(
        gap_paise=open_sum - due_sum,
        baseline_gap_paise=baseline_open - baseline_due,
        cut_lines=cut,
        open_lines_paise=open_sum,
        unclaimed_due_paise=due_sum,
        open_lines=open_lines,
        census={state: len(items) for state, items in buckets.items()},
        sums={state: sum(t.net for t in items) for state, items in buckets.items()},
        unclaimed_due=tuple(sorted(t.entity_id for t in buckets["unclaimed_due"])),
        no_payout_expected=tuple(sorted(zero_net)),
        partial=partial,
    )


@dataclass(frozen=True)
class Split:
    """E2. One settlement whose transactions ended up on more than one bank line,
    or one accepted match that spans more than one settlement.

    Both are `SETTLEMENT_CONTAMINATION` in the ledger and both are *flags for human
    confirmation*, not errors: §9.4 accepts a whole settlement plus one or two
    strays, and `SPLIT_PAYOUT` is a real break in which one settlement legitimately
    reaches the bank as two lines. The audit's job is to say it happened, because
    an approved match that quietly spans two settlements is the shape a
    mis-tagged transaction takes after it has been absorbed.
    """

    settlement_id: str
    bank_line_ids: tuple[str, ...]
    entity_ids: tuple[str, ...]
    kind: str          # "settlement_split_across_lines" | "line_spans_settlements"

    @property
    def sentence(self) -> str:
        if self.kind == "settlement_split_across_lines":
            return (f"{self.settlement_id} paid out across "
                    f"{len(self.bank_line_ids)} bank lines "
                    f"({', '.join(self.bank_line_ids)}); confirm the split is real")
        return (f"{self.bank_line_ids[0]} draws {len(self.entity_ids)} transactions "
                f"from {self.settlement_id}, which is not its own settlement group; "
                "confirm the tagging")


def coherence_audit(compositions: Mapping[str, Sequence[str]],
                    txns: Mapping[str, GatewayTxn]) -> list[Split]:
    """E2: flag settlements split across bank lines, and matches spanning groups.

    G3 already refused the shapes that are not payouts at all (§9.4). What is left
    is the shapes G3 *accepts* and a human should still see — which is exactly why
    this is an audit and not a gate: rejecting them would cost recall on
    `SPLIT_PAYOUT` and on every payout that nets a legitimate cross-cycle stray.
    """
    lines_of: dict[str, set[str]] = {}
    for bank_line_id, composition in compositions.items():
        for entity_id in composition:
            settlement_id = txns[entity_id].settlement_id
            if settlement_id is not None:
                lines_of.setdefault(settlement_id, set()).add(bank_line_id)

    found = [Split(settlement_id, tuple(sorted(ids)),
                   tuple(sorted(e for e in txns
                                if txns[e].settlement_id == settlement_id)),
                   "settlement_split_across_lines")
             for settlement_id, ids in sorted(lines_of.items()) if len(ids) > 1]

    # The other direction: one line drawing from several groups. The *minority*
    # group is the flagged one — a payout is one whole settlement plus strays, so
    # the group contributing fewest items is the contamination, not the payout.
    for bank_line_id, composition in sorted(compositions.items()):
        groups: dict[str, list[str]] = {}
        for entity_id in composition:
            settlement_id = txns[entity_id].settlement_id
            if settlement_id is not None:
                groups.setdefault(settlement_id, []).append(entity_id)
        if len(groups) < 2:
            continue
        majority = max(groups, key=lambda s: (len(groups[s]), s))
        for settlement_id, entity_ids in sorted(groups.items()):
            if settlement_id != majority:
                found.append(Split(settlement_id, (bank_line_id,),
                                   tuple(sorted(entity_ids)),
                                   "line_spans_settlements"))
    return found
