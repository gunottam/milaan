# Stage 1 — money, fees, IST helpers

Written retroactively, for someone who understands `docs/spec.md` and has not read the code.

Spec sections read: **§2** (money, time, formatting) and **§4** (fee, tax, allocation). Nothing
else — a stage that reads the whole 1,068-line spec builds against the wrong half of it.

`pytest tests/test_fees.py`: **17 passed**. The stage's own acceptance test, from
`docs/build-stages.md`: a card payment of ₹12,000 yields `fee=24000, tax=4320, tds=1200,
net=1170480` paise.

---

## Why this stage is first

Every later stage compares money to money. If rounding is inconsistent by one paise, or a fee is
a float somewhere, the failure does not appear here — it appears in stage 8 as a subset that
will not close, and you will look for the bug in the solver. So the primitives come first, and
they come with golden tests written *before* the implementation, because a golden test written
afterwards tends to assert whatever the code already does.

---

## Files

### `core/money.py` — §2

Defines `Paise = int` and the four operations everything else is built from: `round_paise`
(the only rounding function in the codebase), `to_paise`, `fmt_inr` (Indian digit grouping), and
the IST date helpers `ist_date`, `window_key` and `in_window`. It is the one module allowed to
hold a `Decimal` briefly, and only to round it away immediately.

*The decision a reviewer would ask about:* **the IST date helpers live in a module called
`money.py`.** §14's repo layout lists `core/money.py  fees.py  models.py  proof.py` and no
`ist.py`, and §2 of the spec bundles money, time and formatting into a single section — so
adding a fourth file would have been inventing structure the spec does not have. The cost is a
module whose name understates its contents. The alternative cost was a 20-line file.

A second thing worth asking about: `fmt_inr(-450000)` returns `₹-4,500.00`, with the sign
*inside*, after the symbol. §13's mock shows `₹   −4,500.00` in a right-aligned column, which
implies the sign travels with the digits rather than the currency mark. `-₹4,500.00` is the more
common accounting form and would also be defensible.

Three details that matter later:

- **`round_paise` is `ROUND_HALF_UP`, and Python's `round()` is not.** `round(2.5)` gives 2
  (banker's rounding). `round_paise(Decimal("2.5"))` gives 3. There is a test asserting exactly
  this, because a stray `round()` would produce a delta of one paise on roughly half of all
  transactions — small enough to look like the rounding drift of §4.3 and get absorbed by G4.
- **`ist_date` converts, it never truncates.** `ist_date("2026-01-15T18:15:00+00:00")` is
  15-Jan, not 14-Jan. Slicing the first ten characters off an ISO string is the bug §2 warns
  about: it misfiles every transaction within 5½ hours of midnight.
- **`window_key(value_date, txn_date)`** encodes §2's "window key is `value_date`, falling back
  to `txn_date`" so that no caller has to remember the precedence.

### `core/fees.py` — §4.1, §4.2

Holds the rate table (`MDR_BY_METHOD`, `GST_ON_FEE`, `TDS_194O`, `FX_MARKUP`, `INSTANT_FLAT`,
`TCS_GST`) and `expected_fee(txn) -> (fee, tax, tds)`. This is the **only** module in the
codebase permitted to use `Decimal` for rate multiplication, which is what invariant I1 means in
practice and what `tests/test_invariants.py::test_no_floats_in_core` polices.

*The decision a reviewer would ask about:* **`MDR_BY_METHOD[txn.method]` raises `KeyError` on an
unknown method** instead of defaulting to zero. A default would make an unmodelled payment
method silently free, and §17 is explicit that unmodelled fee schedules must "fail loudly —
nothing balances, recall collapses visibly. Never absorbs silently." There is a test asserting
the raise.

The load-bearing line in the file is the order of two statements:

```python
fee = round_paise(txn.amount_paise * rate)
tax = round_paise(fee * GST_ON_FEE)        # GST on the ROUNDED fee
```

GST is computed on the already-rounded fee. Reverse those and the arithmetic still looks
correct, but the sub-paise residue disappears — and `ROUNDING_DRIFT`, one of the eighteen
breaks, becomes unfireable. The golden case that pins this is described below.

### `tests/test_fees.py` — §4.2, §4.3, §2

Seventeen golden cases: the MDR ladder (2% card, 0% UPI and RuPay, 3% intl_card), GST on the
rounded fee, TDS at 0.1%, FX markup folded into `fee_paise`, the §4.3 allocation remainder,
`ROUND_HALF_UP` versus banker's rounding, Indian digit grouping, and the IST helpers. Written
before the implementation, per §16's build order.

*The decision a reviewer would ask about:* **one golden case uses ₹251.25, which is not a
realistic payment.** It exists because the GST-order rule is invisible at ordinary amounts:

```
amount 25,125 paise, card 2%  ->  raw fee 502.5
  round first:  503  ->  18% = 90.54  -> tax 91
  round after:        18% of 502.5 = 90.45 -> tax 90
```

At ₹12,000 both orders give 4,320 and the test proves nothing. I searched for the smallest
amount where the two orders diverge and asserted both branches, so reversing the two lines in
`fees.py` fails a test rather than silently disarming a break. Golden cases chosen for realism
tend to be golden cases that pass either way.

---

## Deviated from the spec

**`allocate()` was put in `core/fees.py`.** §4.3 sits inside spec section 4, so it landed
next to the other §4 functions — but §14's layout names `generator/allocate.py  # §4.3 — the
ROUNDING_DRIFT mechanism`. Wrong file; corrected in stage 3, with the golden test left where it
is (§14 also says `test_fees.py` carries the allocation case).

**Python 3.11, not the 3.12 of the style rules.** The interpreter available is 3.11, so every
module opens with `from __future__ import annotations` to keep `X | None` hints working.
`CLAUDE.md` was updated to record this rather than leaving the mismatch implicit.

**No `pyproject.toml` or virtualenv.** `pytest` went into the system 3.11. Tests are run as
`python3 -m pytest` from the repo root, which is what puts `core/` and `generator/` on the
import path — there is no packaging step.

## Deferred

**`net_contribution` (§3.1) and `target` (§3.2)** — domain model, not money primitives, and §3
was not in this stage's reading list. Both arrived in stage 3 with `core/models.py`.

**A real transaction type.** `expected_fee` needs `method`, `amount_paise` and `international`,
and `core/models.py` did not exist yet, so the tests defined a three-field stand-in class and
`fees.py` typed the parameter with a small `Protocol`. This is the stage's real debt: **a golden
test asserting against a mock is weaker than it looks**, because the mock cannot drift and the
real type can. Stage 3 deleted both the stand-in and the Protocol and re-pointed all 17 cases at
`GatewayTxn`.

**`TCS_GST` is defined and unused.** §4.1 lists it as "marketplace TCS, off by default". Kept as
declared config so the number is visible rather than folded into a comment.

**No global `Decimal` context.** Precision is left at the default 28 significant digits, which
is far more than paise-scale arithmetic needs. Rounding is explicit at every call site instead,
which is easier to audit than a context set once in a module that may not have been imported.
