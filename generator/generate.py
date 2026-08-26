"""CLI: emit the three CSVs plus truth.json. §6.1 for the truth shape."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from core.models import BANK_COLUMNS, GATEWAY_COLUMNS, ORDER_COLUMNS
from core.money import IST
from generator import config as cfg
from generator.entities import Dataset, build
from generator.uniqueness import classify, mark_duplicate_targets, window_pool


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
                budget: int = cfg.UNIQUENESS_NODE_BUDGET_OFFLINE) -> dict:
    """Run the §6.2 gate over every line the generator intends to mark resolvable."""
    by_id = {t.entity_id: t for t in data.txns}
    records: dict[str, dict] = {}
    for settlement, line in zip(data.settlements, data.bank_lines):
        pool = window_pool(line, data.txns, window_days)
        records[line.bank_line_id] = classify(
            line, by_id, pool, settlement.entity_ids, budget)
    mark_duplicate_targets(data.bank_lines, records)

    return {
        "seed": seed,
        "generated_at": generated_at,
        "config": {"bank_lines": len(data.bank_lines), "records": len(data.txns),
                   "noise": noise, "window_days": window_days},
        "bank_lines": records,
        "settlements": {},          # no NET_ZERO_SETTLEMENT until the stage-4 breaks
        "orders": {t.order_id: {"linked_payment": t.entity_id}
                   for t in data.txns if t.type == "payment" and t.order_id},
        "break_manifest": {},
    }


def emit(out: Path, data: Dataset, truth: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    _write_csv(out / "gateway_txns.csv", GATEWAY_COLUMNS, list(data.txns))
    _write_csv(out / "bank_statement.csv", BANK_COLUMNS, list(data.bank_lines))
    _write_csv(out / "orders.csv", ORDER_COLUMNS, list(data.orders))
    (out / "truth.json").write_text(
        json.dumps(truth, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="generate", description=__doc__)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--bank-lines", type=int, default=cfg.DEFAULT_BANK_LINES)
    ap.add_argument("--records", type=int, default=cfg.DEFAULT_RECORDS)
    ap.add_argument("--noise", choices=sorted(cfg.NOISE_PROFILES), default="high")
    ap.add_argument("--window-days", type=int, default=cfg.SETTLEMENT_WINDOW_DAYS)
    ap.add_argument("--out", type=Path, default=None,
                    help="default data/runs/seed{seed}")
    ap.add_argument("--live", action="store_true",
                    help=f"verify uniqueness at the live node budget "
                         f"({cfg.UNIQUENESS_NODE_BUDGET_LIVE:,}) instead of the "
                         f"offline one ({cfg.UNIQUENESS_NODE_BUDGET_OFFLINE:,}). "
                         "Excludes more lines from scoring; use it to measure that "
                         "cost, not to build a dataset")
    ap.add_argument("--generated-at", default=None,
                    help="pin truth.json's timestamp; the CSVs are already "
                         "byte-reproducible from --seed alone")
    args = ap.parse_args(argv)

    data = build(args.seed, args.bank_lines, args.records, args.noise, args.window_days)
    truth = build_truth(
        data, args.seed, args.noise, args.window_days,
        args.generated_at or datetime.now(IST).replace(microsecond=0).isoformat(),
        cfg.UNIQUENESS_NODE_BUDGET_LIVE if args.live
        else cfg.UNIQUENESS_NODE_BUDGET_OFFLINE,
    )
    out = args.out or Path("data/runs") / f"seed{args.seed}"
    emit(out, data, truth)

    lines = truth["bank_lines"].values()
    resolvable = [r for r in lines if r["resolvable"]]
    print(f"{out}: {len(data.bank_lines)} bank lines, {len(data.txns)} transactions, "
          f"{len(data.orders)} orders")
    print(f"  resolvable {len(resolvable)}  "
          f"verified {sum(r.get('uniqueness') == 'verified' for r in resolvable)}  "
          f"budget_exhausted "
          f"{sum(r.get('uniqueness') == 'budget_exhausted' for r in resolvable)}  "
          f"ambiguous {len(lines) - len(resolvable)} "
          f"({(len(lines) - len(resolvable)) / len(lines):.1%})")
    print(f"  narrations unparseable by regex alone: "
          f"{data.unrecoverable_narrations}/{len(data.bank_lines)} "
          f"({data.unrecoverable_narrations / len(data.bank_lines):.1%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
