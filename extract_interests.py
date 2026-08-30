#!/usr/bin/env python3
"""
update_interests.py

Scans all Markdown (.md) files under --source (recursively), reads the
`interests` field from each file's YAML frontmatter, and merges any new
interest slugs into `interests.json` in --config.

Skips:
  - Files whose name matches the dated-interaction pattern YYYY-MM-DD.md
    (e.g. 2024-03-24.md), same convention used elsewhere in hal_md
    (see most_contacted.py / embed_notes.py).
  - Any file located under a folder named "media" anywhere in its path
    (hal_md convention for photo/attachment subfolders).

For any slug found that isn't already in interests.json, a new entry is
added:

    {
        "name": "<slug converted to Title Case, hyphens -> spaces>",
        "slug": "<slug>",
        "alias_slugs": []
    }

e.g. "play-badminton" -> name "Play Badminton"

Existing entries (and their "aliases") are left untouched. The resulting
list is written back sorted alphabetically by "name".

Frontmatter parsing follows the same "---\\n...yaml...\\n---" convention
used by md_frontmatter.py in https://github.com/thephm/hal_md, but is
self-contained here (no dependency on the hal_md package) so this script
can run standalone until it's merged into that repo.

--source is expected to contain one subfolder per person, named with
their slug (the hal_md convention, e.g. "spongebob-squarepants/"), each
holding that person's .md files. Use --max to limit how many of those
person slug folders get scanned, e.g. for a quick test run on a big
vault. .md files sitting directly in --source (not inside a person
folder) are always scanned and don't count against --max.

Usage:
    python update_interests.py --source /path/to/notes --config /path/to/config
    python update_interests.py -s /path/to/notes -c /path/to/config --dry-run -d
    python update_interests.py -s /path/to/notes -c /path/to/config --max 25

Command line options:
    -s, --source   Folder to recursively scan for .md files
    -c, --config   Folder containing (or to contain) interests.json
    -x, --max      Maximum number of person slug folders to scan
    -n, --dry-run  Show what would change without writing the file
    -d, --debug    Print extra info while processing
"""

import argparse
import json
import os
import re
import sys

import yaml

FRONTMATTER_SEPARATOR = "---"
DATED_FILE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$", re.IGNORECASE)
MEDIA_FOLDER_NAME = "media"
INTERESTS_FILENAME = "interests.json"
FIELD_INTERESTS = "interests"
DEFAULT_CONFIG_DIR = os.environ.get(
    "HAL_MD_CONFIG_DIR",
    (r"C:\data\dev-output\config" if os.name == "nt" else "/mnt/c/data/dev-output/config"),
)


def is_dated_file(filename):
    """
    True if the filename matches YYYY-MM-DD.md (a dated interaction file
    that should not be scanned for interests).
    """
    return bool(DATED_FILE_PATTERN.match(filename))


def is_under_media_folder(root_dir, file_path):
    """
    True if any path component between source root and the file is named
    "media" (case-insensitive), e.g. .../people/spongebob/media/note.md
    """
    rel_path = os.path.relpath(file_path, root_dir)
    parts = os.path.normpath(rel_path).split(os.sep)
    # exclude the filename itself, just check the containing folders
    folders = parts[:-1]
    return any(folder.lower() == MEDIA_FOLDER_NAME for folder in folders)


def read_frontmatter(file_path, debug=False):
    """
    Read and parse the YAML frontmatter block at the top of a Markdown
    file. Returns a dict, or None if there's no valid frontmatter.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            first_line = file.readline().strip()
            if first_line != FRONTMATTER_SEPARATOR:
                return None

            raw_lines = []
            for line in file:
                stripped = line.rstrip("\n")
                if stripped.strip() == FRONTMATTER_SEPARATOR:
                    break
                raw_lines.append(stripped)

        yaml_text = "\n".join(raw_lines)
        data = yaml.safe_load(yaml_text)
        return data if isinstance(data, dict) else None
    except Exception as e:
        if debug:
            print(f"  ! failed to parse frontmatter in {file_path}: {e}")
        return None


def extract_interest_slugs(frontmatter):
    """
    Pull interest slugs out of a frontmatter dict. Handles the value
    being a YAML list, a single string, or a comma-separated string.
    """
    if not frontmatter or FIELD_INTERESTS not in frontmatter:
        return []

    value = frontmatter[FIELD_INTERESTS]

    if value is None:
        return []

    if isinstance(value, list):
        slugs = value
    elif isinstance(value, str):
        slugs = [item.strip() for item in value.split(",")]
    else:
        return []

    return [str(slug).strip() for slug in slugs if str(slug).strip()]


def slug_to_name(slug):
    """
    Convert a hyphenated slug into a display name.
    e.g. "play-badminton" -> "Play Badminton"
         "volleyball"      -> "Volleyball"
    """
    return slug.replace("-", " ").replace("_", " ").strip().title()


def new_interest(slug):
    return {
        "name": slug_to_name(slug),
        "slug": slug,
        "aliases": [],
    }


def find_markdown_files_in(start_dir, source_dir, debug=False):
    """
    Walk start_dir recursively, yielding paths to .md files that are not
    dated interaction files and not under a "media" folder. source_dir is
    the overall scan root, used only to compute relative paths.
    """
    for root, dirs, files in os.walk(start_dir):
        # prune media folders so we don't even descend into them
        dirs[:] = [d for d in dirs if d.lower() != MEDIA_FOLDER_NAME]

        for filename in files:
            if not filename.lower().endswith(".md"):
                continue
            if is_dated_file(filename):
                if debug:
                    print(f"  - skipping dated file: {filename}")
                continue

            file_path = os.path.join(root, filename)

            if is_under_media_folder(source_dir, file_path):
                if debug:
                    print(f"  - skipping media file: {file_path}")
                continue

            yield file_path


def find_markdown_files(source_dir, max_people=None, debug=False):
    """
    Yield paths to .md files under source_dir, following the hal_md
    convention that each immediate subfolder of source_dir is a "person"
    named with their slug.

    - .md files directly inside source_dir are always scanned.
    - Person slug folders (immediate subdirectories) are scanned in
      alphabetical order; if max_people is set, only the first
      max_people of them are scanned.
    """
    with os.scandir(source_dir) as entries:
        entries = list(entries)

    # .md files directly under source_dir, not tied to any person folder
    top_level_files = sorted(
        e.path for e in entries if e.is_file() and e.name.lower().endswith(".md")
    )
    for file_path in top_level_files:
        filename = os.path.basename(file_path)
        if is_dated_file(filename):
            if debug:
                print(f"  - skipping dated file: {filename}")
            continue
        yield file_path

    person_folders = sorted(
        (e.path for e in entries if e.is_dir() and e.name.lower() != MEDIA_FOLDER_NAME),
        key=lambda p: os.path.basename(p).lower(),
    )

    if max_people is not None:
        skipped = person_folders[max_people:]
        person_folders = person_folders[:max_people]
        if debug and skipped:
            print(f"  - --max {max_people}: skipping {len(skipped)} person folder(s): "
                  f"{', '.join(os.path.basename(p) for p in skipped)}")

    for folder in person_folders:
        if debug:
            print(f"  - scanning person folder: {os.path.basename(folder)}")
        yield from find_markdown_files_in(folder, source_dir, debug=debug)


def load_interests(config_path, debug=False):
    """
    Load the existing interests.json from config_path. Returns a list of
    interest dicts (empty list if the file doesn't exist yet).
    """
    if not os.path.isfile(config_path):
        if debug:
            print(f"  - no existing {INTERESTS_FILENAME}, starting fresh")
        return []

    with open(config_path, "r", encoding="utf-8") as file:
        try:
            data = json.load(file)
        except json.JSONDecodeError as e:
            print(f"Error: could not parse existing {config_path}: {e}", file=sys.stderr)
            sys.exit(1)

    if not isinstance(data, list):
        print(f"Error: {config_path} does not contain a JSON list", file=sys.stderr)
        sys.exit(1)

    return data


def main():
    parser = argparse.ArgumentParser(
        description="Scan .md files for 'interests' slugs and update interests.json"
    )
    parser.add_argument("-s", "--source", required=True, help="Folder to recursively scan for .md files")
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG_DIR,
                        help=f"Folder containing (or to contain) interests.json (default: {DEFAULT_CONFIG_DIR})")
    parser.add_argument("-x", "--max", type=int, default=None, help="Maximum number of person slug folders to scan")
    parser.add_argument("-n", "--dry-run", action="store_true", help="Show what would change without writing the file")
    parser.add_argument("-d", "--debug", action="store_true", help="Print extra info while processing")
    args = parser.parse_args()

    source_dir = args.source
    config_dir = args.config
    debug = args.debug

    if not os.path.isdir(source_dir):
        print(f"Error: source folder not found: {source_dir}", file=sys.stderr)
        sys.exit(1)

    if not os.path.isdir(config_dir):
        print(f"Error: config folder not found: {config_dir}", file=sys.stderr)
        sys.exit(1)

    config_path = os.path.join(config_dir, INTERESTS_FILENAME)

    interests = load_interests(config_path, debug=debug)
    existing_slugs = {entry.get("slug") for entry in interests if isinstance(entry, dict)}

    found_slugs = set()
    files_scanned = 0

    for file_path in find_markdown_files(source_dir, max_people=args.max, debug=debug):
        files_scanned += 1
        frontmatter = read_frontmatter(file_path, debug=debug)
        slugs = extract_interest_slugs(frontmatter)
        if slugs and debug:
            print(f"  - {file_path}: {slugs}")
        found_slugs.update(slugs)

    new_slugs = sorted(found_slugs - existing_slugs)

    for slug in new_slugs:
        interests.append(new_interest(slug))

    interests.sort(key=lambda entry: entry.get("name", "").lower())

    print(f"Scanned {files_scanned} file(s) under {source_dir}")
    print(f"Found {len(found_slugs)} unique interest slug(s)")
    if new_slugs:
        print(f"Adding {len(new_slugs)} new interest(s):")
        for slug in new_slugs:
            print(f"  + {slug_to_name(slug)} ({slug})")
    else:
        print("No new interests to add.")

    if args.dry_run:
        print(f"\nDry run: {config_path} was not modified.")
        return

    with open(config_path, "w", encoding="utf-8") as file:
        json.dump(interests, file, indent=2, ensure_ascii=False)
        file.write("\n")

    print(f"\nWrote {len(interests)} interest(s) to {config_path}")


if __name__ == "__main__":
    main()