"""One seed-42 dataset for the whole suite.

Four modules pinned counts against `generate(42, 120, 3000, "high", 2, ...)` at the
2M budget and each paid ~7s to build it again. Generation is deterministic in the
seed, so they were all building the same bytes.

**2M, not the 40M offline budget** the scoreboard runs. The budget decides how many
lines truth calls `verified` rather than `unproven` (§10.1), so bucket sizes here
are smaller than the committed board's — the CSVs are identical and the matcher
cannot tell the two apart. Every fixture that pins a count asserts the budget it
was measured at rather than assuming it.
"""

from __future__ import annotations

import pytest

from generator.generate import generate

STAMP = "2026-08-24T15:30:00+05:30"
NODE_BUDGET = 2_000_000

# Fixtures that build or read the full 134-line seed-42 board. Any test whose
# fixture closure touches one of these is marked `slow` automatically — see
# `pytest_collection_modifyitems`.
#
# **Keyed on the fixture, not on the test.** A decorator per test is a list that
# drifts the moment somebody adds one; the fixture closure is the actual fact about
# what a test costs, and pytest already computes it.
BOARD_FIXTURES = frozenset({
    "seed42",     # generate() at 2M, ~13 s, then whatever ladder the consumer runs
    "board",      # test_audit — the committed CSVs plus an uncapped ladder, ~45 s
    "report",     # test_api  — build_report on the committed CSVs, ~45 s
})


@pytest.fixture(scope="session")
def seed42():
    """`(GeneratedData, truth)`. Session-scoped and shared, so nothing here may be
    mutated — every consumer only reads."""
    return generate(42, 120, 3000, "high", 2, STAMP, NODE_BUDGET)


def pytest_collection_modifyitems(config, items):
    """Mark every test that needs the full seed-42 board `slow`.

    **The cost is the uncapped ladder, not the uniqueness budget.** Measured with
    `--durations=25` at stage 11c: six tests each run `run_ladder(deadline_ms=None)`
    over 134 lines at ~45 s apiece, and one module pays 88 s of setup. That is the
    stage-11 regex widening — A3 now hands C1 up to 123 candidate anchors per line
    (§9.5), and with no clock the search runs every one of them to exhaustion. The
    2M generate in `seed42` is 13 s of the 392, and it has not moved since stage 7.

    So the split is not fast-budget versus slow-budget. It is **"does this test's
    assertion live on the 134-line board"**, because that is what an uncapped ladder
    costs. Everything else — the gates, the solver property test, the fee golden
    cases, the diagnostics, the hand-built ledger and audit cases, and §9.7's
    acceptance criterion on its own small isolated dataset — runs in the default
    sweep.
    """
    for item in items:
        if BOARD_FIXTURES & set(getattr(item, "fixturenames", ())):
            item.add_marker(pytest.mark.slow)
