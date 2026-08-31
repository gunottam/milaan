"""The exception ledger. §10.

Every line the ladder did not close leaves a record here, and the record has to be
useful to a human in the next minute of their working day. §10 sets the bar as one
sentence: **`blocked_on` must name the missing input. "Could not match" is not
acceptable output.** Everything else in this module exists to earn that sentence —
the type, the diagnosis, the evidence tokens and the price.

Four inputs, one output. The ladder's trace says what was tried and what tied, Phase
E's coherence audit says which settlements were split, the delta diagnostics
(§10.2) name the arithmetic cause, and the orders file supplies §3.3's tie-out. None
of them is `truth.json`, which is not reachable from `matcher/` — the ledger derives
`AMBIGUOUS_EQUIVALENT` from the book shapes of the tied compositions themselves
(§10.1), by the same rule the generator used to stamp `ambiguity_class`. Exception
typing is a scored metric, and a ledger that could read the answer key would not be
measuring anything.

**Nothing here approves.** An accepted `unresolvable` is still not a match (§9.6), so
I4 holds and I2 is untouched: `Verdict` is not imported in this file.

**Reproducible ageing.** `age_days` is measured from the statement's own last value
date, not from the clock. §11 keeps machine-dependent numbers off the board, and a
ledger that aged by `today()` would render different bytes tomorrow for the same
input.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from core.coherence import book_shape
from core.models import BankLine, GatewayTxn, Order, settlement_members, target
from core.money import Paise, fmt_inr, window_key
from matcher.audit import Split, no_payout_settlements
from matcher.diagnose import diagnose

# §10's `age_bucket`. The example — `age_days: 6, age_bucket: "3-7d"` — pins the
# second boundary; the rest follow a settlement cycle, a week and a month.
AGE_BUCKETS = ((2, "0-2d"), (7, "3-7d"), (30, "8-30d"), (None, ">30d"))

# §10.2's sorting. Three tiers: the two types that cost money and need
# investigation, then everything else, then the documentation task last.
FIRST = ("WITHHELD_RECORD", "AMBIGUOUS_CONSEQUENTIAL")
LAST = ("AMBIGUOUS_EQUIVALENT",)


def reversal_pairs(bank_lines: Sequence[BankLine],
                   open_lines: Iterable[str]) -> dict[str, str]:
    """§3.2's reversal-pair rule: `bank_line_id -> the line that reverses it`.

    `DUPLICATE_CREDIT` is detected by its T+1 reversal — equal magnitude, opposite
    sign, adjacent calendar day. **The balance column cannot detect it**: a
    duplicate posting is a real posting and the balance includes it, which is why
    §3.2 spends a sentence saying so and why `balance_paise` is marked
    presentational only.

    Narration similarity is the fourth signal §3.2 names and it is not used. At
    `--noise high` roughly 30% of narrations are unparseable by regex (§3.4), so a
    string comparison would drop the pairs it is needed on most; the first three
    conditions are already tight enough that a false pair needs two unrelated
    payouts of *identical* magnitude on consecutive days.

    Only open lines are considered. A closed line has a balanced proof against real
    transactions, and reversing that on a coincidence of amount and date would
    withdraw a match no gate rejected.
    """
    candidates = [b for b in bank_lines if b.bank_line_id in set(open_lines)]
    found: dict[str, str] = {}
    for line in candidates:
        if line.bank_line_id in found:
            continue
        day = window_key(line.value_date, line.txn_date)
        for other in candidates:
            if other.bank_line_id in found or other is line:
                continue
            if (target(other) == -target(line) and target(line) != 0
                    and abs((window_key(other.value_date, other.txn_date)
                             - day).days) <= 1):
                found[line.bank_line_id] = other.bank_line_id
                found[other.bank_line_id] = line.bank_line_id
                break
    return found


def age_bucket(age_days: int) -> str:
    return next(label for limit, label in AGE_BUCKETS
                if limit is None or age_days <= limit)


@dataclass(frozen=True)
class LedgerException:
    """One row of §10's ledger. `bank_line_id` is `None` for `ORPHAN_ORDER`, which
    is an ERP-side break with no bank line to sit on (§3.3)."""

    exception_id: str
    bank_line_id: str | None
    exception_type: str
    type_confidence: str
    amount_at_risk_paise: Paise
    delta_diagnosis: str
    age_days: int
    age_bucket: str
    blocked_on: str
    proposed_action: Mapping[str, str]
    hypotheses_tried: int
    evidence: tuple[str, ...] = ()
    settlement_id: str | None = None
    # The gap this line could size on its own, signed, or `None` when it could
    # not. Only an anchored line can size one: without a settlement id there is
    # nothing to subtract the credit from, and §9.7's global sum is then the only
    # thing that knows how big the hole is. Kept apart from
    # `amount_at_risk_paise`, which is the whole credit and a different number.
    residual_paise: Paise | None = None

    def as_dict(self) -> dict:
        return {
            "exception_id": self.exception_id,
            "bank_line_id": self.bank_line_id,
            "exception_type": self.exception_type,
            "type_confidence": self.type_confidence,
            "amount_at_risk_paise": self.amount_at_risk_paise,
            "delta_diagnosis": self.delta_diagnosis,
            "age_days": self.age_days, "age_bucket": self.age_bucket,
            "evidence": list(self.evidence),
            "blocked_on": self.blocked_on,
            "proposed_action": dict(self.proposed_action),
            "hypotheses_tried": self.hypotheses_tried,
            "settlement_id": self.settlement_id,
            "residual_paise": self.residual_paise,
        }


@dataclass
class _Draft:
    """A record under construction. Mutable on purpose — the typing rules append
    evidence as they establish it, and `type_confidence` is a count of what they
    managed to establish rather than a number anybody chose."""

    bank_line_id: str | None
    exception_type: str
    amount_at_risk_paise: Paise
    age_days: int
    blocked_on: str
    proposed_action: Mapping[str, str]
    hypotheses_tried: int = 0
    delta_diagnosis: str = "not_applicable"
    evidence: list[str] = field(default_factory=list)
    # Independent facts established from the input that corroborate the *typing*.
    # Counted apart from `evidence` because not every sentence worth printing is
    # one: "the gap can be sized, not attributed" and the deadline caveat are
    # statements about the limits of the finding, and raising confidence on the
    # strength of an admission is exactly the failure §10 guards against by
    # forbidding a model-produced float.
    tokens: int = 0
    settlement_id: str | None = None
    machine_dependent: bool = False
    residual_paise: Paise | None = None


def _confidence(draft: _Draft) -> str:
    """§10: `high` / `medium` / `low`, from how many independent evidence tokens
    corroborate the typing — **never a model-produced float.**

    A token is one thing established from the input: a recovered settlement id, a
    named delta diagnosis, a count of tied compositions, a settlement total that
    does not close. Three or more agreeing facts is `high`; one is a guess with a
    label on it. An unanchored line whose residual matches nothing therefore comes
    out `low`, which is the correct reading — the type is a residual class and
    nothing in the input positively argues for it.

    `machine_dependent` overrides to `low` regardless of the count. An
    `EXCEEDED_SEARCH_BUDGET` typing is a statement about this box's clock, not about
    the data (§11), and corroborating it three ways would not make it hold on a
    faster machine.
    """
    if draft.machine_dependent:
        return "low"
    return "high" if draft.tokens >= 3 else "medium" if draft.tokens == 2 else "low"


def _sort_key(draft: _Draft) -> tuple:
    """§10.2's ordering: `WITHHELD_RECORD` and `AMBIGUOUS_CONSEQUENTIAL` first by
    amount descending, `AMBIGUOUS_EQUIVALENT` last because it is a documentation
    task, everything else between. `bank_line_id` makes the order total, which is
    what makes the rendered ledger reproducible."""
    tier = (0 if draft.exception_type in FIRST
            else 2 if draft.exception_type in LAST else 1)
    return (tier, -draft.amount_at_risk_paise, draft.bank_line_id or "")


@dataclass(frozen=True)
class Ledger:
    """The typed, priced, aged ledger, plus the two counters §10.1 asks for."""

    exceptions: tuple[LedgerException, ...]
    as_of: date
    malformed_hypotheses: int
    splits: tuple[Split, ...]

    @property
    def at_risk_paise(self) -> Paise:
        return sum(e.amount_at_risk_paise for e in self.exceptions)

    def by_type(self) -> dict[str, list[LedgerException]]:
        out: dict[str, list[LedgerException]] = {}
        for exc in self.exceptions:
            out.setdefault(exc.exception_type, []).append(exc)
        return out

    def sized(self, *types: str) -> tuple[int, Paise]:
        """`(how many rows sized their own gap, what those gaps total)`.

        A line that recovered no settlement id cannot size anything — §9.1: without
        an anchor there is no group total to hold the credit against. Those rows
        are the ones Phase E's global sum exists for, and counting them here as
        zero would hide that.
        """
        rows = [e for e in self.exceptions
                if e.exception_type in types and e.residual_paise is not None]
        return len(rows), sum(e.residual_paise for e in rows)

    def total_for(self, *types: str) -> Paise:
        return sum(e.amount_at_risk_paise for e in self.exceptions
                   if e.exception_type in types)

    def as_dict(self) -> dict:
        return {"as_of": self.as_of.isoformat(),
                "at_risk_paise": self.at_risk_paise,
                "malformed_hypotheses": self.malformed_hypotheses,
                "exceptions": [e.as_dict() for e in self.exceptions],
                "coherence_flags": [s.sentence for s in self.splits]}


def _last_by_tier(trace: Iterable[Mapping], bank_line_id: str) -> list[Mapping]:
    """This line's final state at each tier that touched it.

    The second propagation pass (§9.8) re-offers every open line to every tier, so
    the raw trace holds the same line twice and a reader built on it double-counts.
    The later entry is the one that describes the board as it ended.
    """
    latest: dict[str, Mapping] = {}
    for step in trace:
        if step["line"] == bank_line_id:
            latest[step["tier"]] = step
    return list(latest.values())


def _type_open_line(line: BankLine, steps: Sequence[Mapping], deadline_cut: bool,
                    txns: Mapping[str, GatewayTxn],
                    members: Mapping[str, tuple[str, ...]],
                    unclaimed: Sequence[GatewayTxn], age_days: int,
                    reverses: str | None = None) -> _Draft:
    """Type one open bank line, from the trace alone.

    The order is the order of certainty, not of severity:

    1. **G5 tied** — the tie is a fact in the trace, and the alternatives are
       recorded. Split by book shape (§10.1).
    2. **A tier refused to search** — it said why, in the refusal string, and the
       string already carries the type (`UNIQUENESS_UNPROVEN` or
       `EXCEEDED_SEARCH_BUDGET`). Reading it rather than re-deriving it is what
       keeps the ledger and `search_p` from disagreeing about what happened.
    3. **The deadline never reached the line** — §9.10's `exceeded`.
    4. **Nothing else** — a gap with no reachable composition, which is §10.1's
       definition of `WITHHELD_RECORD`. This is the residual class and it is where
       the delta diagnostics earn their place: without them the record would say
       "a source record is absent" with nothing behind it.
    """
    at_risk = abs(target(line))
    tried = sum(step["candidates"] for step in steps)
    anchors = sorted({a for step in steps for a in step["anchors"]})

    # 0. A reversal pair, first, because it is the only structural fact here that
    #    is established from the bank statement alone — no tier, no search, no
    #    inference about composition. A duplicate posting and its reversal are two
    #    open lines that net to zero, so they contribute nothing to E1's gap and
    #    everything to a human's inbox if they are typed as missing records.
    if reverses is not None:
        draft = _Draft(
            line.bank_line_id, "DUPLICATE_CREDIT", at_risk, age_days,
            blocked_on=("A bank advice confirming the reversal: the statement "
                        f"posts this line and {reverses} equal and opposite on "
                        "adjacent days, so neither is a settlement."),
            proposed_action={"kind": "human_review",
                             "detail": f"Contra {line.bank_line_id} against "
                                       f"{reverses}; no gateway record is expected "
                                       "for either."},
            hypotheses_tried=tried, tokens=3)
        draft.evidence.append(
            f"{fmt_inr(target(line))} on this line is reversed exactly by "
            f"{reverses} on an adjacent calendar day (§3.2)")
        draft.evidence.append(
            "Equal magnitude, opposite sign, T+1 — the balance column cannot see "
            "this: a duplicate posting is a real posting and the balance includes it")
        draft.evidence.append(
            "The pair nets to zero, so it adds nothing to the residue gap")
        draft.delta_diagnosis = "reversed_by_pair"
        return draft

    tied = next((step["tied"] for step in steps if step.get("tied")), [])
    if tied:
        shapes = {tuple(book_shape(alt, txns)) for alt in tied}
        equivalent = len(shapes) == 1
        kind = "AMBIGUOUS_EQUIVALENT" if equivalent else "AMBIGUOUS_CONSEQUENTIAL"
        draft = _Draft(
            line.bank_line_id, kind, at_risk, age_days,
            blocked_on=(
                "A human decision on which composition to book; the input "
                "distinguishes them in no way, so no rule here can choose."
                if equivalent else
                "A human decision on which composition to book; they differ in "
                "tax treatment, timing or counterparty, so the choice changes "
                "the books."),
            proposed_action={
                "kind": "human_documentation" if equivalent else "human_review",
                "detail": (f"Book either of the {len(tied)} compositions and note "
                           "the choice; both post identical figures."
                           if equivalent else
                           f"Compare the {len(tied)} compositions on fee, GST, TDS "
                           "and settlement date, then choose.")},
            hypotheses_tried=tried, tokens=3)
        draft.evidence.append(
            f"{len(tied)} compositions balance to {fmt_inr(target(line))} exactly; "
            f"G5 withdrew approval rather than pick one")
        draft.evidence.append(
            "Alternatives: " + " | ".join(",".join(alt) for alt in tied[:2])
            + (f" (+{len(tied) - 2} more)" if len(tied) > 2 else ""))
        draft.evidence.append(
            "Identical book shape — same types, methods, amounts, fee, GST, TDS "
            "and settlement dates; either assignment gives identical books"
            if equivalent else
            "The alternatives differ in book shape, so the assignment changes a "
            "tax figure, a date or a counterparty")
        return draft

    refusal = next((step["unproven"] for step in steps if step["unproven"]), None)
    if refusal and refusal.startswith("UNIQUENESS_UNPROVEN"):
        draft = _Draft(
            line.bank_line_id, "UNIQUENESS_UNPROVEN", at_risk, age_days,
            blocked_on=("A larger node budget, or a smaller window pool: an answer "
                        "may exist and a second was never ruled out."),
            proposed_action={"kind": "rerun",
                             "detail": "Re-run this line at a higher "
                                       "SUBSET_NODE_BUDGET; §10.1, the budget is "
                                       "what decides whether uniqueness holds."},
            hypotheses_tried=tried, tokens=2)
        draft.evidence.append(refusal.split(": ", 1)[-1])
        draft.evidence.append(
            "An answer, unknown whether unique — a different state from a match "
            "and from having found nothing (§10.1)")
        return draft

    if deadline_cut or (refusal and refusal.startswith("EXCEEDED_SEARCH_BUDGET")):
        draft = _Draft(
            line.bank_line_id, "EXCEEDED_SEARCH_BUDGET", at_risk, age_days,
            blocked_on=("Wall-clock time: the run deadline ended this line before "
                        "any tier had exhausted its search."),
            proposed_action={"kind": "rerun",
                             "detail": "Re-run with the deadline disabled; §11's "
                                       "node-budget-only mode is the reproducible "
                                       "one."},
            hypotheses_tried=tried, machine_dependent=True)
        draft.evidence.append(
            refusal.split(": ", 1)[-1] if refusal else
            "The ladder stopped issuing work before this line was offered every "
            "tier (§9.10)")
        return draft

    # WITHHELD_RECORD — the residual class. §10.1: a gap with no reachable
    # composition. Where an anchor was recovered the evidence can be specific about
    # the size of the hole, which is §10's own example record.
    settlement_id = anchors[0] if anchors else None
    group = members.get(settlement_id, ()) if settlement_id else ()
    recorded = sum(txns[e].net for e in group)
    residual = recorded - target(line) if group else -target(line)
    finding = diagnose(residual, group, txns, unclaimed)

    # Tokens, and only the ones that argue *for* the typing: a recovered anchor,
    # a group total that demonstrably does not close, and a named delta cause. An
    # unanchored line with an undiagnosable residual scores zero of the three and
    # comes out `low` — which is honest, because WITHHELD_RECORD is the residual
    # class and everything that failed for a reason no rule here recognises lands
    # in it.
    tokens = bool(settlement_id) + bool(group and residual) + finding.diagnosed

    draft = _Draft(
        line.bank_line_id, "WITHHELD_RECORD", at_risk, age_days,
        blocked_on=(
            f"The gateway export for {settlement_id}: a record worth "
            f"{fmt_inr(abs(residual))} that the bank paid out is absent from it."
            if settlement_id else
            f"An identifier for this credit: nothing in the narration, the "
            f"reference or the amount index resolves {fmt_inr(target(line))} to a "
            f"settlement."),
        proposed_action={
            "kind": "api_call",
            "detail": (f"GET /v1/settlements/{settlement_id}/recon"
                       if settlement_id else
                       f"GET /v1/settlements?from={window_key(line.value_date, line.txn_date)}"
                       f"&amount={target(line)}")},
        hypotheses_tried=tried, delta_diagnosis=finding.code, tokens=tokens,
        settlement_id=settlement_id,
        residual_paise=residual if settlement_id else None)

    if settlement_id:
        draft.evidence.append(
            f"Settlement {settlement_id} identified from the narration"
            + (f" (ref {line.ref_no})" if line.ref_no else ""))
        draft.evidence.append(
            f"Recorded transactions total {fmt_inr(recorded)} against a credit of "
            f"{fmt_inr(target(line))}")
    else:
        draft.evidence.append(
            f"No settlement id recovered; {len(steps)} tiers proposed "
            f"{tried} candidates and none balanced")
    draft.evidence.append(finding.detail)
    # §17, stated on the record rather than in a footnote: we can name the
    # settlement and the gap, never the missing record. Two withheld transactions
    # summing to the same figure are indistinguishable, so even check five of
    # §10.2 names a candidate and not an answer.
    if not finding.diagnosed:
        draft.evidence.append(
            "The gap can be sized and located, not attributed: a record absent "
            "from every export leaves nothing to name (§17)")
    return draft


def build(txns: Sequence[GatewayTxn], bank_lines: Sequence[BankLine],
          orders: Sequence[Order], *, matched: Mapping[str, Sequence[str]],
          trace: Sequence[Mapping], exceeded: Iterable[str] = (),
          splits: Sequence[Split] = (), deadline_hit: bool = False) -> Ledger:
    """The whole ledger, sorted and numbered per §10.2.

    `exception_id` is assigned **after** sorting, so `exc_0001` is always the most
    urgent row rather than the first bank line alphabetically. That makes the ids
    unstable across runs on purpose: they identify a position in this report, and a
    stable key already exists in `bank_line_id`.
    """
    by_id = {t.entity_id: t for t in txns}
    members = settlement_members(txns)
    claimed = {e for composition in matched.values() for e in composition}
    zero_net = no_payout_settlements(txns)
    unclaimed = [t for t in txns
                 if t.entity_id not in claimed and t.settled
                 and t.settlement_id not in zero_net]

    # The statement's own horizon, not the wall clock — see the module docstring.
    as_of = max(window_key(b.value_date, b.txn_date) for b in bank_lines)
    cut = set(exceeded)

    open_ids = [b.bank_line_id for b in bank_lines if b.bank_line_id not in matched]
    reversed_by = reversal_pairs(bank_lines, open_ids)

    drafts: list[_Draft] = []
    for line in bank_lines:
        if line.bank_line_id in matched:
            continue
        age = (as_of - window_key(line.value_date, line.txn_date)).days
        drafts.append(_type_open_line(
            line, _last_by_tier(trace, line.bank_line_id),
            line.bank_line_id in cut, by_id, members, unclaimed, age,
            reverses=reversed_by.get(line.bank_line_id)))

    # SETTLEMENT_CONTAMINATION sits on *closed* lines as often as open ones — §9.4
    # accepts a whole settlement plus strays, and the audit's job is to say when an
    # approved match spanned groups. The line closed, so nothing is at risk in the
    # sense the other rows use it; the figure priced here is the contaminating
    # transactions' own net, which is what a repair would move.
    for split in splits:
        line_id = split.bank_line_ids[0]
        line = next(b for b in bank_lines if b.bank_line_id == line_id)
        at_risk = abs(sum(by_id[e].net for e in split.entity_ids if e in by_id))
        draft = _Draft(
            line_id, "SETTLEMENT_CONTAMINATION", at_risk,
            (as_of - window_key(line.value_date, line.txn_date)).days,
            blocked_on=("Human confirmation that the tagging is correct: repair "
                        "needs a source we do not have (§17)."),
            proposed_action={"kind": "human_review", "detail": split.sentence},
            tokens=2, settlement_id=split.settlement_id)
        draft.evidence.append(split.sentence)
        draft.evidence.append(
            f"{len(split.entity_ids)} transactions in {split.settlement_id}, "
            f"net {fmt_inr(at_risk)}")
        drafts.append(draft)

    # §3.3's secondary tie-out. One query, and it is what earns the word
    # multi-source: a paid order with no gateway payment is a break neither the
    # bank statement nor the gateway ledger can see on its own.
    paid_orders = {t.order_id for t in txns if t.type == "payment"}
    for order in orders:
        if order.status != "paid" or order.order_id in paid_orders:
            continue
        draft = _Draft(
            None, "ORPHAN_ORDER", order.gross_paise,
            (as_of - window_key(None, order.order_date)).days,
            blocked_on=(f"The gateway payment for {order.order_id}: the ERP records "
                        f"the order paid and no gateway record carries it."),
            proposed_action={"kind": "api_call",
                             "detail": f"GET /v1/orders/{order.order_id}/payments"},
            # §3.3 is a two-sided fact and both sides are in the input: the ERP
            # says paid, the gateway has nothing. There is no third thing to check.
            tokens=2)
        draft.evidence.append(
            f"{order.order_id} is status=paid for {fmt_inr(order.gross_paise)} "
            f"on {order.order_date}")
        draft.evidence.append(
            f"No gateway payment carries order_id={order.order_id}")
        drafts.append(draft)

    # Every deadline-cut record says so, on the record. Exception typing is scored
    # and the live run carries a wall clock, so a reader comparing this ledger with
    # another needs to know which rows would be typed differently on a faster box
    # (§11). Appended after `_confidence` would have counted it — a caveat is not
    # corroboration, and the override to `low` already covers the typing.
    for draft in drafts:
        if draft.machine_dependent:
            draft.evidence.append(
                "This type is deadline-dependent and may differ on faster "
                "hardware: the clock ended this line, not the data (§11).")

    drafts.sort(key=_sort_key)
    return Ledger(
        exceptions=tuple(
            LedgerException(
                exception_id=f"exc_{i:04d}", bank_line_id=d.bank_line_id,
                exception_type=d.exception_type, type_confidence=_confidence(d),
                amount_at_risk_paise=d.amount_at_risk_paise,
                delta_diagnosis=d.delta_diagnosis, age_days=d.age_days,
                age_bucket=age_bucket(d.age_days), blocked_on=d.blocked_on,
                proposed_action=d.proposed_action,
                hypotheses_tried=d.hypotheses_tried,
                evidence=tuple(d.evidence), settlement_id=d.settlement_id,
                residual_paise=d.residual_paise)
            for i, d in enumerate(drafts, start=1)),
        as_of=as_of,
        # §10.1's internal counter: a claim citing a non-existent or already-spent
        # entity. G1 catches all of it (§7.4), and a rising count is a
        # prompt-quality signal. Every one of these is currently a deterministic
        # tier re-proposing a set an earlier line consumed — the model proposer
        # arrives at stage 12 and this is the counter it will be read against.
        malformed_hypotheses=sum(step["stale"] for step in trace),
        splits=tuple(splits),
    )


def render(ledger: Ledger, limit: int = 12) -> list[str]:
    """§13's OPEN ITEMS column, as text. Typed, priced, aged, one sentence each."""
    out = [f"EXCEPTION LEDGER — {len(ledger.exceptions)} open, "
           f"{fmt_inr(ledger.at_risk_paise)} at risk, aged from "
           f"{ledger.as_of.isoformat()}",
           "─" * 92]
    counts = ledger.by_type()
    for kind in sorted(counts, key=lambda k: -ledger.total_for(k)):
        rows = counts[kind]
        out.append(f"  {kind:<28}{len(rows):>4}   "
                   f"{fmt_inr(ledger.total_for(kind)):>16}")
    out.append("")
    for exc in ledger.exceptions[:limit]:
        out.append(f"  {exc.exception_id}  {exc.bank_line_id or '—':<10}"
                   f"{fmt_inr(exc.amount_at_risk_paise):>16}  "
                   f"{exc.exception_type:<26} {exc.type_confidence:<7}"
                   f"{exc.age_bucket:>7}")
        out.append(f"           δ {exc.delta_diagnosis} · "
                   f"{exc.hypotheses_tried} hypotheses tried")
        for token in exc.evidence:
            out.append(f"           · {token}")
        out.append(f"           blocked on: {exc.blocked_on}")
        out.append(f"           {exc.proposed_action['kind']}: "
                   f"{exc.proposed_action['detail']}")
    if len(ledger.exceptions) > limit:
        out.append(f"  … {len(ledger.exceptions) - limit} more, "
                   f"§10.2 order: WITHHELD_RECORD and AMBIGUOUS_CONSEQUENTIAL by "
                   f"amount first, AMBIGUOUS_EQUIVALENT last")
    out.append(f"  MALFORMED_HYPOTHESIS  {ledger.malformed_hypotheses}  "
               "(internal counter, §10.1: claims citing spent or unknown entities, "
               "all caught by G1)")
    return out
