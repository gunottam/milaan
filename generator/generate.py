"""CLI: emit the three CSVs plus truth.json. §6.1 for the truth shape."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from core.models import (BANK_COLUMNS, GATEWAY_COLUMNS, ORDER_COLUMNS, window_pool)
from core.money import IST
from generator import config as cfg
from generator.breaks import BREAK_COUNTS, inject
from generator.entities import Dataset, build
from generator.uniqueness import classify, mark_duplicate_targets


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _write_csv(path: Path, columns: tuple[str, ...], rows: list) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(columns)
        for row in rows:
            d = asdict(row)
            w.writerow([_cell(d[c]) for c in columns])


def build_truth(data: Dataset, seed: int, noise: str, window_days: int,
                generated_at: str,
                budget: int = cfg.UNIQUENESS_NODE_BUDGET_OFFLINE,
                payouts: int | None = None,
                line_breaks: dict[str, list[str]] | None = None,
                forced: dict[str, dict] | None = None,
                settlement_notes: dict[str, dict] | None = None,
                manifest: dict[str, dict] | None = None) -> dict:
    """Run the §6.2 gate over every line the generator intends to mark resolvable.

    An injected break can already determine the record — a withheld source record
    is unresolvable whatever the solver finds — so `forced` records replace the
    gate's verdict. Everything else is measured, never asserted.
    """
    by_id = {t.entity_id: t for t in data.txns}
    lines = {line.bank_line_id: line for line in data.bank_lines}
    line_breaks = line_breaks or {}
    forced = forced or {}
    records: dict[str, dict] = {}

    for settlement in data.settlements:
        line = lines.get(settlement.bank_line_id)
        if line is None or line.bank_line_id in forced:
            continue
        # C1's candidate space: the window pool plus the settlement's own members.
        # Once the settlement id is known, membership is a fact rather than an
        # inference (§9.3), so a transaction pushed out of the window by
        # TIMING_SHIFT is still reachable — and uniqueness has to hold over
        # everything reachable, not just over what C2 can see.
        pool = window_pool(line, data.txns, window_days)
        seen = {t.entity_id for t in pool}
        pool = pool + [by_id[e] for e in settlement.entity_ids if e not in seen]
        records[line.bank_line_id] = classify(
            line, by_id, pool, settlement.entity_ids, budget)

    records.update(forced)
    for bank_line_id, codes in line_breaks.items():
        if bank_line_id in records:
            existing = records[bank_line_id].get("injected_breaks", [])
            records[bank_line_id]["injected_breaks"] = sorted(set(existing) | set(codes))
    mark_duplicate_targets(data.bank_lines, records)

    strays = sum(1 for t in data.txns if t.settlement_id is None)
    tds_lines = sum(1 for r in records.values()
                    if r.get("composition") and any(by_id[e].tds_paise
                                                    for e in r["composition"]
                                                    if e in by_id))
    ambiguous = sum(1 for r in records.values()
                    if "AMBIGUOUS_SUBSET" in r.get("injected_breaks", []))

    return {
        "seed": seed,
        "generated_at": generated_at,
        # The node budget is part of the run's identity, not a performance note:
        # it decides how many lines truth can call `verified` rather than
        # `unproven`, so two truth files at different budgets describe the same
        # CSVs with different confidence and their bucket sizes do not compare.
        "config": {"payouts": payouts if payouts is not None else len(data.settlements),
                   "bank_lines": len(data.bank_lines), "records": len(data.txns),
                   "noise": noise, "window_days": window_days,
                   "uniqueness_node_budget": budget},
        "bank_lines": records,
        "settlements": settlement_notes or {},
        "orders": {t.order_id: {"linked_payment": t.entity_id}
                   for t in data.txns if t.type == "payment" and t.order_id},
        # The 15 injected breaks, scored per-break in §11. `caught` and `missed`
        # are filled by scoring in stage 7 — the generator cannot know them.
        "break_manifest": manifest or {},
        # Not injected but still scored: this is the true-negative class, and
        # refusals on data nobody rigged are the only evidence G5 works at all.
        "emergent_breaks": {
            "AMBIGUOUS_SUBSET": {"count": ambiguous, "refused": None, "matched": None},
        },
        # Nothing to detect: properties of correct data that a naive matcher gets
        # wrong. Counted so a regression in the generator is visible, never scored.
        "baseline_properties": {
            "TDS_DEDUCTION": tds_lines,
            "CROSS_CYCLE_REFUND": strays,
        },
    }


def emit(out: Path, data: Dataset, truth: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    _write_csv(out / "gateway_txns.csv", GATEWAY_COLUMNS, list(data.txns))
    _write_csv(out / "bank_statement.csv", BANK_COLUMNS, list(data.bank_lines))
    _write_csv(out / "orders.csv", ORDER_COLUMNS, list(data.orders))
    (out / "truth.json").write_text(
        json.dumps(truth, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def generate(seed: int, payouts: int, records: int, noise: str, window_days: int,
             generated_at: str, budget: int, breaks: bool = True) -> tuple[Dataset, dict]:
    """Build, optionally inject, and describe. Used by the CLI and the tests."""
    data = build(seed, payouts, records, noise, window_days)
    extra: dict = {}
    if breaks:
        injected = inject(data, seed, window_days)
        data = injected.data
        extra = {"line_breaks": injected.line_breaks, "forced": injected.forced,
                 "settlement_notes": injected.settlement_notes,
                 "manifest": injected.manifest}
    truth = build_truth(data, seed, noise, window_days, generated_at, budget,
                        payouts=payouts, **extra)
    return data, truth


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="generate", description=__doc__)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--payouts", type=int, default=cfg.DEFAULT_PAYOUTS,
                    help="number of settlement payouts. Injected breaks add bank "
                         "lines (a duplicate posting, a split payout) and net-zero "
                         "removes one, so the statement is longer than this")
    ap.add_argument("--records", type=int, default=cfg.DEFAULT_RECORDS)
    ap.add_argument("--noise", choices=sorted(cfg.NOISE_PROFILES), default="high")
    ap.add_argument("--window-days", type=int, default=cfg.SETTLEMENT_WINDOW_DAYS)
    ap.add_argument("--breaks", action=argparse.BooleanOptionalAction, default=True,
                    help="inject the 15 breaks of §5 (default: yes)")
    ap.add_argument("--live", action="store_true",
                    help=f"verify uniqueness at the live node budget "
                         f"({cfg.UNIQUENESS_NODE_BUDGET_LIVE:,}) instead of the "
                         f"offline one ({cfg.UNIQUENESS_NODE_BUDGET_OFFLINE:,}). "
                         "Excludes more lines from scoring; use it to measure that "
                         "cost, not to build a dataset")
    ap.add_argument("--out", type=Path, default=None,
                    help="default data/runs/seed{seed}")
    ap.add_argument("--generated-at", default=None,
                    help="pin truth.json's timestamp; the CSVs are already "
                         "byte-reproducible from --seed alone")
    args = ap.parse_args(argv)

    data, truth = generate(
        args.seed, args.payouts, args.records, args.noise, args.window_days,
        args.generated_at or datetime.now(IST).replace(microsecond=0).isoformat(),
        cfg.UNIQUENESS_NODE_BUDGET_LIVE if args.live
        else cfg.UNIQUENESS_NODE_BUDGET_OFFLINE,
        breaks=args.breaks,
    )
    out = args.out or Path("data/runs") / f"seed{args.seed}"
    emit(out, data, truth)

    lines = truth["bank_lines"].values()
    resolvable = [r for r in lines if r["resolvable"]]
    props = truth["baseline_properties"]
    print(f"{out}: {len(data.bank_lines)} bank lines, {len(data.txns)} transactions, "
          f"{len(data.orders)} orders")
    print(f"  resolvable {len(resolvable)}  "
          f"verified {sum(r.get('uniqueness') == 'verified' for r in resolvable)}  "
          f"by_construction "
          f"{sum(r.get('uniqueness') == 'by_construction' for r in resolvable)}  "
          f"unproven "
          f"{sum(r.get('uniqueness') == 'unproven' for r in resolvable)}  "
          f"unresolvable {len(lines) - len(resolvable)}")
    ambiguous = truth["emergent_breaks"]["AMBIGUOUS_SUBSET"]["count"]
    print(f"  ambiguous {ambiguous} ({ambiguous / len(lines):.1%})  "
          f"cross-cycle strays {props['CROSS_CYCLE_REFUND']}  "
          f"narrations unparseable {data.unrecoverable_narrations}")
    if truth["break_manifest"]:
        fired = {k: v["injected"] for k, v in sorted(truth["break_manifest"].items())}
        print(f"  breaks injected {sum(fired.values())} across "
              f"{sum(1 for v in fired.values() if v)} of {len(fired)} codes")
        for code, count in fired.items():
            want = BREAK_COUNTS[code]
            mark = "" if count == want else f"   asked {want}"
            print(f"    {code:<26} {count}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
