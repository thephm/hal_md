import argparse
import os
import re
from datetime import datetime

FRONTMATTER_SEPARATOR = "---"


def split_frontmatter(text):
    if not text.startswith(FRONTMATTER_SEPARATOR):
        return "", text

    # Find the second frontmatter separator
    parts = text.split(FRONTMATTER_SEPARATOR, 2)
    if len(parts) < 3:
        return "", text

    # parts: ["", "\n...frontmatter...\n", "\n...body..."]
    frontmatter = FRONTMATTER_SEPARATOR + parts[1] + FRONTMATTER_SEPARATOR
    body = parts[2]
    return frontmatter, body


def find_first_heading(body):
    match = re.search(r"(?m)^# .+", body)
    if not match:
        return None, -1
    return match.group(0), match.start()


def dedupe_body(body):
    heading_line, heading_pos = find_first_heading(body)
    if not heading_line:
        return body, False

    second_pos = body.find(heading_line, heading_pos + 1)
    if second_pos == -1:
        return body, False

    return body[:second_pos], True


def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)


def write_backup(backup_root, rel_path, content):
    backup_path = os.path.join(backup_root, rel_path)
    ensure_dir(os.path.dirname(backup_path))
    with open(backup_path, "w", encoding="utf-8", errors="replace") as f:
        f.write(content)


def process_file(path, root, apply, backup_root):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        original = f.read()

    frontmatter, body = split_frontmatter(original)
    new_body, changed = dedupe_body(body)

    if not changed:
        return False

    updated = frontmatter + new_body

    if apply:
        if backup_root:
            rel_path = os.path.relpath(path, root)
            write_backup(backup_root, rel_path, original)
        with open(path, "w", encoding="utf-8", errors="replace") as f:
            f.write(updated)

    return True


def iter_markdown_files(root):
    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$", re.IGNORECASE)
    for base, _, files in os.walk(root):
        for name in files:
            if name.lower().endswith(".md") and not date_pattern.match(name):
                yield os.path.join(base, name)


def main():
    parser = argparse.ArgumentParser(description="Remove duplicated body content in Person markdown files.")
    parser.add_argument("--root", required=True, help="Root folder to scan, e.g. /mnt/c/data/notes/People")
    parser.add_argument("--apply", action="store_true", help="Write fixes to disk")
    parser.add_argument("--backup", action="store_true", help="Write backups before applying changes")
    parser.add_argument("--backup-dir", default="backups/dup_body_fix", help="Backup folder path")
    args = parser.parse_args()

    root = args.root
    if not os.path.isdir(root):
        print(f"Root folder not found: {root}")
        return 2

    backup_root = None
    if args.apply and args.backup:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_root = os.path.join(args.backup_dir, timestamp)
        ensure_dir(backup_root)

    changed = 0
    scanned = 0

    for path in iter_markdown_files(root):
        scanned += 1
        if process_file(path, root, args.apply, backup_root):
            changed += 1
            rel = os.path.relpath(path, root)
            print(f"CHANGED: {rel}")

    print(f"Scanned: {scanned}")
    print(f"Changed: {changed}")
    if args.apply and backup_root:
        print(f"Backups: {backup_root}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
