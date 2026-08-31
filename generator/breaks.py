"""The 15 injected breaks of §5.

Three of §5's eighteen codes are not injected here and must not pretend to be:

- `TDS_DEDUCTION` and `CROSS_CYCLE_REFUND` are properties of *correct* data that a
  naive matcher gets wrong. They are produced by baseline generation and counted
  under `baseline_properties`.
- `AMBIGUOUS_SUBSET` emerges from the uniqueness gate (§6.2). It is counted from
  what the gate actually found, never asserted.

Each injector returns the number of times it fired, and `tests/test_breaks.py`
recounts every one against the emitted data — a break that claims to fire but does
not is worse than one that is missing.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from datetime import timedelta

from core.fees import INSTANT_FLAT, expected_fee
from core.models import BankLine, GatewayTxn, Order
from core.money import ist_date
from generator import config as cfg
from generator.allocate import allocate
from generator.entities import Dataset, Settlement
from generator.narration import make_utr

BREAK_COUNTS = {
    "TIMING_SHIFT": 6, "ONHOLD_RELEASE": 4, "DISPUTE_DEBIT": 4,
    "ROUNDING_DRIFT": 5, "DUPLICATE_CREDIT": 3, "NARRATION_TRUNCATED": 8,
    "ROUTE_SPLIT": 4, "INSTANT_SETTLEMENT": 3, "FX_MARKUP": 5,
    "ORPHAN_ORDER": 6, "SETTLEMENT_CONTAMINATION": 3, "SPLIT_PAYOUT": 3,
    "NEGATIVE_SETTLEMENT": 3, "NET_ZERO_SETTLEMENT": 2, "WITHHELD_RECORD": 4,
}


@dataclass
class Work:
    """Mutable working copy. Frozen value types are replaced, never edited."""

    txns: dict[str, GatewayTxn]
    lines: dict[str, BankLine]
    orders: list[Order]
    settlements: dict[str, Settlement]
    rng: random.Random
    window_days: int
    line_breaks: dict[str, list[str]] = field(default_factory=dict)
    forced: dict[str, dict] = field(default_factory=dict)
    settlement_notes: dict[str, dict] = field(default_factory=dict)
    used: set[str] = field(default_factory=set)
    next_line: int = 0
    next_entity: int = 0

    # --- helpers ------------------------------------------------------------

    def available(self, need: int = 1, where=None) -> list[str]:
        """Settlement ids not yet touched by another break, in a stable order."""
        return [s for s in sorted(self.settlements) if s not in self.used
                and len(self.settlements[s].entity_ids) >= need
                and (where is None or where(self.settlements[s]))]

    def take(self, need: int = 1, where=None) -> Settlement | None:
        free = self.available(need, where)
        if not free:
            return None
        chosen = free[self.rng.randrange(len(free))]
        self.used.add(chosen)
        return self.settlements[chosen]

    def members(self, settlement: Settlement) -> list[GatewayTxn]:
        return [self.txns[e] for e in settlement.entity_ids]

    def flag(self, bank_line_id: str, code: str) -> None:
        self.line_breaks.setdefault(bank_line_id, []).append(code)

    def new_line_id(self) -> str:
        self.next_line += 1
        return f"bl_{self.next_line + 9000:04d}"

    def new_entity_id(self, prefix: str) -> str:
        self.next_entity += 1
        return f"{prefix}_{self.next_entity + 90000:05d}"

    def recredit(self, settlement: Settlement, delta: int = 0) -> None:
        """Re-derive the bank line from the payout it pays. `delta` is a
        deliberate discrepancy — everything else must tie to the paise."""
        net = sum(t.net for t in self.members(settlement)) + delta
        line = self.lines[settlement.bank_line_id]
        self.lines[settlement.bank_line_id] = replace(
            line, credit_paise=max(net, 0), debit_paise=-net if net < 0 else 0)

    def set_members(self, settlement: Settlement, entity_ids: tuple[str, ...]) -> Settlement:
        updated = replace(settlement, entity_ids=entity_ids)
        self.settlements[settlement.settlement_id] = updated
        return updated

    def strays(self, settlement: Settlement) -> int:
        return sum(1 for e in settlement.entity_ids
                   if self.txns[e].settlement_id is None)

    def cycle_day(self, settlement: Settlement) -> int:
        return (ist_date(settlement.cycle_date) - cfg.EPOCH).days


# --- the injectors ----------------------------------------------------------


def timing_shift(w: Work, n: int) -> int:
    """Settles next cycle: push `settled_at` forward. Membership is unchanged, so
    the line is recoverable through C1 and invisible to C2 (§9.3)."""
    fired = 0
    spacing = cfg.cycle_spacing(w.window_days)
    for _ in range(n):
        s = w.take(need=6)
        if s is None:
            break
        moved = [e for e in s.entity_ids if w.txns[e].type == "payment"][:w.rng.randint(1, 3)]
        for e in moved:
            t = w.txns[e]
            shifted = ist_date(t.settled_at) + timedelta(days=spacing)
            w.txns[e] = replace(t, settled_at=f"{shifted.isoformat()}T{cfg.CYCLE_HOUR}+05:30")
        w.flag(s.bank_line_id, "TIMING_SHIFT")
        fired += 1
    return fired


def onhold_release(w: Work, n: int) -> int:
    """Held N cycles, then released into a later payout. `on_hold` is a
    point-in-time display flag; the pool filter never reads it (§3.1)."""
    fired = 0
    for _ in range(n):
        s = w.take(need=6)
        if s is None:
            break
        later = [x for x in sorted(w.settlements)
                 if w.cycle_day(w.settlements[x]) > w.cycle_day(s) + w.window_days
                 and x not in w.used]
        if not later:
            continue
        target_s = w.settlements[later[w.rng.randrange(min(4, len(later)))]]
        w.used.add(target_s.settlement_id)
        held = [e for e in s.entity_ids if w.txns[e].type == "payment"][:w.rng.randint(1, 2)]
        for e in held:
            w.txns[e] = replace(
                w.txns[e], on_hold=True, settlement_id=target_s.settlement_id,
                settlement_utr=target_s.utr,
                settled_at=f"{target_s.cycle_date}T{cfg.CYCLE_HOUR}+05:30")
        s = w.set_members(s, tuple(e for e in s.entity_ids if e not in held))
        target_s = w.set_members(target_s, target_s.entity_ids + tuple(held))
        w.recredit(s)
        w.recredit(target_s)
        w.flag(s.bank_line_id, "ONHOLD_RELEASE")
        w.flag(target_s.bank_line_id, "ONHOLD_RELEASE")
        fired += 1
    return fired


def dispute_debit(w: Work, n: int) -> int:
    """A chargeback posted as a bank debit, matched by B2 against one `disp_*`
    with a negative net (finding 8.1)."""
    fired = 0
    for _ in range(n):
        s = w.take()
        if s is None:
            break
        parent = next((t for t in w.members(s) if t.type == "payment"), None)
        if parent is None:
            continue
        entity_id = w.new_entity_id("disp")
        day = w.cycle_day(s) + 1
        settled = (cfg.EPOCH + timedelta(days=day)).isoformat()
        w.txns[entity_id] = GatewayTxn(
            entity_id=entity_id, type="dispute", amount_paise=parent.amount_paise,
            method=parent.method,
            created_at=f"{settled}T09:00:00+05:30",
            settled_at=f"{settled}T{cfg.CYCLE_HOUR}+05:30",
            settlement_id=None, settlement_utr=None, order_id=parent.order_id,
            payment_id=parent.entity_id,
            description=f"Chargeback on {parent.entity_id}", notes="stage=lost",
        )
        line_id = w.new_line_id()
        w.lines[line_id] = BankLine(
            bank_line_id=line_id, txn_date=settled, value_date=settled,
            narration=f"CHGBK-{entity_id[-6:].upper()}-RZP ADJ", ref_no=None,
            debit_paise=parent.amount_paise, credit_paise=0, balance_paise=0)
        w.forced[line_id] = {
            "resolvable": True, "uniqueness": "by_construction",
            "composition": [entity_id], "injected_breaks": ["DISPUTE_DEBIT"],
            "expected_delta_paise": 0,
        }
        fired += 1
    return fired


def rounding_drift(w: Work, n: int) -> int:
    """§4.3: the instant-settlement premium is allocated by integer division and
    the `total % n` remainder is dropped. The bank deducted the whole premium; the
    ledger records only `n * per`, so the line is short by the remainder — a
    bounded, explainable drift, which is exactly what G4's band exists to catch."""
    fired = 0
    for _ in range(n):
        s = w.take(need=4)
        if s is None:
            break
        members = w.members(s)
        alloc = allocate(INSTANT_FLAT, members)
        remainder = INSTANT_FLAT - sum(alloc.values())
        if remainder == 0:
            continue
        for entity_id, per in alloc.items():
            t = w.txns[entity_id]
            w.txns[entity_id] = replace(t, fee_paise=t.fee_paise + per)
        w.recredit(s, delta=-remainder)
        w.flag(s.bank_line_id, "ROUNDING_DRIFT")
        w.forced[s.bank_line_id] = {
            "resolvable": True, "uniqueness": "verified",
            "composition": sorted(s.entity_ids),
            "injected_breaks": ["ROUNDING_DRIFT"],
            "expected_delta_paise": -remainder,
        }
        fired += 1
    return fired


def duplicate_credit(w: Work, n: int) -> int:
    """The bank posts twice and reverses on T+1. The balance column cannot detect
    it — a duplicate posting is a real posting and the balance includes it."""
    fired = 0
    for _ in range(n):
        s = w.take()
        if s is None:
            break
        original = w.lines[s.bank_line_id]
        day = ist_date(original.value_date)
        dupe_id, reversal_id = w.new_line_id(), w.new_line_id()
        dupe_date = (day + timedelta(days=1)).isoformat()
        w.lines[dupe_id] = replace(
            original, bank_line_id=dupe_id, txn_date=dupe_date, value_date=dupe_date,
            narration=original.narration or "NEFT-RAZORPAYSOFTW-RZPSETTLE")
        rev_date = (day + timedelta(days=2)).isoformat()
        w.lines[reversal_id] = BankLine(
            bank_line_id=reversal_id, txn_date=rev_date, value_date=rev_date,
            narration=f"REV-{original.narration[:24]}" if original.narration else "REV-RZP",
            ref_no=original.ref_no, debit_paise=original.credit_paise,
            credit_paise=0, balance_paise=0)
        for line_id in (dupe_id, reversal_id):
            w.forced[line_id] = {
                "resolvable": False, "composition": None,
                "injected_breaks": ["DUPLICATE_CREDIT"],
                "unresolvable_reason":
                    f"Duplicate posting of {s.bank_line_id}, reversed on T+1 by "
                    f"{reversal_id}. No transaction composes it.",
            }
        fired += 1
    return fired


def narration_truncated(w: Work, n: int) -> int:
    """The UTR is mangled past the point a clean match can use it. A3 and the
    prefix cascade of §9.5 are what recover these."""
    fired = 0
    for _ in range(n):
        s = w.take()
        if s is None:
            break
        keep = s.utr[: w.rng.randint(5, 8)]
        line = w.lines[s.bank_line_id]
        w.lines[s.bank_line_id] = replace(
            line, narration=f"MMT/IMPS/{keep}/RAZORPAY  SOFT/", ref_no=None)
        w.flag(s.bank_line_id, "NARRATION_TRUNCATED")
        fired += 1
    return fired


def route_split(w: Work, n: int) -> int:
    """A Route transfer to a sub-merchant, reducing the payout. C1 sees it as a
    negative term inside the settlement."""
    fired = 0
    for _ in range(n):
        s = w.take(need=3)
        if s is None:
            break
        members = w.members(s)
        share = sum(t.net for t in members) // 10
        if share <= 0:
            continue
        entity_id = w.new_entity_id("trf")
        w.txns[entity_id] = GatewayTxn(
            entity_id=entity_id, type="transfer", amount_paise=share, method="upi",
            created_at=f"{s.cycle_date}T10:00:00+05:30",
            settled_at=f"{s.cycle_date}T{cfg.CYCLE_HOUR}+05:30",
            settlement_id=s.settlement_id, settlement_utr=s.utr,
            description="Route transfer to sub-merchant", notes="route=acc_sub")
        s = w.set_members(s, s.entity_ids + (entity_id,))
        w.recredit(s)
        w.flag(s.bank_line_id, "ROUTE_SPLIT")
        fired += 1
    return fired


def instant_settlement(w: Work, n: int) -> int:
    """An off-cycle payout carrying the ₹25 flat premium, allocated per §4.3. The
    premium is folded into `fee_paise` (I7) and here the allocation divides
    exactly, so the only difference from a normal payout is the date and the fee."""
    fired = 0
    for _ in range(n):
        s = w.take(need=10)
        if s is None:
            break
        members = w.members(s)
        moved = [t for t in members if t.type == "payment"][:5]
        if len(moved) < 5 or INSTANT_FLAT % len(moved):
            continue
        day = w.cycle_day(s) - 1
        cycle = (cfg.EPOCH + timedelta(days=day)).isoformat()
        new_id = f"setl_{9000 + w.next_line:04d}"
        line_id = w.new_line_id()
        utr = make_utr(cfg.MERCHANT_BANK, cycle, 900 + fired)
        alloc = allocate(INSTANT_FLAT, moved)
        for t in moved:
            w.txns[t.entity_id] = replace(
                t, settlement_id=new_id, settlement_utr=utr,
                settled_at=f"{cycle}T{cfg.CYCLE_HOUR}+05:30",
                fee_paise=t.fee_paise + alloc[t.entity_id])
        s = w.set_members(s, tuple(e for e in s.entity_ids
                                   if e not in {t.entity_id for t in moved}))
        w.recredit(s)
        moved_ids = tuple(t.entity_id for t in moved)
        w.settlements[new_id] = Settlement(
            settlement_id=new_id, utr=utr, cycle_date=cycle,
            entity_ids=moved_ids, bank_line_id=line_id)
        w.lines[line_id] = BankLine(
            bank_line_id=line_id, txn_date=cycle, value_date=cycle,
            narration=f"INSTSETL RZP {utr} FEE INCL", ref_no=utr,
            debit_paise=0, credit_paise=sum(w.txns[e].net for e in moved_ids),
            balance_paise=0)
        w.used.add(new_id)
        w.flag(line_id, "INSTANT_SETTLEMENT")
        fired += 1
    return fired


def fx_markup(w: Work, n: int) -> int:
    """An international card: the 1% markup folds into `fee_paise`, never a
    separate term (I7). A matcher using the domestic MDR is short by the markup."""
    fired = 0
    for _ in range(n):
        s = w.take(need=3)
        if s is None:
            break
        card = next((t for t in w.members(s)
                     if t.type == "payment" and t.method == "card"
                     and not t.international), None)
        if card is None:
            continue
        fx = cfg.FX_RATE_MICROS + w.rng.randint(-250_000, 250_000)
        upgraded = replace(card, method="intl_card", international=True,
                           source_currency="USD", fx_rate_micros=fx,
                           source_amount_minor=card.amount_paise * 1_000_000 // fx)
        fee, tax, tds = expected_fee(upgraded)
        w.txns[card.entity_id] = replace(upgraded, fee_paise=fee, tax_paise=tax,
                                         tds_paise=tds)
        w.recredit(s)
        w.flag(s.bank_line_id, "FX_MARKUP")
        fired += 1
    return fired


def orphan_order(w: Work, n: int) -> int:
    """A paid order in the ERP with no gateway payment carrying its id. The §3.3
    tie-out is one query and earns the word multi-source."""
    for i in range(n):
        order_id = f"order_9{i:04d}"
        day = w.rng.randrange(30)
        w.orders.append(Order(
            order_id=order_id,
            order_date=(cfg.EPOCH + timedelta(days=day)).isoformat(),
            customer_ref=f"cust_9{i:04d}",
            gross_paise=w.rng.choice(cfg.PRICE_POINTS), currency="INR",
            status="paid", invoice_no=f"INV-2026-9{i:04d}"))
    return n


def settlement_contamination(w: Work, n: int) -> int:
    """One transaction mis-tagged to another settlement. The payout it really
    belongs to still passes G3 as "complete plus one item from another group" and
    is flagged; the settlement it was tagged INTO can no longer be assembled,
    because its own composition is now a partial slice of the tag group. §17: we
    detect and name it, we cannot repair it."""
    fired = 0
    for _ in range(n):
        # The mis-tagged item is itself one of §9.4's "1-2 items from another
        # group", so the source payout must not already be carrying two strays —
        # three extras is a shape G3 refuses, and the contamination would then
        # break the line it was supposed to leave merely flagged.
        s = w.take(need=4, where=lambda x: w.strays(x) <= 1)
        if s is None:
            break
        others = [x for x in sorted(w.settlements)
                  if x != s.settlement_id and x not in w.used
                  and len(w.settlements[x].entity_ids) >= 3]
        if not others:
            continue
        victim = w.settlements[others[w.rng.randrange(len(others))]]
        w.used.add(victim.settlement_id)
        mis = next(e for e in s.entity_ids if w.txns[e].type == "payment")
        w.txns[mis] = replace(w.txns[mis], settlement_id=victim.settlement_id,
                              settlement_utr=victim.utr)
        w.flag(s.bank_line_id, "SETTLEMENT_CONTAMINATION")
        w.forced[victim.bank_line_id] = {
            "resolvable": False, "composition": None,
            "injected_breaks": ["SETTLEMENT_CONTAMINATION"],
            "unresolvable_reason":
                f"{mis} is tagged to {victim.settlement_id} but was paid out in "
                f"{s.settlement_id}, so no whole group composes this line.",
        }
        fired += 1
    return fired


def split_payout(w: Work, n: int) -> int:
    """One settlement paid across two bank lines. Truth records the real halves
    and `requires_tier: C3`: truth describes the data, not the matcher's current
    reach, so these score FN until C3 exists and TP after, with no truth change."""
    fired = 0
    for _ in range(n):
        s = w.take(need=6)
        if s is None:
            break
        members = w.members(s)
        half, running = [], 0
        goal = sum(t.net for t in members) // 2
        for t in members:
            if running < goal:
                half.append(t)
                running += t.net
        rest = [t for t in members if t not in half]
        if not half or not rest:
            continue
        second_id = w.new_line_id()
        first = w.lines[s.bank_line_id]
        w.lines[s.bank_line_id] = replace(first, credit_paise=running, debit_paise=0)
        w.lines[second_id] = replace(
            first, bank_line_id=second_id,
            credit_paise=sum(t.net for t in rest), debit_paise=0,
            narration=first.narration, ref_no=None)
        for line_id, part in ((s.bank_line_id, half), (second_id, rest)):
            partner = second_id if line_id == s.bank_line_id else s.bank_line_id
            w.forced[line_id] = {
                "resolvable": True, "uniqueness": "by_construction",
                "composition": sorted(t.entity_id for t in part),
                "requires_tier": "C3", "injected_breaks": ["SPLIT_PAYOUT"],
                "expected_delta_paise": 0,
                "unresolvable_reason": None,
                "split_partner": partner,
            }
        fired += 1
    return fired


def negative_settlement(w: Work, n: int) -> int:
    """Refunds exceed payments, so the payout is a bank debit. Every tier accepts
    a signed target (finding 8.1)."""
    fired = 0
    for _ in range(n):
        s = w.take(need=3)
        if s is None:
            break
        members = w.members(s)
        parent = next((t for t in members if t.type == "payment"), None)
        if parent is None:
            continue
        excess = sum(t.net for t in members) + parent.amount_paise // 2
        entity_id = w.new_entity_id("rfnd")
        w.txns[entity_id] = GatewayTxn(
            entity_id=entity_id, type="refund", amount_paise=excess,
            method=parent.method, created_at=f"{s.cycle_date}T11:00:00+05:30",
            settled_at=f"{s.cycle_date}T{cfg.CYCLE_HOUR}+05:30",
            settlement_id=s.settlement_id, settlement_utr=s.utr,
            order_id=parent.order_id, payment_id=parent.entity_id,
            description="Bulk refund exceeding cycle receipts",
            notes="reason=order_cancellation")
        s = w.set_members(s, s.entity_ids + (entity_id,))
        w.recredit(s)
        w.flag(s.bank_line_id, "NEGATIVE_SETTLEMENT")
        fired += 1
    return fired


def net_zero_settlement(w: Work, n: int) -> int:
    """Refunds exactly offset payments, so **no bank line is created at all**
    (§5.1). Its transactions must be excluded from the residue denominator, or the
    gap is permanently non-zero and the whole check is useless."""
    fired = 0
    for _ in range(n):
        s = w.take(need=3)
        if s is None:
            break
        members = w.members(s)
        parent = next((t for t in members if t.type == "payment"), None)
        if parent is None:
            continue
        entity_id = w.new_entity_id("rfnd")
        w.txns[entity_id] = GatewayTxn(
            entity_id=entity_id, type="refund", amount_paise=sum(t.net for t in members),
            method=parent.method, created_at=f"{s.cycle_date}T11:00:00+05:30",
            settled_at=f"{s.cycle_date}T{cfg.CYCLE_HOUR}+05:30",
            settlement_id=s.settlement_id, settlement_utr=s.utr,
            order_id=parent.order_id, payment_id=parent.entity_id,
            description="Refunds offsetting the cycle exactly",
            notes="reason=batch_cancellation")
        s = w.set_members(s, s.entity_ids + (entity_id,))
        assert sum(t.net for t in w.members(s)) == 0
        del w.lines[s.bank_line_id]
        w.settlements[s.settlement_id] = replace(s, bank_line_id="")
        w.settlement_notes[s.settlement_id] = {
            "no_payout_expected": True, "reason": "net zero",
            "entity_ids": sorted(w.settlements[s.settlement_id].entity_ids),
        }
        fired += 1
    return fired


def withheld_record(w: Work, n: int) -> int:
    """A source record absent from the gateway export. Unsolvable by design: we
    can name the settlement and the gap, never the missing record (§17)."""
    fired = 0
    for _ in range(n):
        s = w.take(need=4)
        if s is None:
            break
        gone = next((e for e in s.entity_ids if w.txns[e].type == "payment"), None)
        if gone is None:
            continue
        gap = w.txns[gone].net
        order_id = w.txns[gone].order_id
        del w.txns[gone]
        # §5: absent from ALL exports. Leaving the order behind would silently
        # manufacture an ORPHAN_ORDER and make that manifest count a lie.
        w.orders = [o for o in w.orders if o.order_id != order_id]
        s = w.set_members(s, tuple(e for e in s.entity_ids if e != gone))
        w.forced[s.bank_line_id] = {
            "resolvable": False, "composition": None,
            "injected_breaks": ["WITHHELD_RECORD"],
            "unresolvable_reason":
                f"A source record is missing from the gateway export; "
                f"{s.settlement_id} is short by {gap} paise.",
        }
        fired += 1
    return fired


INJECTORS = (
    ("NET_ZERO_SETTLEMENT", net_zero_settlement),
    ("NEGATIVE_SETTLEMENT", negative_settlement),
    ("SPLIT_PAYOUT", split_payout),
    ("DUPLICATE_CREDIT", duplicate_credit),
    ("INSTANT_SETTLEMENT", instant_settlement),
    ("DISPUTE_DEBIT", dispute_debit),
    ("WITHHELD_RECORD", withheld_record),
    ("SETTLEMENT_CONTAMINATION", settlement_contamination),
    ("ONHOLD_RELEASE", onhold_release),
    ("TIMING_SHIFT", timing_shift),
    ("ROUTE_SPLIT", route_split),
    ("ROUNDING_DRIFT", rounding_drift),
    ("FX_MARKUP", fx_markup),
    ("NARRATION_TRUNCATED", narration_truncated),
    ("ORPHAN_ORDER", orphan_order),
)


@dataclass(frozen=True)
class Injected:
    data: Dataset
    line_breaks: dict[str, list[str]]
    forced: dict[str, dict]
    settlement_notes: dict[str, dict]
    manifest: dict[str, dict]


def inject(data: Dataset, seed: int, window_days: int,
           counts: dict[str, int] | None = None) -> Injected:
    """Run every injector once, in a fixed order, over a working copy.

    `counts` overrides `BREAK_COUNTS` per code, and a code set to 0 does not fire.
    It exists for one test: stage 10's residue gap has to be measured against a
    dataset carrying exactly one `WITHHELD_RECORD` and nothing else, because the
    assertion is that the gap equals *that record's* net — an isolation the full
    manifest cannot give. The default is `BREAK_COUNTS` unchanged, so no committed
    dataset moves.
    """
    counts = {**BREAK_COUNTS, **(counts or {})}
    w = Work(
        txns={t.entity_id: t for t in data.txns},
        lines={line.bank_line_id: line for line in data.bank_lines},
        orders=list(data.orders),
        settlements={s.settlement_id: s for s in data.settlements},
        rng=random.Random(seed ^ 0xB4EA),
        window_days=window_days,
    )
    manifest = {code: {"injected": fire(w, counts[code]),
                       "caught": None, "missed": None}
                for code, fire in INJECTORS}

    balance = cfg.OPENING_BALANCE
    stamped = []
    for line in sorted(w.lines.values(), key=lambda x: (x.value_date, x.bank_line_id)):
        balance += line.credit_paise - line.debit_paise
        stamped.append(replace(line, balance_paise=balance))

    return Injected(
        data=replace(
            data,
            txns=tuple(w.txns.values()),
            bank_lines=tuple(stamped),
            orders=tuple(w.orders),
            settlements=tuple(s for s in w.settlements.values() if s.bank_line_id),
        ),
        line_breaks=w.line_breaks,
        forced=w.forced,
        settlement_notes=w.settlement_notes,
        manifest=manifest,
    )
