"""Prompt construction. §9.6, and the file I10's grep test is aimed at.

**I10: merchant free text never enters a prompt.** Two columns of the gateway
export are merchant-controlled and both are excluded from every prompt this module
builds. `tests/test_invariants.py` greps this package for their attribute access and
fails on a hit, so the invariant is enforced by the test rather than by care.

Note the honest scope of the threat. Even a successful injection cannot produce a
false match — the model has no path to a passing verdict, and every hypothesis it
emits walks the same four gates a regex hit does (I8). The realistic damage is
wasted budget and degraded hypotheses, which is worth preventing and is not a
security catastrophe. Saying so is more useful than implying the exclusion is the
only thing standing between the books and disaster.

**What each pass may see is a whitelist, not a blacklist.** `_line()` and `_txn()`
below build their dicts field by field. A new column added to the export appears in
no prompt until someone adds it here, which is the correct default direction: the
alternative — dumping a row and deleting the two known-bad keys — makes every future
column an opt-out.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from core.models import BankLine, GatewayTxn, target
from core.money import fmt_inr

# --- Pass A: narration strings only -----------------------------------------

PASS_A_SYSTEM = """\
You recover payment identifiers from degraded bank narrations for an Indian \
payment gateway's settlement reconciliation.

A settlement UTR has the shape N + bank code + yymmdd + sequence, for example \
NHDFC26010100001 — the letter N, then HDFC, then a six-digit date, then a \
five-digit sequence. Narrations reach you damaged in specific ways: the UTR may be \
truncated to its first few characters, have its leading N dropped, have two \
adjacent digits transposed, be collapsed into surrounding whitespace, or be missing \
altogether.

Your job is to read the text and say what identifier it carries. Three rules:

Repair, do not invent. If two digits look transposed, say so and give the repaired \
UTR — that is a reading of the text in front of you. If the narration carries no \
identifier at all, answer nothing_recoverable. A plausible-looking UTR you \
constructed rather than read is worse than an honest blank, because it sends a \
downstream search after a settlement that does not exist.

A bank code alone is not an identifier. Narrations often carry an IFSC code such as \
HDFC0000060, and the NEFT template includes it on every line. It identifies the \
branch, not the payment. So does a bare NHDFC with no digits after it. Neither is a \
UTR.

You are reading text, not solving arithmetic. You are given no amounts and no \
transaction records, because ~30% of these narrations are unparseable by regular \
expressions and that is a pure text problem — candidate records would add nothing to \
it. Say what the string says.\
"""


def pass_a_prompt(lines: Sequence[BankLine]) -> str:
    """One batch of narrations. §9.6: narration strings only, no candidate context.

    `ref_no` and `narration` are bank-authored columns — the bank wrote them, not
    the merchant — so I10 does not exclude them, and they are the only two fields
    here. No amount, no date, no settlement list: Pass A's job is to read a string.
    """
    rows = [f"{line.bank_line_id}\n"
            f"  narration: {line.narration!r}\n"
            f"  ref_no:    {line.ref_no!r}"
            for line in lines]
    return ("Read each narration and report the identifier it carries.\n\n"
            + "\n".join(rows))


# --- Pass B: structured amounts and entity ids only -------------------------

PASS_B_SYSTEM = """\
You propose candidate compositions for bank lines that a deterministic \
reconciliation ladder could not close.

A bank credit is paid out by a settlement: a group of gateway transactions, \
sometimes plus one or two cross-cycle items that were never tagged to the batch. \
Each transaction contributes a signed net — a payment contributes its amount less \
MDR, GST and TDS; a refund, dispute, transfer or debit adjustment contributes minus \
its amount; a credit adjustment contributes plus its amount. A composition is \
correct when those nets sum to the bank line's signed target.

You are proposing, not deciding. Every hypothesis you return is checked by \
deterministic gates that you cannot see and cannot influence: they confirm each \
entity exists and is unclaimed, re-add the nets themselves, and reject any \
composition that is not the shape of a real payout. A hypothesis that does not \
balance is discarded, so there is no advantage in guessing — a wrong composition \
costs the run a search and gains it nothing. Propose the sets you actually think \
sum correctly, and say so when none does.

Four claims are available:

subset_sum — name the candidate_ids you believe compose the line. Use \
window_override_days when you think the payout includes an item that settled \
outside the default window, such as a held release; it is capped at 5.

split_across_cycles — one settlement reached the bank as two lines. Name the \
partner_bank_line_id and the settlement_id.

unresolvable — no composition exists in the records you were given. Name the \
break_type and state in blocked_on which specific input is missing, in one \
sentence. "Could not match" is not an answer; "the gateway export is short a \
payment of about ₹19,980 against this settlement" is.

Prefer unresolvable over a composition you do not believe. The reconciler is \
judged on refusing honestly, and a missed match costs a human a minute while a \
confident wrong one corrupts the books.\
"""


def _line(line: BankLine) -> dict:
    """What a bank line looks like to Pass B: an id, a date, a signed amount.

    Not the narration — Pass A already read it, and a second reading here would be
    the model re-deriving an identifier from text while ostensibly doing arithmetic.
    """
    return {"bank_line_id": line.bank_line_id,
            "value_date": line.value_date,
            "target": fmt_inr(target(line)),
            "target_paise": target(line)}


def _txn(txn: GatewayTxn) -> dict:
    """What a transaction looks like to Pass B.

    **The whitelist that I10 rests on.** Eleven fields, each named. The two
    merchant-controlled columns are not among them and cannot be, because nothing
    here reads a field this function does not list.

    `net` is included pre-computed: the sign convention is the one rule the model
    would most easily get wrong, and handing it the answer removes a class of
    arithmetic error from hypotheses that the gates would only reject later.
    """
    return {"entity_id": txn.entity_id,
            "type": txn.type,
            "method": txn.method,
            "settlement_id": txn.settlement_id,
            "settled_at": txn.settled_at,
            "amount": fmt_inr(txn.amount_paise),
            "fee_paise": txn.fee_paise,
            "tax_paise": txn.tax_paise,
            "tds_paise": txn.tds_paise,
            "net_paise": txn.net,
            "net": fmt_inr(txn.net)}


def pass_b_prompt(lines: Sequence[BankLine],
                  pools: dict[str, Iterable[GatewayTxn]]) -> str:
    """One batch of open lines, each with its unclaimed window pool.

    §9.6: structured amounts and entity ids only. The pool is the transactions the
    orchestrator has left unclaimed for that line — the same set the search tiers
    were handed, so a hypothesis cites from the same universe C1 and C2 searched and
    G1 will not reject it as unknown.
    """
    import json

    blocks = []
    for line in lines:
        pool = [_txn(t) for t in pools.get(line.bank_line_id, ())]
        blocks.append(json.dumps({"bank_line": _line(line),
                                  "unclaimed_pool": pool},
                                 indent=1, sort_keys=True))
    return ("Propose a composition for each bank line below, or say it is "
            "unresolvable and name what is missing.\n\n" + "\n\n".join(blocks))


def round_two_prompt(lines: Sequence[BankLine],
                     pools: dict[str, Iterable[GatewayTxn]],
                     rejected: dict[str, list[str]]) -> str:
    """Pass B's second round. §9.6: `LLM_ROUNDS = 2`.

    The second round is only worth its tokens if it is told something the first did
    not know, so it carries the gate's rejection reason back. That is the one piece
    of verification-layer output the detective ever sees, and it is a *rejection* —
    the layer split holds, because knowing why a claim failed cannot manufacture a
    passing one.
    """
    base = pass_b_prompt(lines, pools)
    notes = [f"{bid}: your previous hypothesis was rejected — {'; '.join(reasons)}"
             for bid, reasons in sorted(rejected.items()) if reasons]
    if not notes:
        return base
    return (base + "\n\nThe gates rejected your earlier hypotheses for these "
            "lines. Do not repeat a composition that was already rejected.\n"
            + "\n".join(f"  {n}" for n in notes))
