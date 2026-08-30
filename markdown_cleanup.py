"""Reusable, conservative Markdown formatting utilities."""

import re


HEADING_PATTERN = re.compile(r"^#{2,3}(?!#)\s+\S")
FENCE_PATTERN = re.compile(r"^\s*(`{3,}|~{3,})")


def normalize_heading_spacing(markdown: str) -> str:
    """Ensure level-two and level-three headings have one surrounding blank line."""
    line_end = "\r\n" if "\r\n" in markdown else "\n"
    lines = markdown.splitlines()
    body_start = _frontmatter_end(lines)
    prefix, body = lines[:body_start], lines[body_start:]
    cleaned: list[str] = []
    in_fence = False
    index = 0

    while index < len(body):
        line = body[index]
        if FENCE_PATTERN.match(line):
            in_fence = not in_fence
        if not in_fence and HEADING_PATTERN.match(line):
            while cleaned and not cleaned[-1].strip():
                cleaned.pop()
            if prefix or cleaned:
                cleaned.append("")
            cleaned.append(line)
            index += 1
            while index < len(body) and not body[index].strip():
                index += 1
            if index < len(body):
                cleaned.append("")
            continue
        cleaned.append(line)
        index += 1

    normalized = line_end.join([*prefix, *cleaned])
    if markdown.endswith(("\n", "\r")):
        normalized += line_end
    return normalized


def _frontmatter_end(lines: list[str]) -> int:
    if not lines or lines[0] != "---":
        return 0
    for index, line in enumerate(lines[1:], 1):
        if line == "---":
            return index + 1
    return 0
