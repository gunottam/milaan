"""Phase A and Phase B against seed 42, plus the two cases the seed never fires.

§9.1, §9.2, §9.5. The ladder these numbers come from is `matcher.run.run_ladder` —
single pass, no propagation, no deadline. Stage 9 owns the real ordering, and any
number here can move when it lands.
"""

from __future__ import annotations

from collections import Counter

import pytest

from core.models import BankLine, GatewayTxn, target
from generator.generate import generate
from matcher.proposers.lookup_p import LookupProposer
from matcher.proposers.regex_p import RegexProposer
from matcher.run import run_ladder
from matcher.uniqueness import resolve
from matcher.verify import check
from tests.test_invariants import grep

STAMP = "2026-08-24T15:30:00+05:30"
DAY = "2026-01-05"


@pytest.fixture(scope="module")
def run():
    # The 2M budget only changes how many truth records read "unproven"; the CSVs
    # it describes are the same bytes the 40M offline run emits.
    data, truth = generate(42, 120, 3000, "high", 2, STAMP, 2_000_000)
    matched, trace = run_ladder(data.txns, data.bank_lines)
    return data, truth, matched, trace


# --- what the two phases actually close --------------------------------------


def test_phase_a_and_b_close_64_of_134_lines(run):
    data, _, matched, _ = run
    assert len(data.bank_lines) == 134
    per_tier = Counter(tier for tier, _, _ in matched.values())
    assert dict(per_tier) == {"A1": 40, "A3": 4, "B1": 16, "B2": 4}
    assert len(matched) == 64


def test_not_one_of_them_is_wrong(run):
    """Scoring proper is stage 7. This is the assertion that matters before it:
    a false match is severe and a miss is an exception a human clears."""
    _, truth, matched, _ = run
    wrong = [bid for bid, (_, claim, _) in matched.items()
             if set(truth["bank_lines"][bid].get("composition") or ())
             != set(claim.composition)]
    assert wrong == []


def test_the_four_dispute_debits_match_at_b2_on_a_negative_target(run):
    """§9.2 and finding 8.1 — a chargeback posted as a bank debit is one `disp_*`
    with a negative net, and B2 needs no separate debit path to see it."""
    data, truth, matched, _ = run
    lines = {line.bank_line_id: line for line in data.bank_lines}
    debits = sorted(bid for bid, rec in truth["bank_lines"].items()
                    if "DISPUTE_DEBIT" in rec.get("injected_breaks", []))
    assert len(debits) == 4
    for bid in debits:
        assert target(lines[bid]) < 0
        tier, claim, verdict = matched[bid]
        assert tier == "B2" and len(claim.composition) == 1
        assert verdict.confidence == "exact"


def test_a_recovered_identifier_is_not_a_match(run):
    """I8. A1 recovered a settlement on 81 lines and closed 40 of them: the other 41
    cited a real settlement whose total is not the payout total. Those fall to C1's
    anchored residual search in stage 8, not to a weaker identifier test."""
    _, _, matched, trace = run
    a1 = [t for t in trace if t["tier"] == "A1"]
    assert len(a1) == 81
    assert sum(t["won"] for t in a1) == 40


def test_the_prefix_cascade_is_mostly_thrown_away(run):
    """§9.5: every settlement from one bank on one day shares a long prefix, so a
    truncated fragment matches almost the whole book — 123 candidates at the median
    here. G1 drops the claimed ones in bulk."""
    _, _, _, trace = run
    a3 = [t for t in trace if t["tier"] == "A3"]
    assert len(a3) == 12
    assert all(t["candidates"] > 1 for t in a3)
    assert sum(t["stale"] for t in a3) > 400


def test_a2_finds_nothing_in_this_dataset(run):
    """No narration template writes a `setl_*` token (§3.4), so A2 is dead weight
    here. It stays because the detective's `direct_link` claim returns a settlement
    id to Phase A (§9.6), and that is the tier that consumes it."""
    _, _, matched, trace = run
    assert [t for t in trace if t["tier"] == "A2"] == []


# --- the two cases seed 42 does not fire -------------------------------------


def payment(entity_id: str, amount: int, settlement_id: str, utr: str) -> GatewayTxn:
    return GatewayTxn(entity_id=entity_id, type="payment", amount_paise=amount,
                      settlement_id=settlement_id, settlement_utr=utr,
                      settled_at=f"{DAY}T18:30:00+05:30")


def bank_line(credit: int, narration: str = "", ref_no: str | None = None) -> BankLine:
    return BankLine("bl_0001", DAY, DAY, narration, ref_no, 0, credit, 0)


# Two settlements from one bank on one day: a shared UTR prefix and, deliberately,
# an identical total.
TWINS = [payment("pay_a1", 120, "setl_a", "NHDFC26010500001"),
         payment("pay_a2", 80, "setl_a", "NHDFC26010500001"),
         payment("pay_b1", 150, "setl_b", "NHDFC26010500002"),
         payment("pay_b2", 50, "setl_b", "NHDFC26010500002")]
UNIVERSE = {t.entity_id: t for t in TWINS}


def _decide(claims, line, claimed=frozenset()):
    return resolve([(c, check(c, line, UNIVERSE, claimed)) for c in claims])


def test_b1_refuses_two_unclaimed_settlements_with_the_same_total():
    """Finding 8.4, and the reason B1 has to apply G5: two candidates, no search.
    On seed 42 the index does hold one duplicate-total bucket (₹499.00,
    `setl_0020` and `setl_0108`) and **no bank line asks for it** — so the guarantee
    cannot be left to the seed to demonstrate."""
    line = bank_line(200)
    claims = LookupProposer("B1", TWINS).propose(line, [])
    assert len(claims) == 2
    won, verdict = _decide(claims, line)
    assert won is None and verdict.gate == "G5"
    assert "2 compositions tie" in verdict.reason


def test_the_duplicate_total_bucket_exists_on_seed_42(run):
    data, _, _, _ = run
    b1 = LookupProposer("B1", data.txns)
    dupes = {total: sids for total, sids in b1._index.items() if len(sids) > 1}
    assert dupes == {49_900: {"setl_0020", "setl_0108"}}


def test_exclusivity_is_what_resolves_a_prefix_collision():
    """§9.5's filter 3. The fragment matches both settlements and both balance, so
    arithmetic cannot separate them — only the fact that one is already spent can.
    Seed 42 never needs this: its collisions are always cut by arithmetic instead."""
    line = bank_line(200, narration="MMT/IMPS/NHDFC260105/RAZORPAY  SOFT/")
    claims = RegexProposer("A3", TWINS).propose(line, [])
    assert {c.anchor_settlement_id for c in claims} == {"setl_a", "setl_b"}

    won, verdict = _decide(claims, line)
    assert won is None and verdict.gate == "G5"

    won, verdict = _decide(claims, line, claimed=frozenset({"pay_b1", "pay_b2"}))
    assert won is not None and won.anchor_settlement_id == "setl_a"
    assert verdict.ok and verdict.confidence == "exact"


def test_b1_index_removal_is_incremental():
    """§9.2: built once, O(1) removal on claim, no per-pass rebuild."""
    b1 = LookupProposer("B1", TWINS)
    line = bank_line(200)
    assert len(b1.propose(line, [])) == 2
    b1.release("setl_b")
    assert [c.anchor_settlement_id for c in b1.propose(line, [])] == ["setl_a"]
    b1.release("setl_a")
    assert b1.propose(line, []) == []
    b1.release("setl_a")            # idempotent — a second claim cannot underflow


def test_a1_takes_the_exact_utr_and_a3_leaves_it_alone():
    line = bank_line(200, ref_no="NHDFC26010500001")
    assert [c.anchor_settlement_id
            for c in RegexProposer("A1", TWINS).propose(line, [])] == ["setl_a"]
    # A3 skips a fragment A1 already resolved exactly: re-proposing a set the gates
    # rejected cannot change the answer.
    assert RegexProposer("A3", TWINS).propose(line, []) == []


def test_a_fragment_matching_nothing_falls_through():
    line = bank_line(200, narration="CHGBK-_90007-RZP ADJ")
    assert RegexProposer("A3", TWINS).propose(line, []) == []


def test_b2_matches_a_single_negative_net():
    dispute = GatewayTxn(entity_id="disp_1", type="dispute", amount_paise=4_500,
                         settled_at=f"{DAY}T18:30:00+05:30")
    line = BankLine("bl_0001", DAY, DAY, "CHGBK-RZP ADJ", None, 4_500, 0, 0)
    claims = LookupProposer("B2", [dispute]).propose(line, [dispute])
    won, verdict = resolve([(c, check(c, line, {"disp_1": dispute})) for c in claims])
    assert won.composition == ("disp_1",) and verdict.ok


def test_no_proposer_constructs_a_verdict():
    """The proposal layer creates candidates and approves nothing (§7.1). A gate is
    not importable from here by convention alone — this is the check."""
    assert not grep(r"Verdict", ["matcher/proposers/"])
