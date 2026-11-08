#!/usr/bin/env python3
"""Recursively restore originals and remove byte-identical Syncthing conflicts.

Runs as a dry run unless --apply is supplied. Pause Syncthing and other writers
before applying changes. Conflicts are grouped by original name and directory;
any differing content leaves the entire group untouched.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path


CONFLICT_PATTERN = re.compile(
    r"^(.+)\.sync-conflict-[0-9]{8}-[0-9]{6}-[A-Za-z0-9]+(\.[^.]+)?$"
)
CHUNK_SIZE = 1024 * 1024


@dataclass
class CleanupResult:
    restored: int = 0
    removed: int = 0
    unresolved: int = 0
    errors: int = 0


def original_path(path: Path) -> Path | None:
    match = CONFLICT_PATTERN.fullmatch(path.name)
    if match is None:
        return None
    return path.with_name(match[1] + (match[2] or ""))


def require_regular_file(path: Path) -> os.stat_result:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise OSError(f"Not a regular file (symlinks are not followed): {path}")
    return info


def same_contents(first: Path, second: Path) -> bool:
    first_info = require_regular_file(first)
    second_info = require_regular_file(second)
    if first_info.st_size != second_info.st_size:
        return False
    with first.open("rb") as left, second.open("rb") as right:
        while True:
            chunk = left.read(CHUNK_SIZE)
            if chunk != right.read(CHUNK_SIZE):
                return False
            if not chunk:
                return True


def raise_walk_error(error: OSError) -> None:
    raise error


def find_conflicts(roots: list[Path]) -> dict[Path, list[Path]]:
    # Finish discovery before making changes, including validating every root.
    for root in roots:
        if root.is_symlink() or not root.is_dir():
            raise OSError(f"Not a directory, or is a symlink: {root}")
    groups: dict[Path, set[Path]] = {}
    for root in roots:
        for directory, subdirectories, filenames in os.walk(
            root, followlinks=False, onerror=raise_walk_error
        ):
            parent = Path(directory)
            subdirectories[:] = sorted(
                name for name in subdirectories if not (parent / name).is_symlink()
            )
            for name in sorted(filenames):
                path = parent / name
                target = original_path(path)
                if target is not None:
                    groups.setdefault(target, set()).add(path)
    return {
        target: sorted(paths)
        for target, paths in sorted(groups.items())
    }


def clean_conflicts(roots: list[Path], *, apply: bool = False) -> CleanupResult:
    groups = find_conflicts(roots)
    result = CleanupResult()
    for target, conflicts in groups.items():
        try:
            has_original = os.path.lexists(target)
            keeper = target if has_original else conflicts[0]
            for path in [keeper, *conflicts]:
                require_regular_file(path)
            if not all(same_contents(keeper, path) for path in conflicts):
                print(f"UNRESOLVED: differing contents; leaving group untouched: {target}")
                result.unresolved += 1
                continue
            if not has_original:
                if apply:
                    # Unlike rename on POSIX, link never overwrites an existing target.
                    os.link(keeper, target, follow_symlinks=False)
                    if not same_contents(keeper, target):
                        raise OSError(f"Contents changed while restoring: {keeper}")
                    keeper.unlink()
                print(f"{'RESTORE' if apply else 'WOULD RESTORE'}: {keeper} -> {target}")
                result.restored += 1
                conflicts = conflicts[1:]
            for path in conflicts:
                if apply:
                    if not same_contents(target, path):
                        raise OSError(f"Contents changed; refusing to delete: {path}")
                    path.unlink()
                print(f"{'REMOVE' if apply else 'WOULD REMOVE'}: {path}")
                result.removed += 1
        except OSError as error:
            print(f"ERROR: {target}: {error}", file=sys.stderr)
            result.errors += 1
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "folders", nargs="+", type=Path,
        help="One or more directories to scan recursively (overlaps are deduplicated).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Perform restorations and deletions.")
    mode.add_argument("--dry-run", action="store_true", help="Preview only (the default).")
    args = parser.parse_args(argv)
    # Use absolute paths without resolving symlinks, which must remain detectable.
    roots = list(dict.fromkeys(Path(os.path.abspath(path)) for path in args.folders))
    print("APPLY: pause Syncthing and other writers first." if args.apply else "DRY RUN: no files will be changed.")
    try:
        result = clean_conflicts(roots, apply=args.apply)
    except OSError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    qualifier = "" if args.apply else "Would "
    print(
        f"{qualifier}restore {result.restored}, remove {result.removed}; "
        f"unresolved groups: {result.unresolved}; errors: {result.errors}."
    )
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
