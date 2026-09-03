"""§12's four endpoints, and the shape the UI depends on.

No server is started. FastAPI's `TestClient` calls the app in-process, which is what
makes these tests cheap enough to keep — and the endpoints are thin enough that the
interesting assertions are about *shape*, not about HTTP.

The one thing worth guarding hard is that a bank line is served as a proof **or** as
an exception and never as something that could be read as either. §13's first rule
is that the two nouns are never conflated, and a payload that carried both keys would
let a front end render a refusal as a match.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import (PHASES, RunRequest, app, build_report, line_detail,
                      run_notes)
from generator.config import (UNIQUENESS_NODE_BUDGET_DEMO,
                              UNIQUENESS_NODE_BUDGET_OFFLINE)
from scoring.score import BUCKETS

SEED42 = Path("data/runs/seed42")


@pytest.fixture(scope="module")
def report():
    """The committed board, through the API's serialiser rather than the CLI's.

    `deadline_ms=None` on purpose: §11's reproducible mode. With a wall clock these
    counts would be a property of the machine running the suite.
    """
    return build_report(SEED42, deadline_ms=None)


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_the_report_carries_both_nouns_and_they_differ(report):
    """§13: bank lines are closed or open, transactions are tied. Two counts, two
    words, and on this board they differ by an order of magnitude."""
    assert report["closed"] + report["open"] == report["bank_lines"] == 134
    assert report["transactions"] == 3009
    assert report["transactions_tied"] == report["residue"]["census"]["claimed"]
    assert report["transactions_tied"] > report["bank_lines"]


def test_the_headline_ships_with_its_denominator(report):
    """Issue 1. `recall 100.0%` beside `35 open` is not a contradiction and not a
    bug — the headline bucket is verified-unique lines plus refusals on lines nobody
    rigged, and at the live budget most lines land in `unproven` instead. But an
    unlabelled percentage over an invisible denominator is exactly the kind of
    number this project refuses, so `headline_n` and every held-out bucket ship
    with it and the UI prints both.
    """
    assert report["headline_n"] == sum(report["counts"].values())
    names = [b["name"] for b in report["buckets"]]
    assert names[0] == "headline"
    assert set(names) == set(BUCKETS) - {"excluded"}
    total = sum(b["n"] for b in report["buckets"])
    assert total == report["bank_lines"]
    assert report["headline_n"] < total, (
        "if the headline ever covers the whole board this test is vacuous")
    held = [b for b in report["buckets"] if not b["in_headline"]]
    assert any(b["counts"].get("FN") for b in held), (
        "the FN the headline does not see must be visible in a named bucket")


def test_the_gap_ships_its_composition(report):
    """Issue 2. The `?`/`!` mark alone is an indicator nobody can take apart, and
    one of those gets ignored. Every figure behind the gap travels with it."""
    r = report["residue"]
    assert r["gap_paise"] == r["open_lines_paise"] - r["unclaimed_due_paise"]
    assert r["matcher_delta_paise"] == r["gap_paise"] - r["baseline_gap_paise"]
    assert r["composition"] and all(isinstance(x, str) for x in r["composition"])
    assert any("before any line matched" in x for x in r["composition"])


def test_the_open_column_can_split_risk_from_documentation(report):
    """Issue 3 and 4 share a root: `reversal_pairs` does run in the API path and
    types all six lines correctly, but pricing both halves of a contra as exposure
    made AT RISK a number that was always too big."""
    led = report["ledger"]
    assert led["at_risk_paise"] + led["documentation_paise"] == sum(
        e["amount_at_risk_paise"] for e in led["exceptions"])
    dup = [e for e in led["exceptions"] if e["exception_type"] == "DUPLICATE_CREDIT"]
    assert dup, "seed 42 injects DUPLICATE_CREDIT; the reversal rule must be live"
    assert all(e["risk_class"] == "documentation" and e["reverses"] for e in dup)
    # Every pair is mutual — a row whose partner does not point back is a half-pair.
    partners = {e["bank_line_id"]: e["reverses"] for e in dup}
    assert all(partners[v] == k for k, v in partners.items())
    assert led["nets_to_zero_paise"] * 2 == sum(e["amount_at_risk_paise"] for e in dup)


def test_the_residue_gap_reaches_the_header(report):
    """The global honesty indicator (§13) has to be in the payload the header
    renders, not buried in the ledger."""
    assert report["residue"]["gap_paise"] == 199_126
    assert report["residue"]["reconciles"] is False
    assert set(report["residue"]["census"]) == {
        "claimed", "unclaimed_due", "not_yet_due", "no_payout_expected"}


def test_every_closed_line_carries_the_arithmetic_that_closed_it(report):
    """I8: no tier returns a match without a balanced proof. The strip renders the
    sum `check()` performed, so the rows must add to the total the gate saw."""
    assert report["closed_lines"]
    for row in report["closed_lines"]:
        proof = row["proof"]
        assert sum(r["amount_paise"] for r in proof["rows"]) == proof["total_paise"]
        assert proof["total_paise"] - proof["target_paise"] == proof["delta_paise"]
        assert proof["delta_paise"] == row["delta_paise"]


def test_provenance_is_on_the_result_never_on_the_claim(report):
    """I9. `source` is output-only, and until stage 12 every match is deterministic
    — reported as such rather than left absent, because absent and 'deterministic'
    render identically and mean different things."""
    assert {row["source"] for row in report["closed_lines"]} == {"deterministic"}
    assert report["via_hypothesis"] == 0
    assert report["ablation"]["detective_available"] is False
    assert report["ablation"]["full_recall"] is None


def test_a_line_is_served_as_a_proof_or_an_exception_never_as_both(report):
    """§13's first rule. A payload that could be read as either would let a front
    end render a refusal as a match, which is the confusion this project exists to
    prevent — so `line_detail` returns one `kind`, never a union."""
    closed = {row["bank_line_id"] for row in report["closed_lines"]}
    open_lines = {b["bank_line_id"] for b in report["ledger"]["exceptions"]
                  if b["bank_line_id"]} - closed
    assert len(closed) + len(open_lines) == report["bank_lines"]
    assert all(line_detail(report, bid)["kind"] == "proof" for bid in sorted(closed))
    assert all(line_detail(report, bid)["kind"] == "exception"
               for bid in sorted(open_lines))


def test_a_contaminated_line_is_closed_and_still_flagged(report):
    """§9.4: an accepted match spanning settlements is flagged for human
    confirmation. It is a *match* — G3 accepted the shape and G2 balanced it — so
    the flag rides on the proof rather than replacing it. Dropping either half
    would be the lie: hide the flag and a mis-tagged transaction is absorbed
    silently; hide the proof and a balanced line reads as unexplained.
    """
    closed = {row["bank_line_id"]: row for row in report["closed_lines"]}
    both = [e for e in report["ledger"]["exceptions"]
            if e["bank_line_id"] in closed]
    assert both, "seed 42 injects SETTLEMENT_CONTAMINATION; this path must be live"
    assert {e["exception_type"] for e in both} == {"SETTLEMENT_CONTAMINATION"}
    for exc in both:
        row = closed[exc["bank_line_id"]]
        assert row["flags"], "the closed row must carry the flag it was given"
        assert row["proof"]["delta_paise"] == 0


def test_an_unknown_line_is_a_404(report):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        line_detail(report, "bl_nope")


def test_listing_runs_is_a_directory_glob(client, tmp_path, monkeypatch):
    """§12: `GET /api/runs` is a glob over `data/runs/*/report.json`. No index to
    keep in sync — and a directory holding no report is simply not listed."""
    import api.main as api
    monkeypatch.setattr(api, "RUNS", tmp_path)
    (tmp_path / "run_a").mkdir()
    (tmp_path / "run_a" / "report.json").write_text(json.dumps(
        {"seed": 1, "bank_lines": 4, "closed": 3, "open": 1, "recall": 0.75,
         "residue": {"gap_paise": 0}}), encoding="utf-8")
    (tmp_path / "run_b").mkdir()          # no report — mid-write, not an error

    body = client.get("/api/runs").json()
    assert [r["run_id"] for r in body["runs"]] == ["run_a"]
    assert body["runs"][0]["residue_gap_paise"] == 0


def test_a_finished_run_is_served_from_disk_after_a_restart(client, tmp_path,
                                                            monkeypatch):
    """The glob is the store. In-flight progress dies with the process; nothing
    finished does."""
    import api.main as api
    monkeypatch.setattr(api, "RUNS", tmp_path)
    (tmp_path / "run_x").mkdir()
    (tmp_path / "run_x" / "report.json").write_text(json.dumps(
        {"closed": 2, "bank_lines": 3, "elapsed_ms": 10}), encoding="utf-8")

    body = client.get("/api/runs/run_x").json()
    assert body["status"] == "done" and body["progress"] == 1.0
    assert client.get("/api/runs/nope").status_code == 404


def test_the_phase_enum_is_the_specs(client):
    """§12 lists eleven phases and the detective's two are among them. They are
    reported even though stage 12 has not built them — a phase that vanished would
    make the ladder look shorter than the spec says it is."""
    assert PHASES[0] == "generating" and PHASES[-1] == "done"
    assert "detective_a" in PHASES and "detective_b" in PHASES
    assert "propagation_2" in PHASES


def test_use_llm_is_disclosed_when_phase_d_cannot_run():
    """I4 and honesty. Phase D exists as of stage 12, but a run without API
    credentials cannot use it — and a board reporting `use_llm: true` as satisfied
    would put a number on the screen no model produced. Accepted, not run, disclosed.

    Asserted on the substance: when the detective is unavailable the note says so
    and names the ablated configuration; when it is available there is nothing to
    disclose, because the pass actually ran.
    """
    from detective.propose import available

    loud = run_notes(RunRequest(use_llm=True))
    quiet = run_notes(RunRequest(use_llm=False))
    assert not any("Phase D" in note for note in quiet)
    if available():
        assert not any("Phase D" in note for note in loud), (
            "credentials resolved, so there is nothing to disclose")
    else:
        assert any("Phase D could not run" in note and "ablated" in note
                   for note in loud)


def test_the_generation_budget_is_named_on_every_run():
    """§10.1: the node budget is not a performance knob, it is what decides whether
    the uniqueness guarantee holds — so a board must say which one produced it.

    Asserted on the substance rather than the phrasing: the demo budget's own figure
    appears, and so does the offline figure it is being compared against. Stage 11b
    moved the demo budget from 20k to 5M precisely because the old one put 57 of 134
    lines in `unproven` and measured a different board from the journals.
    """
    note = run_notes(RunRequest())[0]
    assert f"{UNIQUENESS_NODE_BUDGET_DEMO:,}" in note
    assert f"{UNIQUENESS_NODE_BUDGET_OFFLINE:,}" in note
    assert "unproven" in note


def test_the_demo_budget_reaches_the_offline_verified_population():
    """The measured claim behind stage 11b's choice of 5M, pinned so a future edit
    to the constant has to argue with it.

    The sweep in `generator/config.py` shows `verified` reaching 92 at 5M and staying
    there through 40M. A budget below the knee is not a slower demo, it is a
    different measurement.
    """
    assert UNIQUENESS_NODE_BUDGET_DEMO < UNIQUENESS_NODE_BUDGET_OFFLINE
    assert UNIQUENESS_NODE_BUDGET_DEMO >= 5_000_000, (
        "below the measured knee the headline population shrinks; see the sweep "
        "table in generator/config.py")
