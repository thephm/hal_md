#!/usr/bin/env python3
"""
extract_skills.py

Walk a folder of hal_md Person markdown files, pull the `skills` field out
of each file's YAML frontmatter, and write a skills.json file that groups
the raw skill strings by a starter slug — ready for you to manually merge
duplicates and clean up key names.

Requires: pyyaml
    pip install pyyaml

Usage:
    python extract_skills.py --folder /path/to/People

Options:
    --folder    Root folder to search recursively for .md files (required)
    --field     Frontmatter field name to read skills from (default: skills)
    --output    Path to write the resulting JSON (default: skills.json)
    --report    Optional CSV path (skill,file) so you can trace which
                person file each raw skill string came from
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import yaml

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?\n)---\s*\n", re.DOTALL)


def extract_frontmatter(text: str) -> dict:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        print(f"  warning: bad YAML frontmatter ({e})", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def normalize_skill_list(value) -> list:
    """The skills field might be a YAML list or a comma-separated string
    depending on how it was typed in Obsidian. Normalize both to a list."""
    if value is None:
        return []
    if isinstance(value, list):
        items = [str(v).strip() for v in value]
    else:
        items = [v.strip() for v in str(value).split(",")]
    return [i for i in items if i]


def slugify(text: str) -> str:
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "skill"


def main():
    parser = argparse.ArgumentParser(
        description="Extract skills from hal_md Person markdown files into skills.json"
    )
    parser.add_argument("--folder", required=True, help="Root folder to search for .md files")
    parser.add_argument("--field", default="skills", help="Frontmatter field name (default: skills)")
    parser.add_argument("--output", default="skills.json", help="Output JSON path (default: skills.json)")
    parser.add_argument("--report", help="Optional CSV path: skill,file for traceability")
    args = parser.parse_args()

    root = Path(args.folder)
    if not root.is_dir():
        sys.exit(f"Not a folder: {root}")

    md_files = sorted(root.rglob("*.md"))
    if not md_files:
        sys.exit(f"No .md files found under {root}")

    groups = {}   # slug -> list of raw skill strings seen for that slug
    rows = []     # for the optional traceability report

    files_scanned = 0
    files_with_skills = 0

    for path in md_files:
        files_scanned += 1
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            print(f"  skip (read error): {path} ({e})", file=sys.stderr)
            continue

        fm = extract_frontmatter(text)
        if not fm:
            continue

        skills = normalize_skill_list(fm.get(args.field))
        if not skills:
            continue

        files_with_skills += 1
        for skill in skills:
            slug = slugify(skill)
            bucket = groups.setdefault(slug, [])
            if skill not in bucket:
                bucket.append(skill)
            rows.append((skill, str(path)))

    # sort keys and values for stable, diffable output
    ordered = {k: sorted(set(v)) for k, v in sorted(groups.items())}

    out_path = Path(args.output)
    out_path.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.report:
        report_path = Path(args.report)
        with report_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["skill", "file"])
            writer.writerows(rows)

    unique_skill_strings = sum(len(v) for v in ordered.values())
    print(f"Scanned {files_scanned} file(s), {files_with_skills} had a '{args.field}' field.")
    print(f"Found {unique_skill_strings} unique skill string(s) across {len(ordered)} starter group(s).")
    print(f"Wrote {out_path}")
    if args.report:
        print(f"Wrote traceability report to {args.report}")


if __name__ == "__main__":
    main()
