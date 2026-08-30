"""Utilities for repairing text encoding artifacts."""

import re


MOJIBAKE_CONTINUATION = r"[\u0080-\u00bf\u20ac\u201a\u0192\u201e\u2026\u2020\u2021\u02c6\u2030\u0160\u2039\u0152\u017d\u2018\u2019\u201c\u201d\u2022\u2013\u2014\u02dc\u2122\u0161\u203a\u0153\u017e\u0178]"
MOJIBAKE_SEQUENCE = re.compile(rf"(?:[\u00c2\u00c3]{MOJIBAKE_CONTINUATION}|\u00e2{MOJIBAKE_CONTINUATION}{{2}})")


def repair_mojibake(value: str) -> str:
    """Repair UTF-8 text that was previously decoded with a single-byte encoding."""
    for _ in range(3):
        repaired = MOJIBAKE_SEQUENCE.sub(_repair_mojibake_sequence, value)
        if repaired == value:
            break
        value = repaired
    return value


def _repair_mojibake_sequence(match: re.Match[str]) -> str:
    try:
        return match.group().encode("cp1252").decode("utf-8")
    except UnicodeError:
        return match.group()
