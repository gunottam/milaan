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


def test_use_llm_is_honoured_by_being_refused():
    """I4 and honesty. The detective is stage 12; a run that reported `use_llm` as
    satisfied would put a number on the board no code produced, so the request is
    accepted, ignored, and disclosed on the board itself."""
    quiet = run_notes(RunRequest(use_llm=False))
    loud = run_notes(RunRequest(use_llm=True))
    assert any("live budget" in note for note in quiet)
    assert not any("stage 12" in note for note in quiet)
    assert any("stage 12" in note and "deterministic" in note for note in loud)


def test_the_live_budget_is_disclosed_on_every_run():
    """§10.1: the node budget is not a performance knob, it is what decides whether
    the uniqueness guarantee holds. A run generated at the live budget and compared
    against a committed offline board is comparing two denominators."""
    assert any("bucket sizes do not compare" in note
               for note in run_notes(RunRequest()))
