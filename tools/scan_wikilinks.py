#!/usr/bin/env python3

"""Scan a Markdown vault for wikilinks and report broken targets.

The script writes two files in the vault root:

- a hidden Markdown index with frontmatter and a full file/link inventory
- missing_files.md with one line per broken wikilink
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set
from urllib.parse import quote


DEFAULT_INDEX_NAME = ".wikilink_index.md"
DEFAULT_MISSING_NAME = "missing_files.md"
DEFAULT_SOURCE_EXTENSIONS = ".md,.markdown"
WIKILINK_PATTERN = re.compile(r"(!?)\[\[([^\]\n]+)\]\]")


@dataclass(frozen=True)
class LinkRecord:
    source_path: str
    raw_target: str
    normalized_target: str
    resolved_paths: List[str]
    embedded: bool

    @property
    def is_missing(self) -> bool:
        return not self.resolved_paths


@dataclass(frozen=True)
class VaultScanResult:
    root_path: Path
    files: List[str]
    folders: List[str]
    markdown_files: List[str]
    link_records: List[LinkRecord]

    @property
    def missing_records(self) -> List[LinkRecord]:
        return [record for record in self.link_records if record.is_missing]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan a vault for broken Obsidian wikilinks.")
    parser.add_argument("root", nargs="?", default=".", help="Root folder of the vault to scan")
    parser.add_argument(
        "-o",
        "--output",
        dest="output_dir",
        default="output",
        help="Folder where the generated index and broken-link report should be written",
    )
    parser.add_argument(
        "-x",
        "--max",
        dest="max_files",
        type=int,
        default=None,
        help="Stop after scanning this many files",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Show one-line progress updates while scanning folders and files",
    )
    parser.add_argument(
        "--index-name",
        default=DEFAULT_INDEX_NAME,
        help=f"Hidden index file name to write in the vault root (default: {DEFAULT_INDEX_NAME})",
    )
    parser.add_argument(
        "--missing-name",
        default=DEFAULT_MISSING_NAME,
        help=f"Broken-link report file name to write in the vault root (default: {DEFAULT_MISSING_NAME})",
    )
    parser.add_argument(
        "--source-extensions",
        default=DEFAULT_SOURCE_EXTENSIONS,
        help="Comma-separated list of file extensions to scan for wikilinks",
    )
    parser.add_argument(
        "-i",
        "--include-extensions",
        dest="include_extensions",
        default="",
        help="Only index files with these extensions, e.g. .md,.jpg,.pdf (default: all)",
    )
    return parser.parse_args()


def parse_extensions(extension_text: str) -> Set[str]:
    extensions = set()
    for raw_extension in extension_text.split(","):
        extension = raw_extension.strip().lower()
        if not extension:
            continue
        if not extension.startswith("."):
            extension = "." + extension
        extensions.add(extension)
    return extensions


def normalize_wikilink_target(raw_target: str) -> str:
    target = raw_target.strip()
    if "|" in target:
        target = target.split("|", 1)[0].strip()
    if "#" in target:
        target = target.split("#", 1)[0].strip()
    return target


def is_generated_output(relative_path: str, index_name: str, missing_name: str) -> bool:
    normalized = relative_path.replace("\\", "/").lower()
    return normalized == index_name.lower() or normalized == missing_name.lower()


def is_within_output_dir(file_path: Path, output_path: Path) -> bool:
    try:
        file_path.relative_to(output_path)
        return True
    except ValueError:
        return False


def is_hidden_name(name: str) -> bool:
    return name.startswith(".")


def is_hidden_path(relative_path: str) -> bool:
    return any(part.startswith(".") for part in Path(relative_path).parts)


def is_ignored_file(file_path: Path) -> bool:
    return file_path.suffix.lower() == ".py"


def make_obsidian_link(relative_path: str) -> str:
    path = relative_path.replace("\\", "/")
    display_name = Path(path).name or path
    if "/" in path:
        return f"[[{path}|{display_name}]]"
    return f"[[{path}]]"


def make_jottacloud_search_link(target: str) -> str:
    filename = Path(target).name or target
    safe_filename = quote(filename, safe="")
    return f"https://jottacloud.com/web/search/list/name/{safe_filename}"


MAX_FILENAME_DISPLAY = 60


def shorten_progress_message(message: str) -> str:
    if len(message) <= MAX_FILENAME_DISPLAY:
        return message
    return "..." + message[-(MAX_FILENAME_DISPLAY - 3):]


def write_progress(message: str, previous_width: int) -> int:
    message = shorten_progress_message(message)
    line = f"\r\033[2K{message}"
    padding = max(0, previous_width - len(message))
    if padding:
        line += " " * padding
    sys.stdout.write(line)
    sys.stdout.flush()
    return len(message)


def resolve_wikilink_target(normalized_target: str, exact_lookup: Dict[str, str], stem_lookup: Dict[str, List[str]]) -> List[str]:
    if not normalized_target:
        return []

    candidate_targets = [normalized_target.replace("\\", "/")]
    target_path = Path(candidate_targets[0])

    if not target_path.suffix:
        candidate_targets.extend(
            [
                f"{candidate_targets[0]}.md",
                f"{candidate_targets[0]}.markdown",
            ]
        )

    for candidate_target in candidate_targets:
        match = exact_lookup.get(candidate_target.lower())
        if match:
            return [match]

    stem = target_path.stem.lower() or normalized_target.lower()
    matches = stem_lookup.get(stem, [])
    return list(matches)


def scan_vault(
    root_path: Path,
    source_extensions: Set[str],
    index_name: str,
    missing_name: str,
    output_path: Path | None = None,
    include_extensions: Set[str] | None = None,
    max_files: int | None = None,
    debug: bool = False,
) -> VaultScanResult:
    root_path = root_path.resolve()
    if output_path is None:
        output_path = (root_path / "output").resolve()
    else:
        output_path = output_path.resolve()
    if not root_path.exists():
        raise FileNotFoundError(f"Root folder does not exist: {root_path}")

    files: List[str] = []
    folders: List[str] = []
    markdown_files: List[str] = []
    markdown_sources: List[Path] = []
    exact_lookup: Dict[str, str] = {}
    stem_lookup: Dict[str, List[str]] = {}
    progress_width = 0
    scanned_files = 0
    stop_scanning = False

    for current_root, dirnames, filenames in os.walk(root_path):
        if stop_scanning:
            break

        current_path = Path(current_root)
        current_relative = current_path.relative_to(root_path).as_posix() or "."

        dirnames[:] = [
            dirname
            for dirname in dirnames
            if not is_hidden_name(dirname) and not is_within_output_dir(current_path / dirname, output_path)
        ]

        if current_relative != "." and is_hidden_path(current_relative):
            continue

        if debug:
            progress_width = write_progress(f"Scanning folder: {current_relative}", progress_width)

        for dirname in dirnames:
            folder_path = current_path / dirname
            folder_relative = folder_path.relative_to(root_path).as_posix()
            if is_hidden_path(folder_relative):
                continue
            if is_within_output_dir(folder_path, output_path):
                continue
            folders.append(folder_relative)

        for filename in filenames:
            file_path = current_path / filename
            relative_path = file_path.relative_to(root_path).as_posix()

            if is_hidden_name(filename) or is_hidden_path(relative_path):
                continue

            if is_within_output_dir(file_path, output_path):
                continue

            if is_ignored_file(file_path):
                continue

            if debug:
                progress_width = write_progress(f"({scanned_files + 1}) {file_path.name}", progress_width)

            if is_generated_output(relative_path, index_name, missing_name):
                continue

            if include_extensions and file_path.suffix.lower() not in include_extensions:
                continue

            scanned_files += 1

            files.append(relative_path)
            exact_lookup[relative_path.lower()] = relative_path

            stem_key = file_path.stem.lower()
            stem_lookup.setdefault(stem_key, []).append(relative_path)

            if file_path.suffix.lower() in source_extensions:
                markdown_files.append(relative_path)
                markdown_sources.append(file_path)

            if max_files is not None and scanned_files >= max_files:
                stop_scanning = True
                break

    files.sort()
    folders.sort()
    markdown_files.sort()
    stem_lookup = {key: sorted(values) for key, values in stem_lookup.items()}
    markdown_sources = sorted(markdown_sources)

    link_records: List[LinkRecord] = []
    for source_path in markdown_sources:
        source_relative = source_path.relative_to(root_path).as_posix()
        try:
            source_text = source_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for match in WIKILINK_PATTERN.finditer(source_text):
            embedded = bool(match.group(1))
            raw_target = match.group(2).strip()
            normalized_target = normalize_wikilink_target(raw_target)
            resolved_paths = resolve_wikilink_target(normalized_target, exact_lookup, stem_lookup)
            link_records.append(
                LinkRecord(
                    source_path=source_relative,
                    raw_target=raw_target,
                    normalized_target=normalized_target,
                    resolved_paths=resolved_paths,
                    embedded=embedded,
                )
            )

    if debug:
        sys.stdout.write("\n")
        sys.stdout.flush()

    return VaultScanResult(root_path=root_path, files=files, folders=folders, markdown_files=markdown_files, link_records=link_records)


def build_index_frontmatter(result: VaultScanResult) -> str:
    scan_time = datetime.now().astimezone().isoformat(timespec="seconds")
    metadata = [
        "---",
        f"last_scan_time: {scan_time}",
        f"root: {result.root_path.as_posix()}",
        f"total_folders: {len(result.folders)}",
        f"total_directories: {len(result.folders) + 1}",
        f"total_files: {len(result.files)}",
        f"markdown_files: {len(result.markdown_files)}",
        f"wikilinks_found: {len(result.link_records)}",
        f"broken_wikilinks: {len(result.missing_records)}",
        "---",
        "",
    ]
    return "\n".join(metadata)


def build_index_body(result: VaultScanResult) -> str:
    lines: List[str] = []
    lines.append("# Wikilink index")
    lines.append("")
    lines.append(f"- Root: {result.root_path.as_posix()}")
    lines.append(f"- Total folders: {len(result.folders)}")
    lines.append(f"- Total directories: {len(result.folders) + 1}")
    lines.append(f"- Total files: {len(result.files)}")
    lines.append(f"- Markdown files: {len(result.markdown_files)}")
    lines.append(f"- Wikilinks found: {len(result.link_records)}")
    lines.append(f"- Broken wikilinks: {len(result.missing_records)}")
    lines.append("")
    lines.append("## Files")
    lines.append("")
    for relative_path in result.files:
        lines.append(f"- {make_obsidian_link(relative_path)}")
    lines.append("")
    lines.append("## Link map")
    lines.append("")
    for record in result.link_records:
        source_link = make_obsidian_link(record.source_path)
        if record.resolved_paths:
            resolved_links = ", ".join(make_obsidian_link(path) for path in record.resolved_paths)
        else:
            search_url = make_jottacloud_search_link(record.normalized_target)
            display_name = Path(record.normalized_target).name or record.normalized_target
            resolved_links = f"MISSING [{display_name}]({search_url})"
        prefix = "!" if record.embedded else ""
        lines.append(f"- {source_link} - {prefix}[[{record.raw_target}]] -> {resolved_links}")
    lines.append("")
    return "\n".join(lines)


def build_missing_files_body(result: VaultScanResult) -> str:
    lines: List[str] = []
    lines.append("# Broken wikilinks")
    lines.append("")
    if not result.missing_records:
        lines.append("- No broken wikilinks found.")
        lines.append("")
        return "\n".join(lines)

    for record in result.missing_records:
        source_link = make_obsidian_link(record.source_path)
        search_target = record.normalized_target or record.raw_target
        display_name = Path(search_target).name or search_target
        search_url = make_jottacloud_search_link(search_target)
        lines.append(f"- {source_link} - [{display_name}]({search_url})")
    lines.append("")
    return "\n".join(lines)


def write_output_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def main() -> None:
    args = parse_arguments()
    root_path = Path(args.root)
    source_extensions = parse_extensions(args.source_extensions)
    include_extensions = parse_extensions(args.include_extensions) if args.include_extensions else None
    output_path = Path(args.output_dir)
    if not output_path.is_absolute():
        output_path = (Path.cwd() / output_path).resolve()
    else:
        output_path = output_path.resolve()

    result = scan_vault(
        root_path,
        source_extensions,
        args.index_name,
        args.missing_name,
        output_path=output_path,
        include_extensions=include_extensions,
        max_files=args.max_files,
        debug=args.debug,
    )

    index_path = output_path / args.index_name
    missing_path = output_path / args.missing_name

    output_path.mkdir(parents=True, exist_ok=True)

    if args.debug:
        print(f"Building index ({len(result.files)} files, {len(result.link_records)} links)...")
    write_output_file(index_path, build_index_frontmatter(result) + build_index_body(result))

    if args.debug:
        print(f"Writing {len(result.missing_records)} broken link(s) to {missing_path}...")
    write_output_file(missing_path, build_missing_files_body(result))

    if args.debug:
        print(f"Done. Index: {index_path}")
        print(f"      Missing: {missing_path}")


if __name__ == "__main__":
    main()