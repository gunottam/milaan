"""The manifest must match reality. §5, §6.1.

A break that claims to fire but does not is worse than one that is missing, so
every count below is **recounted from the emitted dataset**, not read back from the
injector that produced it. Where a break leaves no signature in the data that can
be told apart from baseline noise, the count comes from the truth records instead
and the test says so.
"""

from __future__ import annotations

import warnings

import pytest

from core.models import net_contribution, target
from generator.breaks import BREAK_COUNTS



@pytest.fixture(scope="module")
def run(seed42):
    data, truth = seed42
    return data, truth


def counted(truth, code: str) -> int:
    return truth["break_manifest"][code]["injected"]


def lines_flagged(truth, code: str) -> list[str]:
    return [k for k, v in truth["bank_lines"].items()
            if code in v.get("injected_breaks", [])]


def payouts(data):
    """settlement -> (members, its bank line)."""
    by_id = {t.entity_id: t for t in data.txns}
    lines = {line.bank_line_id: line for line in data.bank_lines}
    return [(s, [by_id[e] for e in s.entity_ids], lines[s.bank_line_id])
            for s in data.settlements if s.bank_line_id in lines]


# --- the manifest is complete and honest -------------------------------------


def test_the_manifest_covers_the_fifteen_injected_breaks(run):
    _, truth = run
    assert set(truth["break_manifest"]) == set(BREAK_COUNTS)
    for code, record in truth["break_manifest"].items():
        assert set(record) == {"injected", "caught", "missed"}, code
        # caught/missed belong to scoring in stage 7; the generator cannot know them
        assert record["caught"] is None and record["missed"] is None


def test_every_injected_break_actually_fired(run):
    """`injected <= requested` would pass at zero. Each code must have fired."""
    _, truth = run
    dead = [code for code, r in truth["break_manifest"].items() if r["injected"] == 0]
    assert not dead, dead


def test_a_shortfall_against_the_requested_count_is_visible(run):
    """Firing fewer times than asked is legitimate — an injector can run out of
    eligible settlements — but it must not be silent."""
    _, truth = run
    short = {code: (r["injected"], BREAK_COUNTS[code])
             for code, r in truth["break_manifest"].items()
             if r["injected"] < BREAK_COUNTS[code]}
    if short:
        warnings.warn(f"breaks fired fewer times than requested: {short}",
                      stacklevel=2)


def test_the_three_manifest_sections_are_disjoint_and_complete(run):
    _, truth = run
    assert set(truth["emergent_breaks"]) == {"AMBIGUOUS_SUBSET"}
    assert set(truth["emergent_breaks"]["AMBIGUOUS_SUBSET"]) == {
        "count", "refused", "matched"}
    # Nothing to detect in these two, so they are never scored per-break.
    assert set(truth["baseline_properties"]) == {"TDS_DEDUCTION", "CROSS_CYCLE_REFUND"}
    sections = (set(truth["break_manifest"]), set(truth["emergent_breaks"]),
                set(truth["baseline_properties"]))
    assert sum(len(x) for x in sections) == len(set().union(*sections)) == 18


# --- recounted from the data --------------------------------------------------


def test_timing_shift(run):
    data, truth = run
    shifted = {s.settlement_id for s, members, _ in payouts(data)
               if any(t.settled_at[:10] > s.cycle_date and not t.on_hold
                      for t in members)}
    assert len(shifted) == counted(truth, "TIMING_SHIFT")


def test_onhold_release(run):
    data, truth = run
    held = {s.settlement_id for s, members, _ in payouts(data)
            if any(t.on_hold for t in members)}
    assert len(held) == counted(truth, "ONHOLD_RELEASE")


def test_dispute_debit(run):
    data, truth = run
    disputes = [t for t in data.txns if t.type == "dispute"]
    chargebacks = [line for line in data.bank_lines
                   if line.narration.startswith("CHGBK-")]
    assert len(disputes) == len(chargebacks) == counted(truth, "DISPUTE_DEBIT")
    for line in chargebacks:                     # a debit line, signed target (8.1)
        assert target(line) < 0


def test_rounding_drift_is_the_allocation_remainder(run):
    data, truth = run
    split = {k for k, v in truth["bank_lines"].items() if v.get("requires_tier")}
    drifted = [(s, members, line) for s, members, line in payouts(data)
               if line.bank_line_id not in split
               and sum(t.net for t in members) != target(line)
               and abs(sum(t.net for t in members) - target(line)) <= len(members)]
    assert len(drifted) == counted(truth, "ROUNDING_DRIFT")
    for s, members, line in drifted:
        delta = target(line) - sum(t.net for t in members)
        # §8.2's double cap: within a rupee AND within one paise per transaction
        assert 0 < abs(delta) <= min(100, len(members))
        assert truth["bank_lines"][line.bank_line_id]["expected_delta_paise"] == delta


def test_duplicate_credit_has_a_t_plus_one_reversal(run):
    data, truth = run
    reversals = [line for line in data.bank_lines if line.narration.startswith("REV-")]
    assert len(reversals) == counted(truth, "DUPLICATE_CREDIT")
    for line in reversals:                       # the reversal is a debit
        assert line.debit_paise > 0 and line.credit_paise == 0
    # both halves of every pair are unresolvable: no transaction composes them
    assert len(lines_flagged(truth, "DUPLICATE_CREDIT")) == 2 * len(reversals)


def test_route_split(run):
    data, truth = run
    transfers = [t for t in data.txns if t.type == "transfer"]
    assert len(transfers) == counted(truth, "ROUTE_SPLIT")
    for t in transfers:                          # a negative term inside the payout
        assert net_contribution(t) < 0


def test_instant_settlement_is_off_cycle_and_carries_the_flat_fee(run):
    data, truth = run
    instant = [s for s in data.settlements if s.settlement_id.startswith("setl_9")]
    assert len(instant) == counted(truth, "INSTANT_SETTLEMENT")
    for s, _, line in payouts(data):
        if s.settlement_id.startswith("setl_9"):
            assert line.narration.startswith("INSTSETL")


def test_settlement_contamination(run):
    data, truth = run
    paid_out_by = {e: s.settlement_id for s in data.settlements for e in s.entity_ids}
    mistagged = [t for t in data.txns
                 if t.settlement_id and t.entity_id in paid_out_by
                 and t.settlement_id != paid_out_by[t.entity_id]]
    assert len(mistagged) == counted(truth, "SETTLEMENT_CONTAMINATION")


def test_negative_settlement_produces_a_bank_debit(run):
    data, truth = run
    negative = [line for s, members, line in payouts(data)
                if sum(t.net for t in members) < 0]
    assert len(negative) == counted(truth, "NEGATIVE_SETTLEMENT")
    for line in negative:
        assert line.debit_paise > 0 and line.credit_paise == 0


def test_net_zero_settlement_produces_no_bank_line_at_all(run):
    data, truth = run
    notes = truth["settlements"]
    assert len(notes) == counted(truth, "NET_ZERO_SETTLEMENT")
    by_id = {t.entity_id: t for t in data.txns}
    paid = {s.settlement_id for s in data.settlements}
    for settlement_id, note in notes.items():
        assert note["no_payout_expected"] is True
        assert sum(by_id[e].net for e in note["entity_ids"]) == 0
        assert settlement_id not in paid          # §5.1: no payout, so no line, ever


def test_withheld_record_leaves_a_gap_no_composition_can_close(run):
    data, truth = run
    # A SPLIT_PAYOUT half legitimately does not tie to its whole settlement — its
    # composition is the half, checked in its own test — so exclude those.
    split = {k for k, v in truth["bank_lines"].items() if v.get("requires_tier")}
    gaps = [line for s, members, line in payouts(data)
            if line.bank_line_id not in split
            and abs(sum(t.net for t in members) - target(line)) > 100]
    assert len(gaps) == counted(truth, "WITHHELD_RECORD")
    for line in gaps:
        record = truth["bank_lines"][line.bank_line_id]
        assert record["resolvable"] is False
        assert record["injected_breaks"] == ["WITHHELD_RECORD"]
        assert "missing from the gateway export" in record["unresolvable_reason"]


def test_orphan_order_has_no_gateway_payment(run):
    data, truth = run
    linked = {t.order_id for t in data.txns if t.type == "payment"}
    orphans = [o for o in data.orders if o.status == "paid" and o.order_id not in linked]
    assert len(orphans) == counted(truth, "ORPHAN_ORDER")


def test_split_payout_keeps_the_real_composition_and_names_the_tier(run):
    data, truth = run
    split = {k: v for k, v in truth["bank_lines"].items()
             if v.get("requires_tier") == "C3"}
    assert len(split) == 2 * counted(truth, "SPLIT_PAYOUT")
    by_id = {t.entity_id: t for t in data.txns}
    lines = {line.bank_line_id: line for line in data.bank_lines}
    for bank_line_id, record in split.items():
        # resolvable: true with the real halves. Truth describes the data, not the
        # matcher's current reach, so these score FN until C3 and TP after.
        assert record["resolvable"] is True
        assert record["composition"]
        assert sum(by_id[e].net for e in record["composition"]) == \
            target(lines[bank_line_id])
        assert record["split_partner"] in truth["bank_lines"]


def test_fx_markup_folds_into_fee_paise(run):
    data, truth = run
    # No data-side signature separates an injected international payment from a
    # baseline intl_card one, so this count comes from the truth flags.
    flagged = lines_flagged(truth, "FX_MARKUP")
    assert len(flagged) == counted(truth, "FX_MARKUP")
    for s, members, _ in payouts(data):
        if s.bank_line_id in flagged:
            intl = [t for t in members if t.international]
            assert intl, s.settlement_id
            for t in intl:                        # I7: never a separate term
                assert t.fee_paise > 0 and t.source_currency == "USD"


def test_narration_truncated(run):
    _, truth = run
    # Baseline degradation emits the same template, so the injected ones are only
    # distinguishable through the truth flag.
    assert len(lines_flagged(truth, "NARRATION_TRUNCATED")) == \
        counted(truth, "NARRATION_TRUNCATED")


# --- baseline properties -----------------------------------------------------


def test_baseline_property_counts_match_the_data(run):
    data, truth = run
    props = truth["baseline_properties"]
    strays = [t for t in data.txns if t.settlement_id is None]
    assert props["CROSS_CYCLE_REFUND"] == len(strays)
    for t in strays:
        assert t.type in ("refund", "dispute")

    by_id = {t.entity_id: t for t in data.txns}
    tds = sum(1 for r in truth["bank_lines"].values()
              if r.get("composition")
              and any(by_id[e].tds_paise for e in r["composition"] if e in by_id))
    assert props["TDS_DEDUCTION"] == tds


def test_emergent_ambiguity_count_matches_the_records(run):
    _, truth = run
    ambiguous = [k for k, v in truth["bank_lines"].items()
                 if "AMBIGUOUS_SUBSET" in v.get("injected_breaks", [])]
    assert truth["emergent_breaks"]["AMBIGUOUS_SUBSET"]["count"] == len(ambiguous)
    for k in ambiguous:
        record = truth["bank_lines"][k]
        assert record["resolvable"] is False
        assert record["ambiguity_class"] in ("equivalent", "consequential")


def test_ambiguity_is_reachable_at_all(run):
    """The whole point of shared windows: without a decoy in the pool, G5 is dead
    code and the refusal path can never be exercised."""
    _, truth = run
    assert truth["emergent_breaks"]["AMBIGUOUS_SUBSET"]["count"] > 0


def test_every_ambiguous_pair_is_coherent_on_both_sides(run):
    """Both alternatives must pass G3, or the ambiguity is not real — the matcher
    would reject one and resolve the line, and truth would score that as a false
    positive."""
    data, truth = run
    from core.coherence import is_plausible_payout
    by_id = {t.entity_id: t for t in data.txns}
    for record in truth["bank_lines"].values():
        for alternative in record.get("alternate_compositions", []):
            assert is_plausible_payout(alternative, by_id)


def test_no_line_is_excluded_from_scoring(run):
    """An unproven line keeps its composition and its place in the denominators.
    Excluding it would drop the hardest lines and inflate recall."""
    _, truth = run
    assert not [k for k, v in truth["bank_lines"].items()
                if v.get("excluded_from_scoring")]
    unproven = [k for k, v in truth["bank_lines"].items()
                if v.get("uniqueness") == "unproven"]
    for k in unproven:
        assert truth["bank_lines"][k]["resolvable"] is True
        assert truth["bank_lines"][k]["composition"]
