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


@pytest.fixture(scope="session")
def seed42():
    """`(GeneratedData, truth)`. Session-scoped and shared, so nothing here may be
    mutated — every consumer only reads."""
    return generate(42, 120, 3000, "high", 2, STAMP, NODE_BUDGET)
