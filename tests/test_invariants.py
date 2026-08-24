"""The invariants, enforced by grep. §0 and §14 of the spec.

Runnable at every stage: a path that does not exist yet skips, it does not error.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def grep(pattern: str, paths: list[str]) -> list[str]:
    """Hits as `path:line: text` across the .py files under each path."""
    rx = re.compile(pattern)
    hits = []
    for p in paths:
        root = ROOT / p
        if not root.exists():
            pytest.skip(f"{p} does not exist yet")
        files = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for f in files:
            if any(part.startswith(".") for part in f.relative_to(ROOT).parts):
                continue
            for n, line in enumerate(f.read_text().splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()}")
    return hits


def test_no_floats_in_core():
    """I1 — all money is int paise. Decimal only, and only in core/fees.py."""
    assert not grep(r"\bfloat\(", ["core/", "matcher/", "generator/"])


def test_only_verify_approves():
    """I2 — one place in the codebase may return a passing verdict."""
    hits = grep(r"Verdict\(ok=True", ["."])
    assert all(h.startswith("matcher/verify.py") for h in hits), hits


def test_detective_cannot_reach_truth():
    """I3 — the model never sees the answer key."""
    assert not grep(r"truth", ["detective/"])


def test_claim_carries_no_source():
    """I9 — no gate may learn which proposer produced a claim."""
    assert not grep(r"source", ["matcher/proposers/base.py"])


def test_no_free_text_in_prompts():
    """I10 — merchant-controlled free text is a prompt-injection surface."""
    assert not grep(r"\.notes|\.description", ["detective/"])
