#!/usr/bin/env python3
"""
extract_linkedin_ids.py

Usage:
    python3 extract_linkedin_ids.py <letter> [base_dir]

Searches sub-folders (directly under base_dir) whose name begins with
<letter> (case-insensitive), looks at "First Last.md" files inside them
(skips dated note files named YYYY-MM-DD.md), pulls the `linkedin_id`
value out of the YAML frontmatter, and prints it. At the end, prints
the slug (filename stem) of every person file that had no linkedin_id.
"""

import re
import sys
from pathlib import Path

DATED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?\n)---\s*\n?", re.DOTALL)
LINKEDIN_ID_RE = re.compile(r"^linkedin_id:\s*(.*)$", re.MULTILINE)

# Matches a `tags:` field in three common YAML shapes:
#   tags: [person, exec]
#   tags: person
#   tags:
#     - person
#     - exec
TAGS_INLINE_RE = re.compile(r"^tags:\s*\[(.*?)\]\s*$", re.MULTILINE)
TAGS_SCALAR_RE = re.compile(r"^tags:\s*(\S.*)$", re.MULTILINE)
TAGS_BLOCK_RE = re.compile(r"^tags:\s*\n((?:[ \t]+-\s*.*\n?)+)", re.MULTILINE)
LIST_ITEM_RE = re.compile(r"^[ \t]+-\s*(.+?)\s*$", re.MULTILINE)


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value.strip()


def extract_frontmatter(text: str) -> str:
    match = FRONTMATTER_RE.match(text)
    return match.group(1) if match else ""


def extract_tags(frontmatter: str) -> list[str]:
    # Block style (dash list on following lines) takes precedence, since
    # `tags:\n  - person` would otherwise be matched (uselessly) by nothing else.
    block_match = TAGS_BLOCK_RE.search(frontmatter)
    if block_match:
        items = LIST_ITEM_RE.findall(block_match.group(1))
        return [_strip_quotes(i) for i in items]

    inline_match = TAGS_INLINE_RE.search(frontmatter)
    if inline_match:
        items = inline_match.group(1).split(",")
        return [_strip_quotes(i) for i in items if _strip_quotes(i)]

    scalar_match = TAGS_SCALAR_RE.search(frontmatter)
    if scalar_match:
        return [_strip_quotes(scalar_match.group(1))]

    return []


def extract_linkedin_id(frontmatter: str) -> str:
    match = LINKEDIN_ID_RE.search(frontmatter)
    if not match:
        return ""
    return _strip_quotes(match.group(1))


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <letter> [base_dir]", file=sys.stderr)
        return 1

    letter = sys.argv[1][:1].lower()
    base_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".")

    if not base_dir.is_dir():
        print(f"Error: base_dir '{base_dir}' is not a directory", file=sys.stderr)
        return 1

    missing = []

    subdirs = sorted(
        d for d in base_dir.iterdir()
        if d.is_dir() and d.name[:1].lower() == letter
    )

    for subdir in subdirs:
        md_files = sorted(subdir.glob("*.md"))
        for file in md_files:
            fname = file.name

            if DATED_RE.match(fname):
                continue

            slug = file.stem

            try:
                text = file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError) as e:
                print(f"Warning: could not read '{file}': {e}", file=sys.stderr)
                continue

            frontmatter = extract_frontmatter(text)
            tags = extract_tags(frontmatter)

            if "person" not in tags:
                continue

            linkedin_id = extract_linkedin_id(frontmatter)

            if linkedin_id:
                print(f"{slug}: {linkedin_id}")
            else:
                missing.append(slug)

    print()
    print("=== Missing linkedin_id ===")
    if missing:
        for slug in missing:
            print(slug)
    else:
        print("(none)")

    return 0


if __name__ == "__main__":
    sys.exit(main())