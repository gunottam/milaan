"""Scoring against `truth.json`. §11.

The dependency runs one way: this module imports the matcher, the matcher does not
import this one. `truth.json` is reachable from here and from nowhere else (I3).

Set equality, never partial credit (I5). A composition that is right about
twenty-eight transactions and wrong about one is a false match, and a false match
is the severe failure — books wrong, silently.

**Nothing is excluded silently.** §11 removes `excluded_from_scoring` lines from
every denominator, and stage 4 removed that flag from the generator: a line whose
uniqueness the solver could not settle is `resolvable: true, uniqueness: "unproven"`
with its real composition, because the composition is known and only its uniqueness
is not. Three populations still sit outside the headline, and each is reported by
name rather than folded in or dropped — see `BUCKETS`.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from core.models import BankLine, GatewayTxn, Order, read_csv
from core.money import fmt_inr
from generator.config import UNIQUENESS_NODE_BUDGET_OFFLINE
from matcher.run import MATCH_DEADLINE_MS, Run, run_ladder

# Bucket -> what sits in it, and why it is not in the headline.
BUCKETS = {
    "headline": "verified-unique lines, plus refusals on lines nobody rigged",
    "unproven": "uniqueness: unproven — composition known, uniqueness is not",
    "by_construction_c3": "SPLIT_PAYOUT halves — FN until C3 lands in stage 13",
    "by_construction_single": "single-transaction payouts — B2's, no search needed",
    "emergent": "AMBIGUOUS_SUBSET — the true-negative class, G5's only evidence",
    "excluded": "excluded_from_scoring — removed from every denominator (§11)",
}
DISCLOSED = tuple(b for b in BUCKETS if b not in ("headline", "excluded"))


def outcome(record: Mapping, composition: Iterable[str] | None) -> str:
    """TP / FP / FN / TN for one bank line, §11.

    `composition is None` means the agent produced no match — an exception. That
    covers `EXCEEDED_SEARCH_BUDGET` and `UNIQUENESS_UNPROVEN` without a special
    case: both are states in which no composition was approved, and §11 scores
    both as FN. An answer whose uniqueness was never established is not a match.
    """
    if record["resolvable"]:
        if composition is None:
            return "FN"
        return "TP" if set(composition) == set(record["composition"] or ()) else "FP"
    return "FP" if composition is not None else "TN"


def bucket(record: Mapping) -> str:
    """Which population the line is scored in. Every line lands in exactly one."""
    if record.get("excluded_from_scoring"):
        return "excluded"
    if not record["resolvable"]:
        return ("emergent" if "AMBIGUOUS_SUBSET" in record["injected_breaks"]
                else "headline")
    match record.get("uniqueness"):
        case "unproven":
            return "unproven"
        case "by_construction":
            return ("by_construction_c3" if record.get("requires_tier")
                    else "by_construction_single")
        case _:
            return "headline"


@dataclass(frozen=True)
class Report:
    """Per-line verdicts plus the two manifests §11 asks scoring to fill."""

    outcomes: dict[str, str]
    buckets: dict[str, str]
    break_manifest: dict[str, dict]
    emergent_breaks: dict[str, dict]

    def counts(self, *buckets: str) -> Counter:
        wanted = set(buckets) or set(BUCKETS) - {"excluded"}
        return Counter(o for bid, o in self.outcomes.items()
                       if self.buckets[bid] in wanted)

    def lines(self, *buckets: str) -> list[str]:
        return sorted(b for b in self.outcomes if self.buckets[b] in set(buckets))


def precision(c: Counter) -> float | None:
    return c["TP"] / (c["TP"] + c["FP"]) if c["TP"] + c["FP"] else None


def recall(c: Counter) -> float | None:
    return c["TP"] / (c["TP"] + c["FN"]) if c["TP"] + c["FN"] else None


def score(truth: Mapping, matched: Mapping[str, Iterable[str]]) -> Report:
    """Score every bank line in `truth`, and fill both manifests.

    `matched` is `bank_line_id -> composition`; a line absent from it is an
    exception. Scoring needs nothing else — not the tier, not the confidence, not
    the proof. Which proposer produced the answer cannot change whether it is
    right (I9), so it is not an input here either.
    """
    records = truth["bank_lines"]
    buckets = {bid: bucket(rec) for bid, rec in records.items()}
    outcomes = {bid: outcome(rec, matched.get(bid))
                for bid, rec in records.items()}

    def carrying(code: str) -> list[str]:
        return sorted(bid for bid, rec in records.items()
                      if code in rec["injected_breaks"] and buckets[bid] != "excluded")

    # Per-break recall (§11). `injected` counts injections and stays untouched;
    # `lines` counts bank lines carrying the code, and they differ on purpose —
    # SETTLEMENT_CONTAMINATION breaks two lines per injection, NET_ZERO_SETTLEMENT
    # and ORPHAN_ORDER break none at all.
    #
    # Caught splits two ways and the split is not cosmetic. `caught_by_match` is a
    # composition proved to the paisa. `caught_by_refusal` is a line truth calls
    # unresolvable that nothing proposed — which scores identically and can be
    # earned by having no rule at all. `DUPLICATE_CREDIT` is the live case: §3.2's
    # reversal-pair rule is unimplemented, so every one of its lines is a green.
    # A table that reported one number would show six greens for code that does
    # not exist, and stage 14's regression would carry that forward silently.
    manifest = {}
    for code, entry in truth["break_manifest"].items():
        lines = carrying(code)
        by_match = sum(outcomes[bid] == "TP" for bid in lines)
        by_refusal = sum(outcomes[bid] == "TN" for bid in lines)
        manifest[code] = {
            **entry, "lines": len(lines),
            "caught": by_match + by_refusal,
            "missed": len(lines) - by_match - by_refusal,
            "caught_by_match": by_match, "caught_by_refusal": by_refusal,
            # Every green earned by refusing. Correct for WITHHELD_RECORD, where
            # refusal is §5's required outcome; unearned for DUPLICATE_CREDIT,
            # where it is the absence of a rule. Scoring cannot tell those apart —
            # exception typing is stage 10 — so it flags both and names neither.
            "scored_by_refusal": by_match == 0 and by_refusal > 0,
            "no_bank_line": not lines,
        }

    emergent = {}
    for code, entry in truth["emergent_breaks"].items():
        lines = carrying(code)
        hit = sum(bid in matched for bid in lines)
        emergent[code] = {**entry, "matched": hit, "refused": len(lines) - hit}

    return Report(outcomes, buckets, manifest, emergent)


def anchors_recovered(trace: Sequence[Mapping], truth: Mapping,
                      settlement_of: Mapping[str, str | None]) -> dict:
    """§9.1's amendment: report anchors recovered beside lines closed.

    Phase A's product is an anchor, not a composition — a payout is a settlement
    group plus whatever cross-cycle items it nets, so the group's own total is the
    bank credit only when it nets nothing extra. Counting only closures books
    identifier recovery at a fraction of its worth, and stage 12 reads the ablation
    delta against this number.
    """
    found: dict[str, set[str]] = {}
    for step in trace:
        if step["tier"].startswith("A") and step["anchors"]:
            found.setdefault(step["line"], set()).update(step["anchors"])

    present = wrong = unknowable = 0
    for bid, proposed in found.items():
        composition = truth["bank_lines"][bid].get("composition") or ()
        true_ids = Counter(s for s in (settlement_of.get(e) for e in composition) if s)
        if not true_ids:
            unknowable += 1                      # no composition, or all strays
        elif true_ids.most_common(1)[0][0] in proposed:
            present += 1
        else:
            wrong += 1
    return {"recovered": len(found), "true_anchor_present": present,
            "wrong": wrong, "no_true_anchor": unknowable,
            "per_line": {bid: sorted(a) for bid, a in sorted(found.items())}}


# --- CLI ---------------------------------------------------------------------


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:6.1%}"


def _rule(char: str = "─", width: int = 78) -> str:
    return char * width


def budget_banner(truth: Mapping) -> list[str]:
    """The node budget truth was verified at, and a loud line when it is not the
    offline one.

    §10.1: the budget is not a performance knob, it is what decides whether the
    uniqueness guarantee holds. Two truth files at different budgets describe the
    same CSVs — the matcher cannot tell them apart — but call different lines
    `verified`, `unproven` and `AMBIGUOUS_SUBSET`. Comparing a recall figure across
    that boundary compares two different denominators, and the difference looks
    exactly like a regression.
    """
    budget = truth["config"].get("uniqueness_node_budget")
    if budget is None:
        return ["  !! truth records no node budget — written before stage 7.",
                "     Nothing here is comparable with any other run. Regenerate."]
    line = f"  uniqueness verified at {budget:,} nodes"
    if budget == UNIQUENESS_NODE_BUDGET_OFFLINE:
        return [line + "  (the offline budget — comparable)"]
    return [line,
            f"  !! NOT the {UNIQUENESS_NODE_BUDGET_OFFLINE:,} offline budget. The "
            f"unproven and emergent buckets are",
            "     sized by this number, so these counts do not compare with an "
            "offline run."]


def search_summary(trace: Sequence[Mapping]) -> list[str]:
    """What Phase C did, not just what it closed.

    A search tier has three outcomes and only one of them is a match. `refused` is
    G5 withdrawing approval from a tie; `declined` is the tier not searching at all
    — a pool past `C2_MAX_POOL`, where uniqueness is not establishable at any node
    budget, or an exhausted node budget (§10.1). Collapsing those into "did not
    close" would hide the difference between a rule doing its job and a limit being
    hit, which is the distinction §9.3 spends a paragraph on.

    **`proposed on`, not `attempted`.** The trace holds a line only when a tier
    produced a candidate or declined; a tier that searched a line exhaustively and
    found nothing coherent leaves no entry, so the tiers see more lines than this
    counts. Labelling it `attempted` would be a number that reads larger than the
    fact behind it.
    """
    out = []
    for tier in ("C1", "C2"):
        # One entry per line, not one per encounter: the second propagation pass
        # (§9.8) re-offers every open line to every tier, so the raw trace counts
        # the same line twice and a summary built on it reads double. The last
        # entry is that line's final state, which is what the board reports.
        steps = list({s["line"]: s for s in trace if s["tier"] == tier}.values())
        if not steps:
            continue
        declined = sum(1 for s in steps if s.get("unproven"))
        closed = sum(1 for s in steps if s["won"])
        out.append(f"  {tier} proposed on {len(steps) - declined:>3}   "
                   f"closed {closed:>3}   "
                   f"G5 refused {len(steps) - closed - declined:>3}   "
                   f"declined to search {declined:>3}")
    return out


def _pass_two(trace: Sequence[Mapping]) -> str:
    """What the second propagation pass closed that the first did not (§9.8).

    Resolving one line shrinks every other pool, which can turn an ambiguous line
    into a determined one — that is the claim the second pass rests on, and it is
    an empirical one. Printed every run rather than assumed, because a loop that
    closes nothing is a loop to delete, not a loop to keep on faith.
    """
    closed = [s["line"] for s in trace if s["won"] and s.get("pass") == 2]
    return f"{len(closed)} lines" + (f" — {', '.join(sorted(closed))}" if closed
                                     else " (nothing pass 1 had not already)")


def render(report: Report, truth: Mapping, ladder: Run,
           anchors: Mapping, at_risk: Mapping[str, int], run: Path) -> str:
    """The scoreboard. Headline first, then everything held out of it by name.

    Nothing machine-dependent is printed here. §11: a wall clock makes the result a
    property of the box it ran on, so the elapsed time is printed beside the board
    and never inside it — two runs at the same seed and node budget render the same
    bytes. `ladder.banner()` is the exception, and it is the honest one: it says the
    clock cut the run short, which is a fact about the answer rather than about the
    speed.
    """
    cfg = truth["config"]
    matched, trace = ladder.matched, ladder.trace
    tiers = Counter(step["tier"] for step in trace if step["won"])
    out = [f"MILAAN — scoreboard    {run}    seed {truth['seed']}  noise {cfg['noise']}",
           _rule("═"),
           f"  {cfg['bank_lines']} bank lines · {cfg['records']} transactions · "
           f"{len(matched)} closed · {cfg['bank_lines'] - len(matched)} open",
           "  by tier   " + "  ".join(f"{t} {tiers.get(t, 0)}"
                                      for t in ("A1", "A2", "A3", "B1", "B2",
                                                "C1", "C2")),
           *search_summary(trace),
           f"  anchors recovered {anchors['recovered']} "
           f"(true anchor present {anchors['true_anchor_present']}, "
           f"wrong {anchors['wrong']}, no true anchor {anchors['no_true_anchor']}) "
           f"· lines closed {len(matched)}",
           f"  propagation pass 2 closed {_pass_two(trace)}",
           *budget_banner(truth), *ladder.banner(), ""]

    head = report.counts("headline")
    out += [f"HEADLINE — {BUCKETS['headline']}", _rule(),
            f"  TP {head['TP']:>4}      FP {head['FP']:>4}      "
            f"FN {head['FN']:>4}      TN {head['TN']:>4}",
            f"  precision {_pct(precision(head))}        "
            f"recall {_pct(recall(head))}",
            ""]

    out += ["DISCLOSED — held out of the headline, reported by name", _rule()]
    for name in DISCLOSED:
        c = report.counts(name)
        n = sum(c.values())
        out.append(f"  {name:<24} {n:>3} lines   "
                   f"TP {c['TP']:>3}  FP {c['FP']:>3}  FN {c['FN']:>3}  TN {c['TN']:>3}")
        out.append(f"  {'':<24}     {BUCKETS[name]}")
    excluded = report.lines("excluded")
    out += [f"  {'excluded_from_scoring':<24} {len(excluded):>3} lines   "
            f"{'removed from every denominator (§11)' if excluded else 'none'}", ""]

    amb = report.emergent_breaks.get("AMBIGUOUS_SUBSET", {})
    if amb:
        out += [f"  AMBIGUOUS_SUBSET   {amb['count']} lines   "
                f"refused {amb['refused']}   matched {amb['matched']}",
                "    a refusal here is the only evidence G5 works; a match here is "
                "fabricated", ""]

    out += ["PER-BREAK — match is a composition proved; refuse is a line truth calls "
            "unresolvable", _rule(width=92),
            f"  {'code':<26}{'inj':>5}{'lines':>6}{'match':>6}{'refuse':>7}"
            f"{'recall':>9}{'at risk':>16}  note"]
    for code, entry in sorted(report.break_manifest.items()):
        r = entry["caught"] / entry["lines"] if entry["lines"] else None
        risk = sum(at_risk.get(bid, 0) for bid in
                   sorted(bid for bid, rec in truth["bank_lines"].items()
                          if code in rec["injected_breaks"]
                          and report.outcomes[bid] in ("FN", "FP")))
        note = ("no bank line" if entry["no_bank_line"]
                else "refusal-only" if entry["scored_by_refusal"] else "")
        out.append(f"  {code:<26}{entry['injected']:>5}{entry['lines']:>6}"
                   f"{entry['caught_by_match']:>6}{entry['caught_by_refusal']:>7}"
                   f"{_pct(r):>9}{fmt_inr(risk) if risk else '—':>16}  {note}".rstrip())
    out += ["    no bank line   the break creates none, so 0 of 0 is not recall: "
            "NET_ZERO_SETTLEMENT",
            "                   produces no payout (§5.1), ORPHAN_ORDER is the §3.3 "
            "order tie-out.",
            "    refusal-only   every green came from refusing a line truth calls "
            "unresolvable, not",
            "                   from composing one. Required for WITHHELD_RECORD "
            "(§5). Unearned for",
            "                   DUPLICATE_CREDIT: §3.2's reversal-pair rule does not "
            "exist, and its",
            "                   absence scores the same as its success."]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="score", description=__doc__)
    ap.add_argument("--run", type=Path, default=Path("data/runs/seed42"),
                    help="a directory holding the three CSVs and truth.json")
    ap.add_argument("--json", type=Path, default=None,
                    help="also write the scored report here")
    ap.add_argument("--deadline-ms", type=int, default=MATCH_DEADLINE_MS,
                    help="run-level deadline (§9.10). 0 disables it, which is "
                         "§11's reproducible node-budget-only mode")
    args = ap.parse_args(argv)
    args.deadline_ms = args.deadline_ms or None

    truth = json.loads((args.run / "truth.json").read_text(encoding="utf-8"))
    txns = read_csv(args.run / "gateway_txns.csv", GatewayTxn)
    bank_lines = read_csv(args.run / "bank_statement.csv", BankLine)
    read_csv(args.run / "orders.csv", Order)      # §3.3 tie-out is stage 10

    ladder = run_ladder(txns, bank_lines, truth["config"]["window_days"],
                        deadline_ms=args.deadline_ms)
    matched, trace = ladder.matched, ladder.trace
    compositions = {bid: claim.composition for bid, (_, claim, _) in matched.items()}
    report = score(truth, compositions)
    anchors = anchors_recovered(
        trace, truth, {t.entity_id: t.settlement_id for t in txns})
    at_risk = {line.bank_line_id: abs(line.credit_paise - line.debit_paise)
               for line in bank_lines}

    print(render(report, truth, ladder, anchors, at_risk, args.run))
    # Outside the board on purpose (§11): the wall clock is the one number here
    # that belongs to the machine rather than to the method.
    print(f"\n  wall clock {ladder.elapsed_ms / 1000:.1f}s  "
          f"(deadline {'off' if ladder.deadline_ms is None else f'{ladder.deadline_ms:,} ms'}"
          f", §15 allocates 22 s to Phase C)")
    if args.json:
        args.json.write_text(json.dumps({
            "run": str(args.run), "seed": truth["seed"],
            # Carried into the report so a regression table can refuse to compare
            # two runs verified at different budgets (§10.1).
            "uniqueness_node_budget":
                truth["config"].get("uniqueness_node_budget"),
            "closed": len(matched), "bank_lines": len(bank_lines),
            # §9.10. Named, not counted: "12 unattempted" and "12 with no answer"
            # score identically and are not the same fact.
            "exceeded_search_budget": list(ladder.exceeded),
            "passes_run": ladder.passes_run,
            "outcomes": report.outcomes, "buckets": report.buckets,
            "break_manifest": report.break_manifest,
            "emergent_breaks": report.emergent_breaks,
            "anchors": anchors,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
