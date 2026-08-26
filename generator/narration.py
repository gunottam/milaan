"""Narration templates and degradation. §3.4 of the spec.

A UTR is `N` + bank code + date + sequence, so every settlement from the same bank
on the same day shares a long prefix by construction — that is what the §9.5
prefix cascade has to survive. The templates carry `{utr}` whole rather than the
spec's `N{utr}`, since the leading N lives in the identifier itself.
"""

from __future__ import annotations

import random

TEMPLATES = (
    "NEFT-RAZORPAYSOFTW-HDFC0000060-{utr}-RZPSETTLE",
    "IMPS/{utr}/RAZORPAY SOFTWARE PVT/SETTLEMENT",
    "MMT/IMPS/{utr}/RAZORPAY  SOFT/",
    "UPI/CR/{tail}/RAZORPAYSOF/HDFC/settlement",
    "INSTSETL RZP {utr} FEE INCL",
)
ENTITY_ABBREV = (
    ("RAZORPAY SOFTWARE PVT", "RZP SOFT"),
    ("RAZORPAYSOFTW", "RZPSOFTW"),
    ("RAZORPAY  SOFT", "RZP SOFT"),
    ("RAZORPAYSOF", "RZPSOF"),
)


def make_utr(bank: str, cycle: str, seq: int) -> str:
    """`NHDFC26011500042` — bank code, yymmdd, sequence."""
    yymmdd = cycle[2:4] + cycle[5:7] + cycle[8:10]
    return f"N{bank}{yymmdd}{seq:05d}"


def _transpose(utr: str, rng: random.Random) -> str:
    digits = [i for i, c in enumerate(utr) if c.isdigit()]
    if len(digits) < 2:
        return utr
    i = rng.choice(digits[:-1])
    chars = list(utr)
    chars[i], chars[i + 1] = chars[i + 1], chars[i]
    return "".join(chars)


def render(utr: str, profile: dict[str, float], rng: random.Random) -> tuple[str, bool]:
    """(narration, recoverable). `recoverable` is False when no form of the UTR
    survives — those lines are the ~30% a regex cannot parse at high noise."""
    if rng.random() < profile["blank"]:
        return "", False

    template = rng.choice(TEMPLATES)
    shown, recoverable = utr, True

    if rng.random() < profile["drop"]:
        shown, recoverable = "", False
    elif rng.random() < profile["transpose"]:
        shown, recoverable = _transpose(utr, rng), False
    elif rng.random() < profile["truncate"]:
        shown = utr[: rng.randint(5, 8)]

    text = template.format(utr=shown, tail=shown[1:] if shown else "")
    if rng.random() < profile["abbrev"]:
        for full, short in ENTITY_ABBREV:
            text = text.replace(full, short)
    if rng.random() < profile["collapse"]:
        text = " ".join(text.split())
    if rng.random() < profile["upper"]:
        text = text.upper()
    return text, recoverable
