"""§11's multi-seed variance — ten seeds, **precomputed offline, node budget only**
(finding 8.6). Writes `regression.json` and renders it as a ruled table.

Two runs per seed and they answer different questions. Do not merge them.

**The offline run is the measurement.** `deadline_ms=None`, so no clock touches the
search: every figure here is a property of the data and the node budget, and two
machines produce the same bytes. Uniqueness is verified at
`UNIQUENESS_NODE_BUDGET_OFFLINE`, which is what decides how many lines truth can
call `verified` rather than `unproven` (§10.1) — a row generated at a different
budget is not comparable with these and the file records the budget so a reader can
check. The detective is **off**: a live model call is not reproducible, so it cannot
appear in a number whose whole claim is reproducibility. §11's ablation delta is
measured on the committed board, not here.

**The live run is the clock, and nothing else.** Same seed, the demo uniqueness
budget, the run deadline armed, and **Phase D off by default from stage 15** —
which is the configuration a judge triggers from the browser (`use_llm: false`,
`api/main.py::RunRequest`). Its recall is *not* recorded: at the demo budget the
buckets are sized differently, and printing a second recall figure beside the first
would invite the comparison §10.1 says is invalid. What it is for is §15's 60 s
ceiling, measured across ten seeds instead of asserted from seed 42.

**Why Phase D is off in the shipped configuration**, and it is a measurement rather
than a preference: it closed **zero** extra lines on all ten seeds at stage 14, for
297 paise, and it cannot be held to §15's 12 s allocation — the run deadline is
checked between tiers and cannot interrupt a batch in flight, so the same ten seeds
ran 33.8 s – 80.7 s with the model answering against 12.5 s – 24.2 s ablated, over
the ceiling on two of six. `--detective` still measures it; the default does not.
See §15's v1.3.1 amendment and `docs/journal/stage-15.md`.

**Which scoring rule produced these numbers**, because stage 14 nearly changed it:
per-line composition set equality (I5). Pair-scoring a `SPLIT_PAYOUT` — the agent's
union across both halves against truth's union — was measured at **1 TP → 2 TP on
seed 42 and declined**; `docs/build-stages.md` and `docs/journal/stage-13.md` carry
the reason. The refusals it would have bought are reported instead, with the census
that makes them refusals: 279 divisions of `setl_0048`'s payout balance against
`bl_0048`'s credit and the statement does not say which.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from core.models import BankLine, GatewayTxn, Order, read_csv
from generator import config as cfg
from generator.generate import emit, generate
from matcher.run import MATCH_DEADLINE_MS, build_tiers, run_ladder
from scoring.score import (all_lines, anchors_recovered, phase_e, precision,
                           recall, score)

# Ten, fixed. Any set would do and this one is not special — which is the point:
# picking seeds after seeing their numbers is how a variance figure stops being one.
# 42, 7, 99 and 2026 are the seeds the suite already pins, kept first so a reader
# can check a row against a test rather than against this file.
SEEDS = (42, 7, 99, 2026, 1, 5, 13, 23, 101, 777)

ROOT = Path("data/regression")
COMMITTED = Path("data/runs/seed42")

# The rule these numbers are scored under, stated in the file rather than in a
# journal only. §11's TP is set equality on the composition.
SCORING_RULE = ("per-line composition set equality (I5). Pair-scored SPLIT_PAYOUT "
                "measured at 1 TP -> 2 TP on seed 42 and DECLINED — it requires C3 "
                "to commit a division the source data does not determine (two "
                "identical refunds per pair), so it is a false match half the time "
                "by construction. See docs/build-stages.md stage 14 and "
                "docs/journal/stage-13.md.")

# What changed in the matcher between the stage-14 numbers and these, because the
# rule above did not: §3.2's reversal-pair rule became a pre-match exclusion
# (v1.3.1, §9.8). It is monotonically restrictive, so it can only cost recall — and
# it did not: recall rose on the three seeds that carried the false match, because
# the transactions the duplicate consumed went back to the line that earned them.
# §11's ablation delta, and **the pass that measured it**. The default live pass
# runs ablated, and a run with the model off cannot measure the model — so this is
# carried as a recorded result with its provenance rather than recomputed into a
# zero that means "not tried" while reading as "tried and found nothing". Those are
# the two things §13 must never render identically. `--detective` overwrites it with
# a live measurement of the same shape.
PHASE_D_MEASURED = {
    "measured_by": "stage 14 — docs/journal/stage-14.md, ten seeds, live Groq",
    "live": False,
    "seeds": 10,
    "seeds_model_answered": 6,
    "extra_lines_closed": 0,
    "recall_delta": 0.0,
    "cost_paise": 297,
    "note": ("Phase D closed zero extra lines on all ten seeds. A floor, not a "
             "ceiling: four of the ten exhausted Groq's 200,000-token daily cap "
             "and every call came back 429. The demo therefore runs use_llm: "
             "false (§15 v1.3.1)."),
}

MATCHER_CHANGE = ("stage 15: §3.2's reversal-pair rule promoted to a pre-match "
                  "exclusion (matcher/run.py, one implementation shared with §10's "
                  "typing pass). Removed 3 false matches across 10 seeds — all "
                  "DUPLICATE_CREDIT — and withheld no resolvable line on any seed.")


def dataset(seed: int, root: Path = ROOT, *, window_days: int = cfg.SETTLEMENT_WINDOW_DAYS,
            payouts: int = cfg.DEFAULT_PAYOUTS, records: int = cfg.DEFAULT_RECORDS,
            noise: str = "high") -> Path:
    """The offline dataset for one seed, generated once and cached on disk.

    Seed 42 reads the **committed** board rather than a copy of it. Generation is
    deterministic from the seed, so a regenerated seed 42 would be byte-identical —
    but the row a reader will check first is the one the slow set pins, and pointing
    at that directory is the only way the two cannot drift apart.

    A cached directory is reused only when its truth records the same config *and
    the same node budget*. Everything else regenerates: a truth file at another
    budget describes these CSVs with different confidence, and its bucket sizes do
    not compare (§10.1).
    """
    # `records` is deliberately not compared. The config field holds the count
    # *emitted* — breaks add rows — so a requested 3,000 reads back as 3,009 and a
    # check on it regenerates a cached board every time, overwriting the very
    # directory the slow set pins.
    want = {"payouts": payouts, "noise": noise, "window_days": window_days,
            "uniqueness_node_budget": cfg.UNIQUENESS_NODE_BUDGET_OFFLINE}
    run_dir = COMMITTED if seed == 42 else root / f"seed{seed}"
    truth_path = run_dir / "truth.json"
    if truth_path.is_file():
        config = json.loads(truth_path.read_text(encoding="utf-8"))["config"]
        if all(config.get(k) == v for k, v in want.items()):
            return run_dir
    data, truth = generate(seed, payouts, records, noise, window_days,
                           # Pinned, not stamped: `generated_at` is the one field
                           # in truth.json that would make two identical runs
                           # differ, and the CSVs are reproducible from the seed.
                           "2026-01-01T00:00:00+05:30",
                           cfg.UNIQUENESS_NODE_BUDGET_OFFLINE)
    emit(run_dir, data, truth)
    return run_dir


def _read(run_dir: Path) -> tuple[dict, list[GatewayTxn], list[BankLine], list[Order]]:
    return (json.loads((run_dir / "truth.json").read_text(encoding="utf-8")),
            read_csv(run_dir / "gateway_txns.csv", GatewayTxn),
            read_csv(run_dir / "bank_statement.csv", BankLine),
            read_csv(run_dir / "orders.csv", Order))


def _figures(counts) -> dict:
    return {"counts": dict(counts), "n": sum(counts.values()),
            "precision": precision(counts), "recall": recall(counts)}


def offline(seed: int, run_dir: Path) -> dict:
    """One seed, node budget only. Everything in the returned row is reproducible."""
    truth, txns, bank_lines, orders = _read(run_dir)
    window_days = truth["config"]["window_days"]
    ladder = run_ladder(txns, bank_lines, window_days,
                        tiers=build_tiers(txns, window_days),
                        deadline_ms=None)
    compositions = {bid: claim.composition
                    for bid, (_, claim, _) in ladder.matched.items()}
    report = score(truth, compositions)
    residue, ledger = phase_e(txns, bank_lines, orders, ladder)
    anchors = anchors_recovered(ladder.trace, truth,
                                {t.entity_id: t.settlement_id for t in txns})
    ambiguous = truth["emergent_breaks"]["AMBIGUOUS_SUBSET"]["count"]

    return {
        "seed": seed,
        "run": str(run_dir),
        "bank_lines": len(bank_lines),
        "transactions": len(txns),
        "uniqueness_node_budget": truth["config"]["uniqueness_node_budget"],
        "closed": len(ladder.matched),
        "open": len(bank_lines) - len(ladder.matched),
        # Stage 15's pre-match exclusion (§9.8), and **its cost priced against
        # truth**. An exclusion is monotonically restrictive, so the only way it can
        # be wrong is by withholding a line that had a composition — which is a
        # recall loss and has to be visible rather than argued. `withheld_resolvable`
        # is that number. It is measured here and not in `matcher/`, which cannot
        # reach `truth.json` (I3).
        "excluded": {
            "lines": sorted(ladder.excluded),
            "pairs": len(ladder.excluded) // 2,
            "withheld_resolvable": sorted(
                b for b in ladder.excluded
                if truth["bank_lines"][b]["resolvable"]),
        },
        "all_lines": _figures(all_lines(report)),
        "headline": _figures(report.counts("headline")),
        # §6.2's rate control targets 8%; it is reported, never asserted, and the
        # spread across seeds is the reason this file exists.
        "ambiguity": {"lines": ambiguous, "of": len(bank_lines),
                      "rate": ambiguous / len(bank_lines)},
        "anchors": {k: anchors[k] for k in
                    ("recovered", "true_anchor_present", "wrong", "no_true_anchor")},
        "residue_gap_paise": residue.gap_paise,
        "residue_reconciles": residue.reconciles,
        "by_tier": {t: sum(1 for tier, _, _ in ladder.matched.values() if tier == t)
                    for t in sorted({tier for tier, _, _ in ladder.matched.values()})},
        "buckets": {name: dict(report.counts(name))
                    for name in sorted(set(report.buckets.values()))},
        # The refusals, with the reason that makes each one a refusal rather than a
        # miss. This is what stage 14 reports *instead of* the recall point pair
        # scoring would have bought — the claim is stronger and it is checkable:
        # every sentence names the settlement, the partner credit and how many sets
        # of transactions balance (`core.subsetsum.count_exact`).
        "split_refusals": [
            {"bank_line_id": exc.bank_line_id,
             "settlement_id": exc.settlement_id,
             "amount_paise": exc.amount_at_risk_paise,
             "reason": exc.evidence[0] if exc.evidence else "",
             "blocked_on": exc.blocked_on}
            for exc in ledger.exceptions
            if exc.exception_type == "SPLIT_PAYOUT"],
        # **Named, never counted.** "1 FP on seed 7" is unactionable and reads as a
        # rounding artefact; the line id, the tier that closed it and whether truth
        # calls the line resolvable at all are what turn it into a thing somebody
        # can go and look at. §1: this is the failure class that matters.
        "false_matches": [
            {"bank_line_id": bid,
             "bucket": report.buckets[bid],
             "tier": ladder.matched[bid][0] if bid in ladder.matched else None,
             "confidence": (ladder.matched[bid][2].confidence
                            if bid in ladder.matched else None),
             "delta_paise": (ladder.matched[bid][2].delta_paise
                             if bid in ladder.matched else None),
             "truth_resolvable": truth["bank_lines"][bid]["resolvable"],
             "injected_breaks": truth["bank_lines"][bid]["injected_breaks"]}
            for bid, out in sorted(report.outcomes.items()) if out == "FP"],
        "ledger": {"at_risk_paise": ledger.at_risk_paise,
                   "documentation_paise": ledger.documentation_paise,
                   "by_type": {kind: len(rows)
                               for kind, rows in sorted(ledger.by_type().items())}},
        # Not a clock — a count. Node budget only means this run has no wall clock
        # to report, and §11 forbids folding one in.
        "propagation_passes_run": ladder.passes_run,
    }


def live(seed: int, root: Path = ROOT, *, detective: bool, window_days: int = cfg.SETTLEMENT_WINDOW_DAYS,
         payouts: int = cfg.DEFAULT_PAYOUTS, records: int = cfg.DEFAULT_RECORDS,
         noise: str = "high") -> dict:
    """The same seed in the configuration a judge triggers, timed and nothing else.

    Generation at `UNIQUENESS_NODE_BUDGET_DEMO`, the run deadline armed, Phase D on
    where credentials resolve. **Regenerated every call, deliberately**: the demo
    budget is most of the clock and a cached dataset would report a ceiling nobody
    can hit from the browser.

    **The ladder runs twice and both clocks are reported**, with and without Phase
    D, over the same generated data. One number cannot say *where* a breach of
    §15's ceiling came from, and the two configurations differ by a network round
    trip per batch — which is the one part of the run that is not this machine's to
    control. The ablated clock is what a run with no credentials costs.
    """
    started = time.monotonic()
    data, truth = generate(seed, payouts, records, noise, window_days,
                           "2026-01-01T00:00:00+05:30",
                           cfg.UNIQUENESS_NODE_BUDGET_DEMO)
    run_dir = root / "live" / f"seed{seed}"
    emit(run_dir, data, truth)
    generated = time.monotonic() - started

    ladder = run_ladder(data.txns, data.bank_lines, window_days,
                        tiers=build_tiers(data.txns, window_days,
                                          detective=detective),
                        deadline_ms=MATCH_DEADLINE_MS)
    audit_started = time.monotonic()
    compositions = {bid: claim.composition
                    for bid, (_, claim, _) in ladder.matched.items()}
    phase_e(data.txns, data.bank_lines, data.orders, ladder)
    score(truth, compositions)
    audited = time.monotonic() - audit_started
    phase_d = [t for t in ladder.tiers if getattr(t, "name", "") in ("D1", "D2")]
    # **`calls` is attempts, not answers.** Groq's free tier caps tokens per day, and
    # a 429 is counted as a call and a malformed hypothesis — so a pass that was
    # refused outright reads identically to a pass that ran, at a third of the
    # latency and no cost. Measured the hard way at stage 14: four of ten seeds in
    # the committed live pass were rate-limited, and their 15–21 s totals are the
    # ablated clock plus a few refusals rather than evidence the ceiling holds.
    # So "ran" means **produced a hypothesis**, and the refusal reason is recorded
    # beside it.
    hypotheses = sum(len(t.hypotheses) for t in phase_d)
    unavailable = sorted({r.split(": ", 1)[-1][:120]
                          for t in phase_d for r in t.refusals.values()
                          if "RateLimit" in r or "UNAVAILABLE" in r})

    ablated = ladder
    if hypotheses or unavailable:
        ablated = run_ladder(data.txns, data.bank_lines, window_days,
                             tiers=build_tiers(data.txns, window_days),
                             deadline_ms=MATCH_DEADLINE_MS)

    match_s = ladder.elapsed_ms / 1000
    ablated_s = ablated.elapsed_ms / 1000
    return {
        "seed": seed,
        "generate_s": round(generated, 2),
        "match_s": round(match_s, 2),
        "audit_score_s": round(audited, 2),
        "total_s": round(generated + match_s + audited, 2),
        # The same run with Phase D filtered out of the tier list (§7.2's ablation
        # is a filter, not a special case). Same data, same deadline, same box.
        "match_ablated_s": round(ablated_s, 2),
        "total_ablated_s": round(generated + ablated_s + audited, 2),
        "deadline_ms": ladder.deadline_ms,
        "deadline_hit": ladder.deadline_hit,
        "deadline_hit_ablated": ablated.deadline_hit,
        "closed": len(ladder.matched),
        "closed_ablated": len(ablated.matched),
        "bank_lines": len(data.bank_lines),
        # `detective_ran` is hypotheses, not calls — see above.
        "detective_ran": bool(hypotheses),
        "detective_hypotheses": hypotheses,
        "detective_calls": sum(t.usage.calls for t in phase_d),
        "detective_malformed": sum(t.usage.malformed for t in phase_d),
        "detective_cost_paise": sum(t.usage.cost_paise for t in phase_d),
        "detective_unavailable": unavailable,
    }


# --- aggregation -------------------------------------------------------------


def spread(values: Sequence[float]) -> dict:
    """Mean and **population** σ over the seeds, plus the range.

    Population, not sample: these ten seeds are the whole harness, not a draw from
    a larger population we are inferring about. The range is reported beside it
    because σ alone hides a bimodal spread, and stage 4's five-seed figures ran
    4.5% to 11.9% — the spread was the finding, not the mean.
    """
    values = [v for v in values if v is not None]
    if not values:
        return {"mean": None, "sigma": None, "min": None, "max": None, "n": 0}
    return {"mean": statistics.fmean(values),
            "sigma": statistics.pstdev(values) if len(values) > 1 else 0.0,
            "min": min(values), "max": max(values), "n": len(values)}


def aggregate(rows: Sequence[Mapping], live_rows: Sequence[Mapping] = ()) -> dict:
    """The four figures stage 14 reports, plus the one that must not vary."""
    summary = {
        "all_lines_recall": spread([r["all_lines"]["recall"] for r in rows]),
        "headline_recall": spread([r["headline"]["recall"] for r in rows]),
        "all_lines_precision": spread([r["all_lines"]["precision"] for r in rows]),
        "headline_precision": spread([r["headline"]["precision"] for r in rows]),
        "ambiguity_rate": spread([r["ambiguity"]["rate"] for r in rows]),
        "closed": spread([r["closed"] for r in rows]),
    }
    if live_rows:
        summary["live_total_s"] = spread([r["total_s"] for r in live_rows])
        summary["live_total_ablated_s"] = spread(
            [r.get("total_ablated_s") for r in live_rows])
    # One FP anywhere is worth stopping for: a false match books the wrong figure
    # silently and propagates to GST and revenue (§1). Recorded as a claim with the
    # seeds that back it, so a reader does not have to trust a mean of 100%.
    false_matches = {r["seed"]: r["all_lines"]["counts"].get("FP", 0) for r in rows}
    summary["false_matches"] = {"per_seed": false_matches,
                                "total": sum(false_matches.values()),
                                "clean_on_every_seed":
                                    not any(false_matches.values())}
    # The other side of stage 15's ledger. An exclusion trades recall for
    # correctness by construction, so the trade has to be priced: how many lines
    # were withheld from every tier, and how many of those truth says were
    # matchable. The second number is the cost and it must be reported even when it
    # is zero, because "we checked" and "it did not come up" are different claims.
    withheld = {r["seed"]: len(r["excluded"]["withheld_resolvable"])
                for r in rows if "excluded" in r}
    if withheld:
        summary["excluded"] = {
            "lines_per_seed": {r["seed"]: len(r["excluded"]["lines"])
                               for r in rows if "excluded" in r},
            "withheld_resolvable_per_seed": withheld,
            "withheld_resolvable_total": sum(withheld.values()),
            "costs_no_recall_on_any_seed": not any(withheld.values()),
        }
    return summary


def phase_d_delta(live_rows: Sequence[Mapping]) -> dict:
    """Phase D's contribution, measured from a live pass that actually ran it.

    `closed` against `closed_ablated` over the same data, same deadline, same box —
    §7.2's ablation is a filter over the tier list, so the two runs differ by the
    model and nothing else. Seeds where the model never answered are counted and
    named apart: a 429 is a call, and a pass that was refused contributes no
    evidence either way.
    """
    answered = [r for r in live_rows if r.get("detective_ran")]
    extra = sum(r["closed"] - r.get("closed_ablated", r["closed"])
                for r in answered)
    return {
        "measured_by": "this pass, --detective",
        "live": True,
        "seeds": len(live_rows),
        "seeds_model_answered": len(answered),
        "extra_lines_closed": extra,
        # Lines, not points. The live pass does not record recall at all — the demo
        # budget sizes the buckets differently (§10.1) — so the honest delta here is
        # the count of lines the model closed that the ablated run did not.
        "recall_delta": None,
        "cost_paise": sum(r.get("detective_cost_paise", 0) for r in live_rows),
        "note": ("Measured live. Seeds where the model did not answer are excluded "
                 "from the delta and counted above."),
    }


def run(seeds: Iterable[int] = SEEDS, *, root: Path = ROOT,
        with_live: bool = True, detective: bool = False,
        log=print) -> dict:
    """Every seed, offline then live, into the shape `regression.json` holds."""
    rows, live_rows = [], []
    for seed in seeds:
        run_dir = dataset(seed, root)
        row = offline(seed, run_dir)
        rows.append(row)
        log(f"  seed {seed:<5} offline   closed {row['closed']:>3}/"
            f"{row['bank_lines']}   all-lines recall "
            f"{row['all_lines']['recall']:.1%}   precision "
            f"{row['all_lines']['precision']:.1%}   ambiguity "
            f"{row['ambiguity']['rate']:.1%}")
        if with_live:
            timed = live(seed, root, detective=detective)
            live_rows.append(timed)
            log(f"  seed {seed:<5} live      {timed['total_s']:>5.1f}s total  "
                f"(generate {timed['generate_s']:.1f}s, match "
                f"{timed['match_s']:.1f}s, audit+score "
                f"{timed['audit_score_s']:.2f}s)   detective "
                f"{'ran' if timed['detective_ran'] else 'off'}"
                f"   ablated {timed['total_ablated_s']:.1f}s")
    return {
        "harness": {
            "seeds": list(seeds),
            "scoring_rule": SCORING_RULE,
            "matcher_change": MATCHER_CHANGE,
            "offline": {
                "deadline_ms": None,
                "uniqueness_node_budget": cfg.UNIQUENESS_NODE_BUDGET_OFFLINE,
                "detective": False,
                "note": "node budget only, no wall clock — reproducible (§11, 8.6)",
            },
            "phase_d": phase_d_delta(live_rows) if detective else PHASE_D_MEASURED,
            "live": {
                "deadline_ms": MATCH_DEADLINE_MS,
                "uniqueness_node_budget": cfg.UNIQUENESS_NODE_BUDGET_DEMO,
                "detective": detective,
                "ceiling_s": 60,
                "note": "wall clock only. Its recall is not recorded: the demo "
                        "budget sizes the buckets differently and the two "
                        "denominators do not compare (§10.1). detective=false is "
                        "the shipped demo configuration (use_llm: false) — §15's "
                        "12 s Phase D allocation is not enforceable and Phase D "
                        "closed zero lines on all ten seeds (v1.3.1)",
            },
        },
        "seeds": rows,
        "live": live_rows,
        "summary": aggregate(rows, live_rows),
    }


# --- the table ---------------------------------------------------------------


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:.1%}"


def _pm(figure: Mapping, fmt=_pct) -> str:
    if figure["mean"] is None:
        return "—"
    return f"{fmt(figure['mean'])} ± {fmt(figure['sigma'])}"


def render(data: Mapping, width: int = 96) -> list[str]:
    """The static ruled table. Same figures as `regression.json`, no interpretation.

    Ruled rather than charted (§13): the job is to make the numbers look checkable,
    and a reader comparing ten seeds wants them in a column on the decimal. The
    mean sits under a single rule and the spread under a double one, which is the
    bookkeeping mark for a closed sum.
    """
    rows, live_rows = data["seeds"], {r["seed"]: r for r in data.get("live", ())}
    harness, summary = data["harness"], data["summary"]
    out = [f"MILAAN — offline regression   {len(rows)} seeds · node budget only, "
           "no wall clock",
           "═" * (width - 4),
           f"  uniqueness verified at "
           f"{harness['offline']['uniqueness_node_budget']:,} nodes · deadline off "
           f"· deterministic tiers only",
           f"  scoring: {SCORING_RULE.split('.')[0]}.",
           "",
           f"  {'seed':>6}{'lines':>7}{'closed':>8}{'all-lines':>12}"
           f"{'headline':>11}{'precision':>11}{'ambiguity':>11}{'FP':>5}"
           f"{'live s':>9}{'abl s':>8}",
           "  " + "─" * (width - 4)]
    for row in rows:
        timed = live_rows.get(row["seed"])
        clock = f"{timed['total_s']:.1f}" if timed else "—"
        ablated = (f"{timed['total_ablated_s']:.1f}"
                   if timed and timed.get("total_ablated_s") else "—")
        out.append(
            f"  {row['seed']:>6}{row['bank_lines']:>7}{row['closed']:>8}"
            f"{_pct(row['all_lines']['recall']):>12}"
            f"{_pct(row['headline']['recall']):>11}"
            f"{_pct(row['all_lines']['precision']):>11}"
            f"{_pct(row['ambiguity']['rate']):>11}"
            f"{row['all_lines']['counts'].get('FP', 0):>5}"
            f"{clock:>9}{ablated:>8}")
    # The summary is four labelled rows rather than four more columns. A ± figure
    # does not fit under an 11-character heading, and squeezing it there is how
    # `100.0% ± 0.0%` becomes `100.0%` — which is the one number on this page that
    # must not be quoted without its spread.
    out += ["  " + "─" * (width - 4)]
    first = True
    for label, key in (("all-lines recall", "all_lines_recall"),
                       ("headline recall", "headline_recall"),
                       ("precision", "all_lines_precision"),
                       ("ambiguity rate", "ambiguity_rate")):
        figure = summary[key]
        out.append(f"  {'mean ± σ' if first else '':<11}{label:<20}"
                   f"{_pm(figure):>16}      "
                   f"range {_pct(figure['min'])} – {_pct(figure['max'])}")
        first = False
    out.append("  " + "═" * (width - 4))

    fp = summary["false_matches"]
    out += ["",
            f"  false matches {fp['total']} across {len(rows)} seeds — "
            + ("precision reads 100.0% on every seed"
               if fp["clean_on_every_seed"]
               else "NOT CLEAN: " + ", ".join(f"seed {s}: {n} FP"
                                              for s, n in fp["per_seed"].items() if n))]
    exc = summary.get("excluded")
    if exc:
        lines = sum(exc["lines_per_seed"].values())
        out += [f"  reversal-pair exclusion (§3.2, §9.8) withheld {lines} lines "
                f"across {len(rows)} seeds — "
                + ("no resolvable line among them on any seed, so it cost zero "
                   "recall" if exc["costs_no_recall_on_any_seed"] else
                   "COST RECALL: " + ", ".join(
                       f"seed {s}: {n}" for s, n
                       in exc["withheld_resolvable_per_seed"].items() if n))]
    # Named on the page, not only in the file. A false match is the one result that
    # stops a stage, so it does not get to be a digit in a column.
    for row in rows:
        for match in row.get("false_matches", ()):
            out.append(f"    seed {row['seed']:<5} {match['bank_line_id']:<9}"
                       f"tier {match['tier'] or '—':<4}"
                       f"{match['confidence'] or '—':<10}"
                       f"delta {match['delta_paise']} paise   "
                       f"bucket {match['bucket']}   "
                       f"truth resolvable {match['truth_resolvable']}   "
                       f"{', '.join(match['injected_breaks']) or 'no injected break'}")
    if live_rows:
        ceiling = harness["live"].get("ceiling_s", 60)
        clock = summary["live_total_s"]
        breached = [s for s, r in live_rows.items() if r["total_s"] > ceiling]
        out += [f"  live wall clock {clock['mean']:.1f}s ± {clock['sigma']:.1f}s, "
                f"range {clock['min']:.1f}–{clock['max']:.1f}s against §15's "
                f"{ceiling} s ceiling"
                + (" — inside it on every seed" if not breached else
                   f" — BREACHED on {len(breached)} of {len(live_rows)} seeds: "
                   + ", ".join(f"seed {s} at {live_rows[s]['total_s']:.1f}s"
                               for s in breached))]
        ablated_clock = summary.get("live_total_ablated_s") or {}
        if not harness["live"].get("detective"):
            # Phase D off *is* the shipped configuration from stage 15, so there is
            # no second clock to compare against — printing one would compare the
            # run with itself and then explain the difference.
            out += [f"  {'':<2}Phase D off, so the two clock columns are one run: "
                    f"this is the configuration the board ships (use_llm: false). "
                    f"§15's 12 s Phase D allocation is not enforceable between "
                    f"tiers, and D closed zero extra lines on every seed stage 14 "
                    f"measured; the with-model clock is that table.",
                    f"  {'':<2}the live columns are the demo uniqueness budget "
                    f"({harness['live']['uniqueness_node_budget']:,}) with the "
                    f"deadline armed; their recall is not comparable with the "
                    f"offline columns and is not recorded"]
            return out + _refusals(rows, width)
        if ablated_clock.get("mean") is not None:
            ablated_breached = [s for s, r in live_rows.items()
                                if (r.get("total_ablated_s") or 0) > ceiling]
            out += [f"  ablated (Phase D filtered out of the tier list, same data, "
                    f"same deadline) {ablated_clock['mean']:.1f}s ± "
                    f"{ablated_clock['sigma']:.1f}s, range "
                    f"{ablated_clock['min']:.1f}–{ablated_clock['max']:.1f}s"
                    + (" — inside the ceiling on every seed"
                       if not ablated_breached else
                       f" — BREACHED on {len(ablated_breached)} seeds"),
                    f"  {'':<2}so the overrun is the model's round trips, not the "
                    f"search. It is the one part of the run this machine does not "
                    f"own."]
        out += [f"  {'':<2}the live columns are the demo uniqueness budget "
                f"({harness['live']['uniqueness_node_budget']:,}) with the deadline "
                f"armed; their recall is not comparable with the offline columns "
                f"and is not recorded"]

    return out + _refusals(rows, width)


def _refusals(rows: Sequence[Mapping], width: int) -> list[str]:
    """§13's refusal block. Its own function because `render` has two exits — the
    live pass with Phase D on prints an ablation comparison and the shipped one
    does not, and the refusals belong under both."""
    out: list[str] = []
    refusals = [(row["seed"], r) for row in rows for r in row["split_refusals"]]
    if refusals:
        out += ["", f"REFUSED — SPLIT_PAYOUT, the pair ties out and the division is "
                    f"not recorded   {len(refusals)} halves",
                "  " + "─" * (width - 4)]
        for seed, refusal in refusals:
            out.append(f"  seed {seed:<5} {refusal['bank_line_id']:<9}"
                       f"{refusal['settlement_id'] or '—':<12}"
                       f"{refusal['reason']}")
        out.append("  Each is a refusal rather than a miss, and the census is why: "
                   "the sets that balance are")
        out.append("  counted exactly, not stopped at two. Picking one would be a "
                   "false match by construction.")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="regression", description=__doc__)
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    ap.add_argument("--out", type=Path, default=Path("regression.json"))
    ap.add_argument("--root", type=Path, default=ROOT,
                    help="where offline datasets are cached")
    ap.add_argument("--live", action=argparse.BooleanOptionalAction, default=True,
                    help="also time the live configuration per seed (§15's 60 s "
                         "ceiling). Offline figures never include a clock")
    ap.add_argument("--detective", action="store_true",
                    help="run Phase D in the live timing pass. Offline is always "
                         "deterministic — a model call is not reproducible")
    ap.add_argument("--table", action="store_true",
                    help="render an existing regression.json and run nothing")
    args = ap.parse_args(argv)

    if args.table:
        data = json.loads(args.out.read_text(encoding="utf-8"))
    else:
        data = run(args.seeds, root=args.root, with_live=args.live,
                   detective=args.detective)
        args.out.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
        print()
    print("\n".join(render(data)))
    if not args.table:
        print(f"\n  written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
