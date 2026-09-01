"""The API. §12.

**Polling at 500 ms. No SSE, no SQLite.** Both are rulings, not omissions. The run
is under 60 s, so an event stream buys nothing a poll does not and adds a reconnect
path to debug in the demo room; and a store that is written once and only ever
listed is a directory glob over `data/runs/*/report.json`, not a database.

The state a run needs while it is *in flight* — its phase and its progress — is
genuinely ephemeral, so it lives in a dict guarded by a lock and dies with the
process. The state that matters afterwards is the report, and that is a file. A
restart loses the progress bars of runs in flight and no finished work at all,
which is the correct thing to lose.

**The report is the CLI's report.** `scoring.score` already assembles the board,
Phase E and the ledger; this module runs the same functions and serialises the
result. Two renderers over one computation — if the API had its own scoring path,
the number on the screen and the number in the terminal could disagree, and the
whole project is an argument that a figure should be derivable twice and agree.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core.models import BankLine, GatewayTxn, Order, read_csv, target
from generator.config import (SETTLEMENT_WINDOW_DAYS,
                              UNIQUENESS_NODE_BUDGET_LIVE)
from generator.generate import emit, generate
from matcher.run import MATCH_DEADLINE_MS, run_ladder
from scoring.score import phase_e, precision, recall, score

RUNS = Path("data/runs")

# §12's phase enum, in order. `detective_a` and `detective_b` are listed because the
# spec lists them; they are skipped until stage 12 builds the detective, and the run
# says so rather than idling on a phase that is doing nothing.
PHASES = ("generating", "verifying_uniqueness", "phase_a", "phase_b", "phase_c",
          "detective_a", "detective_b", "propagation_2", "audit", "scoring", "done")

# Tier prefix -> the phase §12 names for it. The ladder reports tiers; the API
# reports phases; this is the whole of the translation.
TIER_PHASE = {"A": "phase_a", "B": "phase_b", "C": "phase_c"}

app = FastAPI(title="Milaan", description=__doc__)

# The dev server is Vite on another port. Same machine, same person, one demo.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


class RunRequest(BaseModel):
    """§12's POST body.

    `bank_lines` is the generator's *payout* count, not the emitted line count —
    breaks add lines (a `SPLIT_PAYOUT` makes two, a `DUPLICATE_CREDIT` makes two
    more) and remove them (`NET_ZERO_SETTLEMENT` makes none at all), so 120 payouts
    emit 134 lines. The field keeps §12's name and the response reports both.
    """

    seed: int = 42
    bank_lines: int = Field(default=120, ge=1, le=400)
    records: int = Field(default=3_000, ge=10, le=20_000)
    noise: str = "high"
    use_llm: bool = False


@dataclass
class RunState:
    """One run in flight. Everything here is ephemeral by design."""

    run_id: str
    request: RunRequest
    status: str = "running"          # running | done | error
    phase: str = "generating"
    progress: float = 0.0
    closed: int = 0
    bank_lines: int = 0
    started_ns: int = field(default_factory=time.monotonic_ns)
    elapsed_ms: int = 0
    error: str | None = None
    report: dict | None = None
    notes: list[str] = field(default_factory=list)


_STATE: dict[str, RunState] = {}
_LOCK = threading.Lock()


def _touch(state: RunState, **fields) -> None:
    """Publish a state change. The lock is held only for the assignment — the work
    happens outside it, so a poll never waits on a search."""
    with _LOCK:
        for key, value in fields.items():
            setattr(state, key, value)
        state.elapsed_ms = (time.monotonic_ns() - state.started_ns) // 1_000_000


def build_report(run_dir: Path, deadline_ms: int | None = MATCH_DEADLINE_MS,
                 on_tier=None) -> dict:
    """Match, audit, score and serialise one run directory.

    The same three calls `scoring.score.main` makes, in the same order, so the JSON
    the browser renders and the text the terminal prints come out of one
    computation (§11's reproducibility argument applies to the *inputs*; this is
    the weaker and more practical claim that there is only one implementation).
    """
    truth = json.loads((run_dir / "truth.json").read_text(encoding="utf-8"))
    txns = read_csv(run_dir / "gateway_txns.csv", GatewayTxn)
    bank_lines = read_csv(run_dir / "bank_statement.csv", BankLine)
    orders = read_csv(run_dir / "orders.csv", Order)

    ladder = run_ladder(txns, bank_lines, truth["config"]["window_days"],
                        deadline_ms=deadline_ms, on_tier=on_tier)
    compositions = {bid: claim.composition
                    for bid, (_, claim, _) in ladder.matched.items()}
    if on_tier is not None:
        on_tier("audit", 0, len(compositions))
    residue, ledger = phase_e(txns, bank_lines, orders, ladder)
    if on_tier is not None:
        on_tier("scoring", 0, len(compositions))
    report = score(truth, compositions)

    counts = report.counts("headline")
    lines = {b.bank_line_id: b for b in bank_lines}
    tiers = {tier for tier, _, _ in ladder.matched.values()}

    # §9.4: accepted matches spanning more than one settlement are flagged
    # `SETTLEMENT_CONTAMINATION` for human confirmation. The line is *closed* — G3
    # accepted the shape and G2 balanced it — so the flag rides on the proof rather
    # than replacing it. A closed line that also appears in the ledger is not a
    # contradiction; it is a match a human should still look at, and dropping
    # either half would be the lie.
    flags: dict[str, list[str]] = {}
    for exc in ledger.exceptions:
        if exc.exception_type == "SETTLEMENT_CONTAMINATION" and exc.bank_line_id:
            flags.setdefault(exc.bank_line_id, []).extend(exc.evidence)

    closed = [{
        "bank_line_id": bid,
        "value_date": lines[bid].value_date,
        "target_paise": target(lines[bid]),
        "tier": tier,
        "confidence": verdict.confidence,
        "delta_paise": verdict.delta_paise,
        "anchor_settlement_id": claim.anchor_settlement_id,
        "composition_size": len(claim.composition),
        # §13's proof strip, and the reason it is served rather than recomputed in
        # the browser: this is the sum `check()` actually performed, kept instead of
        # thrown away (I8). A front end that re-derived it from the composition
        # would be a second implementation of the arithmetic, and the point of the
        # strip is that a human reads the same figures the gate did.
        "proof": {
            "rows": [{"label": label, "count": count, "amount_paise": amount}
                     for label, count, amount in verdict.proof.rows],
            "total_paise": verdict.proof.total_paise,
            "target_paise": verdict.proof.target_paise,
            "delta_paise": verdict.proof.delta_paise,
        },
        # §13: hypothesis-sourced matches carry the `--hypo` marker so provenance is
        # never ambiguous. `source` is stamped here, on the *result* — never on
        # `Claim` (I9). Every match is deterministic until stage 12 builds the
        # detective, and the field says which rather than being absent.
        "source": "deterministic",
        "flags": flags.get(bid, []),
    } for bid, (tier, claim, verdict) in sorted(ladder.matched.items())]

    return {
        "run": str(run_dir), "seed": truth["seed"],
        "config": truth["config"],
        "bank_lines": len(bank_lines),
        "transactions": len(txns),
        "closed": len(ladder.matched),
        "open": len(bank_lines) - len(ladder.matched),
        # §13's two nouns, never conflated. Bank lines are closed or open;
        # transactions are tied. The census is the only place the second number
        # exists, which is why it is read from the audit rather than recomputed.
        "transactions_tied": residue.census["claimed"],
        "counts": dict(counts),
        "precision": precision(counts), "recall": recall(counts),
        "exact": sum(1 for c in closed if c["confidence"] == "exact"),
        "tolerance": sum(1 for c in closed if c["confidence"] == "tolerance"),
        "via_hypothesis": sum(1 for c in closed if c["source"] == "hypothesis"),
        "tiers_used": sorted(tiers),
        "by_tier": {t: sum(1 for c in closed if c["tier"] == t)
                    for t in sorted(tiers)},
        "residue": {
            "gap_paise": residue.gap_paise,
            "open_lines_paise": residue.open_lines_paise,
            "unclaimed_due_paise": residue.unclaimed_due_paise,
            "census": dict(residue.census), "sums": dict(residue.sums),
            "reconciles": residue.reconciles, "partial": residue.partial,
        },
        "ledger": ledger.as_dict(),
        "closed_lines": closed,
        "deadline": {
            "hit": ladder.deadline_hit, "ms": ladder.deadline_ms,
            "banner": ladder.banner(),
            "exceeded": list(ladder.exceeded), "cut": list(ladder.cut),
            "passes_run": ladder.passes_run, "passes_asked": ladder.passes_asked,
        },
        # §11: the wall clock is a property of the machine, so it is reported
        # beside the board and never folded into it.
        "elapsed_ms": ladder.elapsed_ms,
        # Stage 12 has not happened. The ablation delta is deterministic-vs-full and
        # there is no full yet, so it is reported absent rather than as a number
        # equal to the deterministic one — those render identically and mean
        # opposite things.
        "ablation": {"deterministic_recall": recall(counts), "full_recall": None,
                     "detective_available": False},
    }


def run_notes(request: RunRequest) -> list[str]:
    """What the board must say about this run before it says anything else.

    Both notes are disclosures, not decoration. The first is §10.1's: the budget
    decides which lines truth calls `verified` rather than `unproven`, so a live-
    budget board and a committed offline board have different denominators and the
    difference looks exactly like a regression. The second is I4's: the detective
    arrives at stage 12, and reporting `use_llm: true` as satisfied would put a
    number on the screen that no code produced.
    """
    notes = [f"uniqueness verified at {UNIQUENESS_NODE_BUDGET_LIVE:,} nodes (the "
             "live budget) — bucket sizes do not compare with a committed offline "
             "board"]
    if request.use_llm:
        notes.append("use_llm was requested and ignored: Detective Pass A/B is "
                     "stage 12. Every match below is deterministic.")
    return notes


def _execute(state: RunState) -> None:
    """One run, start to finish, on its own thread. Never raises out of the thread."""
    run_dir = RUNS / state.run_id
    try:
        _touch(state, phase="generating", progress=0.05)
        data, truth = generate(
            state.request.seed, state.request.bank_lines, state.request.records,
            state.request.noise, SETTLEMENT_WINDOW_DAYS,
            time.strftime("%Y-%m-%dT%H:%M:%S+05:30"),
            # The LIVE budget, not the offline one (§10.1). Offline generation has
            # no wall clock to answer to and runs at 40M nodes; a request that did
            # that would sit for minutes. The consequence is real and the scoreboard
            # already shouts about it: at 20k, more lines land in `unproven` and
            # fewer are proven `AMBIGUOUS_SUBSET`, so these counts do not compare
            # with a committed offline board.
            UNIQUENESS_NODE_BUDGET_LIVE)
        _touch(state, phase="verifying_uniqueness", progress=0.25,
               bank_lines=len(data.bank_lines))
        emit(run_dir, data, truth)

        def on_tier(name: str, pass_no: int, closed: int) -> None:
            phase = TIER_PHASE.get(name[:1], name)
            if pass_no > 1 and phase.startswith("phase_"):
                phase = "propagation_2"
            total = max(len(data.bank_lines), 1)
            _touch(state, phase=phase, closed=closed,
                   # Real progress: closed lines over total, floored at the point
                   # generation left off. Nothing here interpolates against a timer.
                   progress=0.3 + 0.6 * closed / total)

        state.notes.extend(run_notes(state.request))

        report = build_report(run_dir, on_tier=on_tier)
        (run_dir / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _touch(state, status="done", phase="done", progress=1.0,
               closed=report["closed"], report=report)
    except Exception as exc:                       # noqa: BLE001 — reported, not raised
        _touch(state, status="error", error=f"{type(exc).__name__}: {exc}")


# --- §12's four endpoints ----------------------------------------------------


@app.post("/api/runs")
def create_run(request: RunRequest) -> dict:
    """`-> { run_id }`. Returns immediately; the work happens on a thread."""
    run_id = f"run_{request.seed}_{uuid.uuid4().hex[:8]}"
    state = RunState(run_id=run_id, request=request)
    with _LOCK:
        _STATE[run_id] = state
    threading.Thread(target=_execute, args=(state,), daemon=True).start()
    return {"run_id": run_id}


@app.get("/api/runs")
def list_runs() -> dict:
    """A directory glob over `data/runs/*/report.json`. §12, verbatim — no index to
    keep in sync, and nothing to migrate."""
    found = []
    for path in sorted(RUNS.glob("*/report.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue                    # a run mid-write is not an error to report
        found.append({
            "run_id": path.parent.name, "seed": report.get("seed"),
            "bank_lines": report.get("bank_lines"),
            "closed": report.get("closed"), "open": report.get("open"),
            "residue_gap_paise": report.get("residue", {}).get("gap_paise"),
            "recall": report.get("recall"),
        })
    with _LOCK:
        running = [{"run_id": s.run_id, "status": s.status, "phase": s.phase}
                   for s in _STATE.values() if s.status == "running"]
    return {"runs": found, "running": running}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    """`-> { status, phase, progress, report? }`, polled at 500 ms.

    A run this process did not start is served from its `report.json` — the glob is
    the store, so a restart loses progress bars and no finished work.
    """
    with _LOCK:
        state = _STATE.get(run_id)
    if state is not None:
        return {"run_id": run_id, "status": state.status, "phase": state.phase,
                "progress": round(state.progress, 3), "closed": state.closed,
                "bank_lines": state.bank_lines, "elapsed_ms": state.elapsed_ms,
                "error": state.error, "notes": state.notes,
                "phases": list(PHASES), "report": state.report}

    path = RUNS / run_id / "report.json"
    if not path.is_file():
        raise HTTPException(404, f"no run {run_id}")
    report = json.loads(path.read_text(encoding="utf-8"))
    return {"run_id": run_id, "status": "done", "phase": "done", "progress": 1.0,
            "closed": report["closed"], "bank_lines": report["bank_lines"],
            "elapsed_ms": report["elapsed_ms"], "error": None, "notes": [],
            "phases": list(PHASES), "report": report}


def line_detail(report: Mapping, bank_line_id: str) -> dict:
    """§12's third endpoint: a proof, or an exception. Never both, never neither.

    A bank line is closed or it is open (§13's first noun) and the two carry
    different objects — a proof is arithmetic that balanced, an exception is a typed
    refusal. Returning a shape that could be either would let the UI render an
    exception as though it were a match, which is the one confusion this project
    exists to prevent.
    """
    for row in report["closed_lines"]:
        if row["bank_line_id"] == bank_line_id:
            return {"kind": "proof", **row}
    for exc in report["ledger"]["exceptions"]:
        if exc["bank_line_id"] == bank_line_id:
            return {"kind": "exception", **exc}
    raise HTTPException(404, f"no line {bank_line_id}")


@app.get("/api/runs/{run_id}/lines/{bank_line_id}")
def get_line(run_id: str, bank_line_id: str) -> dict:
    return line_detail(get_run(run_id)["report"] or {}, bank_line_id)
