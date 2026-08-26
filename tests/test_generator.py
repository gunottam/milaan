"""The generator's own guarantees: reproducible, balanced, and honest about
what it could not prove."""

from __future__ import annotations

import json

from core.models import net_contribution, target
from generator.entities import build
from generator.generate import build_truth, emit

STAMP = "2026-08-24T15:30:00+05:30"
FILES = ("gateway_txns.csv", "bank_statement.csv", "orders.csv", "truth.json")


def _run(tmp_path, name, seed=42, bank_lines=24, records=400, noise="high"):
    data = build(seed, bank_lines, records, noise)
    truth = build_truth(data, seed, noise, 2, STAMP)
    out = tmp_path / name
    emit(out, data, truth)
    return data, truth, out


def test_the_same_seed_reproduces_byte_identical_output(tmp_path):
    _, _, a = _run(tmp_path, "a")
    _, _, b = _run(tmp_path, "b")
    for name in FILES:
        assert (a / name).read_bytes() == (b / name).read_bytes(), name


def test_a_different_seed_produces_different_data(tmp_path):
    _, _, a = _run(tmp_path, "a")
    _, _, c = _run(tmp_path, "c", seed=43)
    assert (a / "gateway_txns.csv").read_bytes() != (c / "gateway_txns.csv").read_bytes()


def test_the_record_count_is_exact(tmp_path):
    data, _, _ = _run(tmp_path, "a", records=400)
    assert len(data.txns) == 400
    assert len({t.entity_id for t in data.txns}) == 400


def test_every_bank_line_ties_to_its_settlement_to_the_paise(tmp_path):
    data, _, _ = _run(tmp_path, "a")
    by_id = {t.entity_id: t for t in data.txns}
    for settlement, line in zip(data.settlements, data.bank_lines):
        assert settlement.bank_line_id == line.bank_line_id
        composed = sum(net_contribution(by_id[e]) for e in settlement.entity_ids)
        assert composed == target(line), line.bank_line_id


def test_every_transaction_belongs_to_exactly_one_settlement(tmp_path):
    data, _, _ = _run(tmp_path, "a")
    claimed = [e for s in data.settlements for e in s.entity_ids]
    assert len(claimed) == len(set(claimed)) == len(data.txns)


def test_fees_are_zero_off_the_payment_path(tmp_path):
    # I7: everything that is not a payment carries fee_paise = 0 by construction,
    # so the §4.2 recompute check must never be pointed at it.
    data, _, _ = _run(tmp_path, "a")
    for t in data.txns:
        if t.type != "payment":
            assert (t.fee_paise, t.tax_paise, t.tds_paise) == (0, 0, 0), t.entity_id


def test_every_resolvable_line_records_its_uniqueness(tmp_path):
    _, truth, _ = _run(tmp_path, "a")
    for bank_line_id, record in truth["bank_lines"].items():
        if record["resolvable"]:
            assert record["uniqueness"] in ("verified", "budget_exhausted"), bank_line_id
            assert record["composition"], bank_line_id
            if record["uniqueness"] == "budget_exhausted":
                assert record["excluded_from_scoring"] is True
        else:
            assert record["composition"] is None
            assert record["injected_breaks"] == ["AMBIGUOUS_SUBSET"]
            assert record["ambiguity_class"] in ("equivalent", "consequential")


def test_truth_is_json_and_carries_the_run_config(tmp_path):
    _, _, out = _run(tmp_path, "a", bank_lines=24, records=400)
    truth = json.loads((out / "truth.json").read_text())
    assert truth["seed"] == 42
    assert truth["generated_at"] == STAMP
    assert truth["config"] == {"bank_lines": 24, "records": 400,
                               "noise": "high", "window_days": 2}
    assert len(truth["bank_lines"]) == 24


def test_high_noise_leaves_about_30pc_of_narrations_unparseable(tmp_path):
    # §3.4: at --noise high, ~30% of narrations must be unparseable by regex alone.
    data, _, _ = _run(tmp_path, "a", bank_lines=120, records=1200)
    rate = data.unrecoverable_narrations / len(data.bank_lines)
    assert 0.22 <= rate <= 0.38, rate


def test_low_noise_leaves_almost_everything_parseable(tmp_path):
    data, _, _ = _run(tmp_path, "a", bank_lines=120, records=1200, noise="low")
    assert data.unrecoverable_narrations / len(data.bank_lines) <= 0.05
