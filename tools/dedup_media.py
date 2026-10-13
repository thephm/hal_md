#!/usr/bin/env python3

"""Interactively remove byte-identical media files and update Markdown links.

Usage:
    python tools/dedup_media.py -f VAULT_DIRECTORY

The tool scans every folder named ``media`` below the vault directory, or all
folders with ``--all-folders`` (all file types, excluding dot-prefixed filenames).
It displays filesystem creation and modification dates for each copy. By default,
``.bak`` files are automatically deleted as a cleanup step; use ``--keep-bak`` to
preserve them. Empty (0-byte) files are never grouped as duplicates; instead, if any
are found, the tool offers to delete them all as a cleanup step.
At duplicate prompts, choose a file number to keep, or enter ``d`` to keep none and
delete all copies in the set.
With no arguments, it prompts for the vault directory. Enter ``q`` at
any prompt to quit without making any further changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from urllib.parse import quote


WIKILINK_PATTERN = re.compile(r"(!?\[\[)([^\]\n]+)(\]\])")
MARKDOWN_LINK_PATTERN = re.compile(r"(\]\()([^\s)]+)(?:\s+[^)]*)?(\))")
CHUNK_SIZE = 1024 * 1024
DEFAULT_OUTPUT_DIR = Path(r"C:\data\dev-output") if os.name == "nt" else Path("/mnt/c/data/dev-output")
DEFAULT_INDEX_NAME = "media_dedup_index.json"
INDEX_VERSION = 3
MIME_EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
}


@dataclass(frozen=True)
class MediaFile:
    path: Path
    relative_path: str
    size: int
    mime_type: str
    digest: str
    modified_time_ns: int = 0


@dataclass(frozen=True)
class FolderGroupEntry:
    path: Path
    file_count: int
    total_size: int
    files: tuple[MediaFile, ...]


@dataclass(frozen=True)
class ReferenceUpdate:
    markdown_path: Path
    line_number: int
    old_target: str
    new_target: str


@dataclass
class MarkdownReferenceIndex:
    wikilink_paths: dict[str, set[Path]]
    markdown_link_paths: dict[str, set[Path]]
    media_name_counts: dict[str, int]
    markdown_files: dict[str, "MarkdownReferenceFile"] = field(default_factory=dict)


@dataclass(frozen=True)
class MarkdownReferenceFile:
    modified_time_ns: int
    wikilink_targets: tuple[str, ...]
    markdown_link_targets: tuple[str, ...]


def get_relative_parent(path: Path, vault_root: Path) -> str:
    try:
        return path.parent.relative_to(vault_root).as_posix()
    except ValueError:
        return path.parent.as_posix()


def get_relative_folder_path(folder_path: Path, vault_root: Path) -> str:
    try:
        return folder_path.relative_to(vault_root).as_posix()
    except ValueError:
        return folder_path.as_posix()


class PreferenceRule:
    def matches(
        self, candidate_kept: MediaFile, candidate_removed: MediaFile, vault_root: Path
    ) -> bool:
        raise NotImplementedError

    def matches_folder(
        self, entry_kept: FolderGroupEntry, entry_removed: FolderGroupEntry, vault_root: Path
    ) -> bool:
        raise NotImplementedError

    @property
    def description(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class FolderPreferenceRule(PreferenceRule):
    preferred_folder: str
    dispreferred_folder: str

    def matches(
        self, candidate_kept: MediaFile, candidate_removed: MediaFile, vault_root: Path
    ) -> bool:
        folder_kept = get_relative_parent(candidate_kept.path, vault_root)
        folder_removed = get_relative_parent(candidate_removed.path, vault_root)
        return (
            folder_kept.lower() == self.preferred_folder.lower()
            and folder_removed.lower() == self.dispreferred_folder.lower()
        )

    def matches_folder(
        self, entry_kept: FolderGroupEntry, entry_removed: FolderGroupEntry, vault_root: Path
    ) -> bool:
        folder_kept = get_relative_folder_path(entry_kept.path, vault_root)
        folder_removed = get_relative_folder_path(entry_removed.path, vault_root)
        return (
            folder_kept.lower() == self.preferred_folder.lower()
            and folder_removed.lower() == self.dispreferred_folder.lower()
        )

    @property
    def description(self) -> str:
        return f"prefer folder '{self.preferred_folder}' over '{self.dispreferred_folder}'"


@dataclass(frozen=True)
class TreePreferenceRule(PreferenceRule):
    preferred_prefix: str
    dispreferred_prefix: str

    def matches(
        self, candidate_kept: MediaFile, candidate_removed: MediaFile, vault_root: Path
    ) -> bool:
        rel_kept = candidate_kept.relative_path.replace("\\", "/")
        rel_removed = candidate_removed.relative_path.replace("\\", "/")

        pref = self.preferred_prefix.rstrip("/") + "/"
        dispref = self.dispreferred_prefix.rstrip("/") + "/"

        if not rel_kept.lower().startswith(pref.lower()):
            return False
        if not rel_removed.lower().startswith(dispref.lower()):
            return False

        sub_kept = rel_kept[len(pref):]
        sub_removed = rel_removed[len(dispref):]
        return sub_kept.lower() == sub_removed.lower()

    def matches_folder(
        self, entry_kept: FolderGroupEntry, entry_removed: FolderGroupEntry, vault_root: Path
    ) -> bool:
        rel_kept = get_relative_folder_path(entry_kept.path, vault_root).rstrip("/") + "/"
        rel_removed = get_relative_folder_path(entry_removed.path, vault_root).rstrip("/") + "/"

        pref = self.preferred_prefix.rstrip("/") + "/"
        dispref = self.dispreferred_prefix.rstrip("/") + "/"

        if not rel_kept.lower().startswith(pref.lower()):
            return False
        if not rel_removed.lower().startswith(dispref.lower()):
            return False

        sub_kept = rel_kept[len(pref):]
        sub_removed = rel_removed[len(dispref):]
        return sub_kept.lower() == sub_removed.lower()

    @property
    def description(self) -> str:
        return f"prefer tree '{self.preferred_prefix}/' over '{self.dispreferred_prefix}/'"


@dataclass(frozen=True)
class PreferredPathRule(PreferenceRule):
    preferred_prefix: str

    def matches(
        self, candidate_kept: MediaFile, candidate_removed: MediaFile, vault_root: Path
    ) -> bool:
        rel_kept = candidate_kept.relative_path.replace("\\", "/").lower()
        rel_removed = candidate_removed.relative_path.replace("\\", "/").lower()
        pref = self.preferred_prefix.replace("\\", "/").strip("/").lower()

        kept_matches = (
            rel_kept.startswith(pref + "/")
            or rel_kept == pref
            or f"/{pref}/" in f"/{rel_kept}"
        )
        removed_matches = (
            rel_removed.startswith(pref + "/")
            or rel_removed == pref
            or f"/{pref}/" in f"/{rel_removed}"
        )
        return kept_matches and not removed_matches

    def matches_folder(
        self, entry_kept: FolderGroupEntry, entry_removed: FolderGroupEntry, vault_root: Path
    ) -> bool:
        rel_kept = get_relative_folder_path(entry_kept.path, vault_root).lower()
        rel_removed = get_relative_folder_path(entry_removed.path, vault_root).lower()
        pref = self.preferred_prefix.replace("\\", "/").strip("/").lower()

        kept_matches = (
            rel_kept.startswith(pref + "/")
            or rel_kept == pref
            or f"/{pref}/" in f"/{rel_kept}"
        )
        removed_matches = (
            rel_removed.startswith(pref + "/")
            or rel_removed == pref
            or f"/{pref}/" in f"/{rel_removed}"
        )
        return kept_matches and not removed_matches

    @property
    def description(self) -> str:
        return f"prefer paths containing '{self.preferred_prefix}'"


def find_path_prefix_difference(
    rel_a: str, rel_b: str
) -> tuple[str, str] | None:
    parts_a = Path(rel_a.replace("\\", "/")).parts
    parts_b = Path(rel_b.replace("\\", "/")).parts

    common_count = 0
    while (
        common_count < len(parts_a)
        and common_count < len(parts_b)
        and parts_a[-(common_count + 1)].lower()
        == parts_b[-(common_count + 1)].lower()
    ):
        common_count += 1

    if common_count == 0:
        return None

    prefix_a_parts = parts_a[: len(parts_a) - common_count]
    prefix_b_parts = parts_b[: len(parts_b) - common_count]

    prefix_a = "/".join(prefix_a_parts)
    prefix_b = "/".join(prefix_b_parts)

    if prefix_a.lower() == prefix_b.lower():
        return None

    if common_count > 1:
        if not prefix_b and prefix_a:
            top_common = parts_b[0]
            return f"{prefix_a}/{top_common}", top_common
        if not prefix_a and prefix_b:
            top_common = parts_a[0]
            return top_common, f"{prefix_b}/{top_common}"

    return prefix_a, prefix_b


def resolve_group_with_rules(
    group: list[MediaFile],
    rules: list[PreferenceRule],
    vault_root: Path,
) -> tuple[MediaFile | None, PreferenceRule | None]:
    if len(group) < 2 or not rules:
        return None, None

    defeated: set[int] = set()
    winning_rules: dict[int, PreferenceRule] = {}

    for i in range(len(group)):
        for j in range(len(group)):
            if i == j or j in defeated:
                continue
            for rule in rules:
                if rule.matches(group[i], group[j], vault_root):
                    defeated.add(j)
                    winning_rules[i] = rule
                    break

    survivors = [i for i in range(len(group)) if i not in defeated]
    if len(survivors) == 1:
        winner_idx = survivors[0]
        rule = winning_rules.get(winner_idx)
        if rule is not None:
            return group[winner_idx], rule

    return None, None


def resolve_folder_group_with_rules(
    group: list[FolderGroupEntry],
    rules: list[PreferenceRule],
    vault_root: Path,
) -> tuple[FolderGroupEntry | None, PreferenceRule | None]:
    if len(group) < 2 or not rules:
        return None, None

    defeated: set[int] = set()
    winning_rules: dict[int, PreferenceRule] = {}

    for i in range(len(group)):
        for j in range(len(group)):
            if i == j or j in defeated:
                continue
            for rule in rules:
                if rule.matches_folder(group[i], group[j], vault_root):
                    defeated.add(j)
                    winning_rules[i] = rule
                    break

    survivors = [i for i in range(len(group)) if i not in defeated]
    if len(survivors) == 1:
        winner_idx = survivors[0]
        rule = winning_rules.get(winner_idx)
        if rule is not None:
            return group[winner_idx], rule

    return None, None


def prompt_and_add_preference(
    selected_file: MediaFile,
    group: list[MediaFile],
    vault_root: Path,
    rules: list[PreferenceRule],
    prompt_count: int | None = None,
) -> bool:
    selected_folder = get_relative_parent(selected_file.path, vault_root)
    other_folders: list[str] = []
    tree_rules: list[TreePreferenceRule] = []

    for other_file in group:
        if other_file == selected_file:
            continue
        other_folder = get_relative_parent(other_file.path, vault_root)
        if other_folder and other_folder.lower() != selected_folder.lower():
            if other_folder not in other_folders:
                other_folders.append(other_folder)
            tree_diff = find_path_prefix_difference(
                selected_file.relative_path, other_file.relative_path
            )
            if tree_diff is not None:
                p_kept, p_removed = tree_diff
                tree_rule = TreePreferenceRule(p_kept, p_removed)
                if tree_rule not in tree_rules:
                    tree_rules.append(tree_rule)

    if not other_folders:
        return False

    first_other = other_folders[0]
    folder_rule = FolderPreferenceRule(selected_folder, first_other)

    if prompt_count is not None:
        print(f"\nYou have chosen '{selected_folder}' over '{first_other}' {prompt_count} times in a row.")
        print("Would you like to automatically use this option for remaining files?")
    else:
        print("\nRemember preference for remaining duplicate sets:")

    has_tree_rule = (
        len(tree_rules) > 0
        and tree_rules[0].preferred_prefix.lower() != selected_folder.lower()
    )

    if has_tree_rule:
        best_tree_rule = tree_rules[0]
        print(f"  [1] Always prefer folder '{selected_folder}' over '{first_other}'")
        print(
            f"  [2] Always prefer tree '{best_tree_rule.preferred_prefix}/' over "
            f"'{best_tree_rule.dispreferred_prefix}/' (all subfolders)"
        )
        print("  [n] No, keep asking each time")
        ans = prompt("Choice [1]: ")
        if ans is None:
            return False
        choice_str = ans.strip().lower()
        if choice_str in ("", "1", "y"):
            for other in other_folders:
                r = FolderPreferenceRule(selected_folder, other)
                if r not in rules:
                    rules.append(r)
            print(f"Preference saved: always prefer folder '{selected_folder}' over '{first_other}'.")
            return True
        elif choice_str == "2":
            if best_tree_rule not in rules:
                rules.append(best_tree_rule)
            print(
                f"Preference saved: always prefer tree '{best_tree_rule.preferred_prefix}/' over "
                f"'{best_tree_rule.dispreferred_prefix}/'."
            )
            return True
        else:
            print("Will keep asking for these folders.")
            return False
    else:
        ans = prompt(f"Always prefer folder '{selected_folder}' over '{first_other}'? [y]es, [n]o: ")
        if ans is None:
            return False
        choice_str = ans.strip().lower()
        if choice_str in ("", "y", "yes", "1"):
            for other in other_folders:
                r = FolderPreferenceRule(selected_folder, other)
                if r not in rules:
                    rules.append(r)
            print(f"Preference saved: always prefer folder '{selected_folder}' over '{first_other}'.")
            return True
        else:
            print("Will keep asking for these folders.")
            return False


def prompt(message: str) -> str | None:
    try:
        answer = input(message).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nQuitting.")
        return None
    if answer.lower() == "q":
        print("Quitting.")
        return None
    return answer


def media_file_paths(
    vault_root: Path,
    all_folders: bool = False,
    excluded_paths: set[Path] | None = None,
):
    excluded_paths = excluded_paths or set()
    for path in vault_root.rglob("*"):
        try:
            is_file = path.is_file()
        except OSError:
            continue
        if is_file and not path.name.startswith(".") and (
            all_folders or any(parent.name.lower() == "media" for parent in path.parents)
        ):
            try:
                if path.resolve() not in excluded_paths:
                    yield path
            except OSError:
                continue


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(CHUNK_SIZE):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def detect_mime_type(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            header = handle.read(32)
    except OSError:
        return "application/octet-stream"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp"
    if header.startswith(b"%PDF-"):
        return "application/pdf"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return "video/mp4"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def shorten_progress_path(prefix: str, path: str) -> str:
    available_width = max(10, shutil.get_terminal_size(fallback=(120, 20)).columns - len(prefix))
    if len(path) <= available_width:
        return path
    if available_width <= 3:
        return path[:available_width]
    start_length = (available_width - 3) // 2
    end_length = available_width - 3 - start_length
    return f"{path[:start_length]}...{path[-end_length:]}"


def build_media_index(
    vault_root: Path,
    cached_files: dict[str, MediaFile] | None = None,
    all_folders: bool = False,
    excluded_paths: set[Path] | None = None,
) -> tuple[list[MediaFile], list[list[MediaFile]]]:
    cached_files = cached_files or {}
    by_size: dict[int, list[MediaFile]] = defaultdict(list)
    indexed_count = 0
    print("Indexing media files...", flush=True)
    for indexed_count, path in enumerate(
        media_file_paths(vault_root, all_folders, excluded_paths), start=1
    ):
        try:
            stat_result = path.stat()
        except OSError:
            continue
        relative_path = path.relative_to(vault_root).as_posix()
        cached_file = cached_files.get(relative_path)
        is_unchanged = (
            cached_file is not None
            and cached_file.size == stat_result.st_size
            and cached_file.modified_time_ns == stat_result.st_mtime_ns
        )
        if is_unchanged:
            digest = cached_file.digest
            mime_type = cached_file.mime_type
        else:
            digest = ""
            mime_type = detect_mime_type(path)
        media_file = MediaFile(
            path=path,
            relative_path=relative_path,
            size=stat_result.st_size,
            mime_type=mime_type,
            digest=digest,
            modified_time_ns=stat_result.st_mtime_ns,
        )
        by_size[media_file.size].append(media_file)
        if indexed_count == 1 or indexed_count % 100 == 0:
            prefix = f"Indexed {indexed_count:,} files: "
            print(f"\r\033[2K{prefix}{shorten_progress_path(prefix, relative_path)}", end="", flush=True)
    if indexed_count:
        print()
    print(f"Indexed {indexed_count:,} media file(s).")

    media_files = [media_file for files in by_size.values() for media_file in files]
    hash_files = [
        media_file
        for size, files in by_size.items()
        if size > 0 and len(files) > 1
        for media_file in files
        if not media_file.digest
    ]
    if hash_files:
        print(f"Hashing {len(hash_files):,} new or changed candidate file(s)...", flush=True)
    hashed_count = 0
    missing_paths: set[Path] = set()
    for size, files in by_size.items():
        if size == 0 or len(files) < 2:
            continue
        for media_file in files:
            if media_file.digest:
                continue
            digest = sha256_file(media_file.path)
            if not digest:
                missing_paths.add(media_file.path)
                continue
            media_file_index = media_files.index(media_file)
            hashed_file = MediaFile(
                path=media_file.path,
                relative_path=media_file.relative_path,
                size=media_file.size,
                mime_type=media_file.mime_type,
                digest=digest,
                modified_time_ns=media_file.modified_time_ns,
            )
            files[files.index(media_file)] = hashed_file
            media_files[media_file_index] = hashed_file
            hashed_count += 1
            if hashed_count == 1 or hashed_count % 100 == 0:
                print(f"\r\033[2KHashed {hashed_count:,} of {len(hash_files):,} candidate files", end="", flush=True)

    groups: list[list[MediaFile]] = []
    for size, files in by_size.items():
        if size == 0 or len(files) < 2:
            continue
        by_digest: dict[str, list[MediaFile]] = defaultdict(list)
        for media_file in files:
            if media_file.path in missing_paths:
                continue
            if not media_file.digest:
                continue
            try:
                if not media_file.path.is_file():
                    missing_paths.add(media_file.path)
                    continue
            except OSError:
                missing_paths.add(media_file.path)
                continue
            by_digest[media_file.digest].append(media_file)
        for matching_files in by_digest.values():
            if len(matching_files) < 2:
                continue
            groups.append(sorted(matching_files, key=lambda media_file: media_file.relative_path.lower()))
    if hashed_count:
        print()
    if missing_paths:
        media_files = [m for m in media_files if m.path not in missing_paths]
    return media_files, sorted(groups, key=lambda group: group[0].relative_path.lower())


def find_duplicate_groups(vault_root: Path, all_folders: bool = False) -> list[list[MediaFile]]:
    _, groups = build_media_index(vault_root, all_folders=all_folders)
    return groups


def file_url(path: Path) -> str:
    resolved_path = path.resolve()
    parts = resolved_path.parts
    if os.name != "nt" and len(parts) >= 4 and parts[1].lower() == "mnt" and len(parts[2]) == 1:
        path_text = f"{parts[2].upper()}:/{'/'.join(parts[3:])}"
    else:
        path_text = resolved_path.as_posix()
    if path.suffix.lower() == ".3gp":
        return "file:///" + quote(path_text, safe="/:")
    return "vscode://file/" + quote(path_text, safe="/:")


def terminal_link(path: Path, label: str = "Open in VS Code") -> str:
    url = file_url(path)
    return f"\033]8;;{url}\033\\{label}\033]8;;\033\\"


def read_markdown(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", data, 0, len(data), "Markdown file could not be decoded")


def build_index_data(
    media_files: list[MediaFile],
    groups: list[list[MediaFile]],
    reference_index: MarkdownReferenceIndex | None = None,
) -> dict[str, object]:
    return {
        "version": INDEX_VERSION,
        "duplicate_group_count": len(groups),
        "files": [
            {
                "path": media_file.relative_path,
                "byte_count": media_file.size,
                "modified_time_ns": media_file.modified_time_ns,
                "mime_type": media_file.mime_type,
                "sha256": media_file.digest,
            }
            for media_file in sorted(media_files, key=lambda media_file: media_file.relative_path.lower())
        ],
        "groups": [
            {
                "byte_count": group[0].size,
                "sha256": group[0].digest,
                "files": [
                    {
                        "path": media_file.relative_path,
                        "mime_type": media_file.mime_type,
                        "file_url": file_url(media_file.path),
                    }
                    for media_file in group
                ],
            }
            for group in groups
        ],
        "markdown_references": [
            {
                "path": relative_path,
                "modified_time_ns": cached_file.modified_time_ns,
                "wikilink_targets": list(cached_file.wikilink_targets),
                "markdown_link_targets": list(cached_file.markdown_link_targets),
            }
            for relative_path, cached_file in sorted(
                (reference_index.markdown_files if reference_index else {}).items()
            )
        ],
    }


def write_duplicate_index(
    output_dir: Path,
    media_files: list[MediaFile],
    groups: list[list[MediaFile]],
    reference_index: MarkdownReferenceIndex | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / DEFAULT_INDEX_NAME
    index_path.write_text(
        json.dumps(build_index_data(media_files, groups, reference_index), indent=2) + "\n",
        encoding="utf-8",
    )
    return index_path


def load_media_manifest(
    index_path: Path, vault_root: Path
) -> tuple[dict[str, MediaFile], dict[str, MarkdownReferenceFile]]:
    file_size = index_path.stat().st_size
    read_size = 0
    chunks: list[bytes] = []
    with index_path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            chunks.append(chunk)
            read_size += len(chunk)
            percentage = 100 if not file_size else read_size * 100 // file_size
            print(f"\r\033[2KLoading cached media index: {percentage}%", end="", flush=True)
    print("\r\033[2KParsing cached media index...", flush=True)
    data = json.loads(b"".join(chunks).decode("utf-8"))
    if data.get("version") != INDEX_VERSION:
        raise ValueError("index format is not compatible")

    cached_files: dict[str, MediaFile] = {}
    for file_data in data.get("files", []):
        relative_path = file_data.get("path")
        if not isinstance(relative_path, str):
            continue
        path = (vault_root / relative_path).resolve()
        try:
            path.relative_to(vault_root)
        except ValueError:
            continue
        cached_files[relative_path] = MediaFile(
            path=path,
            relative_path=relative_path,
            size=file_data["byte_count"],
            mime_type=file_data["mime_type"],
            digest=file_data.get("sha256", ""),
            modified_time_ns=file_data["modified_time_ns"],
        )
    cached_markdown_files: dict[str, MarkdownReferenceFile] = {}
    for file_data in data.get("markdown_references", []):
        relative_path = file_data.get("path")
        if not isinstance(relative_path, str):
            continue
        wikilink_targets = file_data.get("wikilink_targets")
        markdown_link_targets = file_data.get("markdown_link_targets")
        if not isinstance(wikilink_targets, list) or not isinstance(markdown_link_targets, list):
            continue
        if not all(isinstance(target, str) for target in wikilink_targets + markdown_link_targets):
            continue
        cached_markdown_files[relative_path] = MarkdownReferenceFile(
            modified_time_ns=file_data["modified_time_ns"],
            wikilink_targets=tuple(wikilink_targets),
            markdown_link_targets=tuple(markdown_link_targets),
        )
    return cached_files, cached_markdown_files


def normalize_wikilink_target(target: str) -> str:
    target = target.strip()
    target = target.split("|", 1)[0].strip()
    return target.split("#", 1)[0].strip().replace("\\", "/")


def relative_target(source_path: Path, target: str, vault_root: Path) -> Path | None:
    if "://" in target or target.startswith("#"):
        return None
    candidate = (source_path.parent / target.replace("/", os.sep)).resolve()
    try:
        return candidate.relative_to(vault_root).as_posix()
    except ValueError:
        return None


def build_markdown_reference_index(
    vault_root: Path,
    media_files: list[MediaFile] | None = None,
    cached_markdown_files: dict[str, MarkdownReferenceFile] | None = None,
) -> MarkdownReferenceIndex:
    cached_markdown_files = cached_markdown_files or {}
    media_name_counts: dict[str, int] = defaultdict(int)
    print("Indexing media filenames for shorthand links...", flush=True)
    if media_files is None:
        media_files = [
            MediaFile(path=media_path, relative_path="", size=0, mime_type="", digest="")
            for media_path in media_file_paths(vault_root)
        ]
    media_count = 0
    for media_count, media_file in enumerate(media_files, start=1):
        media_name_counts[media_file.path.name.lower()] += 1
        if media_count == 1 or media_count % 100 == 0:
            print(f"\r\033[2KIndexed {media_count:,} media filenames", end="", flush=True)
    if media_count:
        print()
    print(f"Indexed {media_count:,} media filename(s).")

    wikilink_paths: dict[str, set[Path]] = defaultdict(set)
    markdown_link_paths: dict[str, set[Path]] = defaultdict(set)
    markdown_files: dict[str, MarkdownReferenceFile] = {}
    markdown_count = 0
    reused_count = 0
    print("Indexing Markdown references...", flush=True)
    for markdown_count, markdown_path in enumerate(vault_root.rglob("*.md"), start=1):
        try:
            stat_result = markdown_path.stat()
        except OSError:
            continue
        relative_path = markdown_path.relative_to(vault_root).as_posix()
        cached_file = cached_markdown_files.get(relative_path)
        if cached_file and cached_file.modified_time_ns == stat_result.st_mtime_ns:
            reference_file = cached_file
            reused_count += 1
        else:
            try:
                text, _ = read_markdown(markdown_path)
            except OSError:
                continue
            reference_file = MarkdownReferenceFile(
                modified_time_ns=stat_result.st_mtime_ns,
                wikilink_targets=tuple(
                    normalize_wikilink_target(match.group(2)) for match in WIKILINK_PATTERN.finditer(text)
                ),
                markdown_link_targets=tuple(
                    target
                    for match in MARKDOWN_LINK_PATTERN.finditer(text)
                    if (target := relative_target(markdown_path, match.group(2), vault_root))
                ),
            )
        markdown_files[relative_path] = reference_file
        for target in reference_file.wikilink_targets:
            wikilink_paths[target].add(markdown_path)
        for target in reference_file.markdown_link_targets:
            markdown_link_paths[target].add(markdown_path)
        if markdown_count == 1 or markdown_count % 1000 == 0:
            print(f"\r\033[2KIndexed {markdown_count:,} Markdown files: {relative_path}", end="", flush=True)
    if markdown_count:
        print()
    print(
        f"Indexed references in {markdown_count - reused_count:,} Markdown file(s); "
        f"reused {reused_count:,} unchanged file(s)."
    )
    return MarkdownReferenceIndex(wikilink_paths, markdown_link_paths, media_name_counts, markdown_files)


def update_markdown_references(
    vault_root: Path,
    removed: MediaFile,
    kept: MediaFile,
    reference_index: MarkdownReferenceIndex,
) -> list[ReferenceUpdate]:
    removed_name_is_unique = reference_index.media_name_counts[removed.path.name.lower()] == 1
    updates: list[ReferenceUpdate] = []

    markdown_paths = set(reference_index.wikilink_paths.get(removed.relative_path, set()))
    if removed_name_is_unique:
        markdown_paths.update(reference_index.wikilink_paths.get(removed.path.name, set()))
    markdown_paths.update(reference_index.markdown_link_paths.get(removed.relative_path, set()))

    for markdown_path in sorted(markdown_paths):
        try:
            text, encoding = read_markdown(markdown_path)
        except OSError:
            continue

        def replace_wikilink(match: re.Match[str]) -> str:
            target = match.group(2)
            normalized = normalize_wikilink_target(target)
            matches_removed = normalized == removed.relative_path
            matches_removed |= removed_name_is_unique and normalized == removed.path.name
            if not matches_removed:
                return match.group(0)
            suffix = target[len(target.split("|", 1)[0].split("#", 1)[0]):]
            replacement = f"{kept.relative_path}{suffix}"
            updates.append(
                ReferenceUpdate(markdown_path, text.count("\n", 0, match.start()) + 1, target, replacement)
            )
            return f"{match.group(1)}{replacement}{match.group(3)}"

        def replace_markdown_link(match: re.Match[str]) -> str:
            target = match.group(2)
            if relative_target(markdown_path, target, vault_root) != removed.relative_path:
                return match.group(0)
            replacement = os.path.relpath(kept.path, markdown_path.parent).replace("\\", "/")
            updates.append(
                ReferenceUpdate(markdown_path, text.count("\n", 0, match.start()) + 1, target, replacement)
            )
            return f"{match.group(1)}{replacement}{match.group(3)}"

        updated = WIKILINK_PATTERN.sub(replace_wikilink, text)
        updated = MARKDOWN_LINK_PATTERN.sub(replace_markdown_link, updated)
        if updated != text:
            markdown_path.write_bytes(updated.encode(encoding))
    return updates


def rename_extensionless_media(media_file: MediaFile, vault_root: Path) -> MediaFile | None:
    extension = MIME_EXTENSIONS.get(media_file.mime_type)
    if media_file.path.suffix or not extension:
        return media_file
    renamed_path = media_file.path.with_name(media_file.path.name + extension)
    if renamed_path.exists():
        print(f"Cannot rename {media_file.relative_path}: {renamed_path.name} already exists.")
        return None
    media_file.path.rename(renamed_path)
    return replace(
        media_file,
        path=renamed_path,
        relative_path=renamed_path.relative_to(vault_root).as_posix(),
        modified_time_ns=renamed_path.stat().st_mtime_ns,
    )


def relocate_media_file(media_file: MediaFile, target: str | Path, vault_root: Path) -> MediaFile:
    target_path = Path(str(target).lstrip("/\\"))
    if target_path.is_absolute():
        raise ValueError("Destination must be relative to the vault root.")
    destination = (vault_root / target_path).resolve()
    try:
        relative_path = destination.relative_to(vault_root).as_posix()
    except ValueError as error:
        raise ValueError("Destination must be inside the vault root.") from error
    if destination.exists():
        raise ValueError(f"Destination already exists: {relative_path}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    media_file.path.rename(destination)
    return replace(
        media_file,
        path=destination,
        relative_path=relative_path,
        modified_time_ns=destination.stat().st_mtime_ns,
    )


def print_reference_updates(updates: list[ReferenceUpdate], vault_root: Path) -> None:
    red = "\033[31m"
    green = "\033[32m"
    reset = "\033[0m"
    for update in updates:
        relative_path = update.markdown_path.relative_to(vault_root).as_posix()
        print(
            f"  {terminal_link(update.markdown_path, relative_path)}:{update.line_number}"
        )
        print(f"    {red}- {update.old_target}{reset}")
        print(f"    {green}+ {update.new_target}{reset}")


def format_file_dates(path_or_stat: Path | os.stat_result) -> str:
    if isinstance(path_or_stat, Path):
        try:
            stat_result = path_or_stat.stat()
        except OSError:
            return "File or folder no longer exists"
    else:
        stat_result = path_or_stat
    created_time = getattr(stat_result, "st_birthtime", None)
    if created_time is None and os.name == "nt":
        created_time = stat_result.st_ctime
    created = (
        datetime.fromtimestamp(created_time).astimezone().isoformat(sep=" ", timespec="seconds")
        if created_time is not None
        else "unavailable"
    )
    modified = datetime.fromtimestamp(stat_result.st_mtime).astimezone().isoformat(
        sep=" ", timespec="seconds"
    )
    return f"Created: {created}; Last modified: {modified}"


def handle_bak_files(
    bak_files: list[MediaFile],
    keep_bak: bool = False,
) -> list[MediaFile]:
    if not bak_files or keep_bak:
        return []
    print(f"\nFound {len(bak_files):,} .bak file(s). Deleting .bak files (use --keep-bak to preserve them)...")
    deleted: list[MediaFile] = []
    for bak_file in bak_files:
        try:
            bak_file.path.unlink()
            deleted.append(bak_file)
        except OSError as error:
            if not bak_file.path.exists():
                deleted.append(bak_file)
            else:
                print(f"Failed to delete {bak_file.relative_path}: {error}")
    print(f"Deleted {len(deleted):,} .bak file(s).")
    return deleted


def handle_empty_files(empty_files: list[MediaFile]) -> list[MediaFile] | None:
    if not empty_files:
        return []
    print(f"\nFound {len(empty_files):,} empty (0-byte) file(s).")
    while True:
        choice = prompt("Delete all empty files? [y]es, [n]o, [q]uit: ")
        if choice is None:
            return None
        if choice.lower() in ("n", "s"):
            return []
        if choice.lower() == "y":
            deleted: list[MediaFile] = []
            for empty_file in empty_files:
                try:
                    empty_file.path.unlink()
                    deleted.append(empty_file)
                except OSError as error:
                    if not empty_file.path.exists():
                        deleted.append(empty_file)
                    else:
                        print(f"Failed to delete {empty_file.relative_path}: {error}")
            print(f"Deleted {len(deleted):,} empty file(s).")
            return deleted
        print("Choose y, n, or q.")


def folder_is_fully_indexed(
    folder_path: Path,
    indexed_files: tuple[MediaFile, ...] | list[MediaFile],
    excluded_names: set[str] | None = None,
) -> bool:
    excluded_names = excluded_names or {DEFAULT_INDEX_NAME}
    try:
        indexed_set = {f.path.resolve() for f in indexed_files}
    except OSError:
        return False
    try:
        children = list(folder_path.rglob("*"))
    except OSError:
        return False
    for file_path in children:
        try:
            if not file_path.is_file():
                continue
            if file_path.name.startswith(".") or file_path.name in excluded_names:
                continue
            if file_path.resolve() not in indexed_set:
                return False
        except OSError:
            continue
    return True


def find_duplicate_folder_groups(
    vault_root: Path, media_files: list[MediaFile]
) -> list[list[FolderGroupEntry]]:
    folder_files: dict[Path, list[MediaFile]] = defaultdict(list)
    for media_file in media_files:
        curr = media_file.path.parent
        while curr != vault_root and curr != curr.parent:
            try:
                curr.relative_to(vault_root)
            except ValueError:
                break
            folder_files[curr].append(media_file)
            curr = curr.parent

    by_signature: dict[tuple, list[FolderGroupEntry]] = defaultdict(list)
    for folder_path, files in folder_files.items():
        if not files:
            continue
        total_size = sum(f.size for f in files)
        if total_size == 0:
            continue
        signature_items = []
        valid_folder = True
        for f in files:
            if not f.digest and f.size > 0:
                digest = sha256_file(f.path)
                if not digest:
                    valid_folder = False
                    break
            else:
                try:
                    if not f.path.is_file():
                        valid_folder = False
                        break
                except OSError:
                    valid_folder = False
                    break
                digest = f.digest
            signature_items.append((
                f.path.relative_to(folder_path).as_posix(),
                f.size,
                digest,
            ))
        if not valid_folder:
            continue
        signature = tuple(sorted(signature_items))
        entry = FolderGroupEntry(
            path=folder_path,
            file_count=len(files),
            total_size=total_size,
            files=tuple(sorted(files, key=lambda f: f.relative_path.lower())),
        )
        by_signature[signature].append(entry)

    groups: list[list[FolderGroupEntry]] = []
    for signature, entries in by_signature.items():
        if len(entries) < 2:
            continue
        valid_entries = [
            entry for entry in entries if folder_is_fully_indexed(entry.path, entry.files)
        ]
        if len(valid_entries) >= 2:
            groups.append(
                sorted(valid_entries, key=lambda e: e.path.relative_to(vault_root).as_posix().lower())
            )

    def group_sort_key(group: list[FolderGroupEntry]):
        min_depth = min(len(e.path.relative_to(vault_root).parts) for e in group)
        max_size = max(e.total_size for e in group)
        first_path = group[0].path.relative_to(vault_root).as_posix().lower()
        return (min_depth, -max_size, first_path)

    return sorted(groups, key=group_sort_key)


def describe_folder_group(group: list[FolderGroupEntry], vault_root: Path) -> None:
    first = group[0]
    print(
        f"\nSet of identical folders: {len(group)} folders, {first.file_count:,} files, "
        f"{first.total_size:,} bytes each"
    )
    for index, entry in enumerate(group, start=1):
        rel_path = entry.path.relative_to(vault_root).as_posix()
        linked_path = terminal_link(entry.path, rel_path + "/")
        print(f"  [{index}] {linked_path} ({entry.file_count:,} files, {entry.total_size:,} bytes)")
        print(f"      {format_file_dates(entry.path)}")


def process_folder_groups(
    folder_groups: list[list[FolderGroupEntry]],
    vault_root: Path,
    reference_index: MarkdownReferenceIndex,
    media_files: list[MediaFile],
    groups: list[list[MediaFile]],
    rules: list[PreferenceRule] | None = None,
) -> bool:
    rules = rules if rules is not None else []
    removed_folder_count = 0
    removed_file_count = 0
    updated_markdown_count = 0

    for group in folder_groups:
        existing_group = [
            entry for entry in group
            if entry.path.exists() and all(f.path.is_file() for f in entry.files)
        ]
        if len(existing_group) < 2:
            continue

        winner, matched_rule = resolve_folder_group_with_rules(existing_group, rules, vault_root)
        if winner is not None and matched_rule is not None:
            describe_folder_group(existing_group, vault_root)
            winner_idx = existing_group.index(winner) + 1
            rel_winner = winner.path.relative_to(vault_root).as_posix()
            print(f"Auto-selected [{winner_idx}] {rel_winner}/ ({matched_rule.description}).")
            kept_entry = winner
        else:
            describe_folder_group(existing_group, vault_root)
            while True:
                choice = prompt("Choose a folder number to keep (e.g. 1, 1a to always prefer), [d]elete all, [s]kip, [q]uit: ")
                if choice is None:
                    if removed_folder_count > 0:
                        print(
                            f"\nDone. Removed {removed_folder_count} folder(s) "
                            f"({removed_file_count} file(s)); updated {updated_markdown_count} Markdown file(s)."
                        )
                    return False
                if choice.strip().lower() == "s":
                    break
                if choice.strip().lower() == "d":
                    break

                remember = False
                cleaned = choice.strip()
                if cleaned.lower().endswith("a") or cleaned.lower().endswith("!"):
                    remember = True
                    cleaned = cleaned[:-1].strip()
                elif cleaned.lower().startswith("a") and len(cleaned) > 1 and cleaned[1:].strip().isdigit():
                    remember = True
                    cleaned = cleaned[1:].strip()

                try:
                    choice_index = int(cleaned) - 1
                except (ValueError, IndexError):
                    print("Choose a listed option, d, s, or q (or append 'a' to remember, e.g. 1a).")
                    continue
                if 0 <= choice_index < len(existing_group):
                    kept_entry = existing_group[choice_index]
                    if remember:
                        kept_folder = kept_entry.path.relative_to(vault_root).as_posix()
                        for other_entry in existing_group:
                            if other_entry.path == kept_entry.path:
                                continue
                            other_folder = other_entry.path.relative_to(vault_root).as_posix()
                            r = FolderPreferenceRule(kept_folder, other_folder)
                            if r not in rules:
                                rules.append(r)
                        print(f"Preference saved: always prefer folder '{kept_folder}'.")
                    break
                else:
                    print("Choose a listed option, d, s, or q (or append 'a' to remember, e.g. 1a).")
                    continue

            if choice.strip().lower() == "s":
                continue

            if choice.strip().lower() == "d":
                all_removed_paths: set[Path] = set()
                for removed_entry in existing_group:
                    for removed_file in removed_entry.files:
                        try:
                            removed_file.path.unlink(missing_ok=True)
                        except OSError:
                            pass
                        reference_index.media_name_counts[removed_file.path.name.lower()] -= 1
                        all_removed_paths.add(removed_file.path)
                        removed_file_count += 1
                    shutil.rmtree(removed_entry.path, ignore_errors=True)
                    removed_folder_count += 1
                    rel_removed = removed_entry.path.relative_to(vault_root).as_posix()
                    print(
                        f"Removed folder {rel_removed}/ ({len(removed_entry.files)} file(s)); "
                        f"updated 0 Markdown file(s)."
                    )
                media_files[:] = [f for f in media_files if f.path not in all_removed_paths]
                for g in groups:
                    g[:] = [f for f in g if f.path not in all_removed_paths]
                continue

        kept_by_rel = {
            f.path.relative_to(kept_entry.path).as_posix(): f
            for f in kept_entry.files
        }

        all_removed_paths: set[Path] = set()
        for removed_entry in existing_group:
            if removed_entry.path == kept_entry.path:
                continue

            folder_updates: list[ReferenceUpdate] = []
            for removed_file in removed_entry.files:
                rel_sub = removed_file.path.relative_to(removed_entry.path).as_posix()
                kept_file = kept_by_rel[rel_sub]
                updates = update_markdown_references(
                    vault_root, removed_file, kept_file, reference_index
                )
                folder_updates.extend(updates)
                removed_file.path.unlink(missing_ok=True)
                reference_index.media_name_counts[removed_file.path.name.lower()] -= 1
                all_removed_paths.add(removed_file.path)
                removed_file_count += 1

            shutil.rmtree(removed_entry.path, ignore_errors=True)
            removed_folder_count += 1
            folder_updated_mds = {u.markdown_path for u in folder_updates}
            updated_markdown_count += len(folder_updated_mds)
            rel_removed = removed_entry.path.relative_to(vault_root).as_posix()
            print(
                f"Removed folder {rel_removed}/ ({len(removed_entry.files)} file(s)); "
                f"updated {len(folder_updated_mds)} Markdown file(s)."
            )
            print_reference_updates(folder_updates, vault_root)

        if all_removed_paths:
            media_files[:] = [f for f in media_files if f.path not in all_removed_paths]
            for g in groups:
                g[:] = [f for f in g if f.path not in all_removed_paths]
            groups[:] = [g for g in groups if len(g) > 1]

    if removed_folder_count > 0:
        print(
            f"\nDone folder-level deduplication. Removed {removed_folder_count} folder(s) "
            f"({removed_file_count} file(s)); updated {updated_markdown_count} Markdown file(s)."
        )
    return True


def describe_group(group: list[MediaFile]) -> None:
    print(f"\nSet of identical files: {len(group)} files, {group[0].size:,} bytes each")
    for index, media_file in enumerate(group, start=1):
        extension_note = "; no filename extension" if not media_file.path.suffix else ""
        linked_path = terminal_link(media_file.path, media_file.relative_path)
        print(f"  [{index}] {linked_path} ({media_file.mime_type}{extension_note})")
        print(f"      {format_file_dates(media_file.path)}")


def process_groups(
    groups: list[list[MediaFile]],
    vault_root: Path,
    reference_index: MarkdownReferenceIndex,
    rules: list[PreferenceRule] | None = None,
) -> None:
    rules = rules if rules is not None else []
    removed_count = 0
    updated_count = 0
    auto_count = 0
    folder_pairs_chosen: Counter[tuple[str, str]] = Counter()
    declined_pairs: set[tuple[str, str]] = set()

    for group in groups:
        winner, matched_rule = resolve_group_with_rules(group, rules, vault_root)
        auto_selected = False
        remember = False
        choice = ""

        if winner is not None and matched_rule is not None:
            describe_group(group)
            winner_idx = group.index(winner) + 1
            print(
                f"Auto-selected [{winner_idx}] {winner.relative_path} "
                f"({matched_rule.description})."
            )
            selected_file = winner
            kept = selected_file
            auto_selected = True
            auto_count += 1
        else:
            describe_group(group)
            while True:
                choice = prompt(
                    "Choose a file number to keep (e.g. 2, 2a to always prefer), [d]elete all, [c]ustom path, [s]kip, [q]uit: "
                )
                if choice is None:
                    total_note = f" ({auto_count} automatically)" if auto_count > 0 else ""
                    if removed_count > 0:
                        print(
                            f"\nDone. Removed {removed_count} media file(s){total_note}; "
                            f"updated {updated_count} Markdown file(s)."
                        )
                    return
                if choice.strip().lower() == "s":
                    break
                if choice.strip().lower() == "d":
                    break
                if choice.lower() in ("r", "rules"):
                    if not rules:
                        print("No active preference rules.")
                    else:
                        print("\nActive preference rules:")
                        for idx, r in enumerate(rules, start=1):
                            print(f"  {idx}. {r.description}")
                    continue
                if choice.lower() in ("clear-rules", "cr"):
                    rules[:] = [r for r in rules if isinstance(r, PreferredPathRule)]
                    folder_pairs_chosen.clear()
                    declined_pairs.clear()
                    print("Learned preference rules cleared.")
                    continue
                if choice.lower() == "c":
                    target = prompt("Custom relative path and filename [q]uit: ")
                    if target is None:
                        return
                    selected_file = group[0]
                    try:
                        kept = relocate_media_file(selected_file, target, vault_root)
                    except (ValueError, OSError) as error:
                        print(f"Cannot use that path: {error}")
                        continue
                    relocation_updates = update_markdown_references(
                        vault_root, selected_file, kept, reference_index
                    )
                    reference_index.media_name_counts[selected_file.path.name.lower()] -= 1
                    reference_index.media_name_counts[kept.path.name.lower()] += 1
                    print(f"Relocated {selected_file.relative_path} to {kept.relative_path}.")
                    print_reference_updates(relocation_updates, vault_root)
                    break

                cleaned_choice = choice.strip()
                remember = False
                if cleaned_choice.lower().endswith("a") or cleaned_choice.lower().endswith("!"):
                    remember = True
                    cleaned_choice = cleaned_choice[:-1].strip()
                elif (
                    cleaned_choice.lower().startswith("a")
                    and len(cleaned_choice) > 1
                    and cleaned_choice[1:].strip().isdigit()
                ):
                    remember = True
                    cleaned_choice = cleaned_choice[1:].strip()

                try:
                    choice_index = int(cleaned_choice) - 1
                except (ValueError, IndexError):
                    print("Choose a listed option, d, c, s, or q (or append 'a' to remember, e.g. 2a).")
                    continue
                if 0 <= choice_index < len(group):
                    selected_file = group[choice_index]
                    kept = selected_file
                    if remember:
                        prompt_and_add_preference(
                            selected_file, group, vault_root, rules, prompt_count=None
                        )
                    break
                else:
                    print("Choose a listed option, d, c, s, or q (or append 'a' to remember, e.g. 2a).")
                    continue

        if not auto_selected and choice.strip().lower() == "s":
            continue

        if not auto_selected and choice.strip().lower() == "d":
            for removed in group:
                try:
                    removed.path.unlink(missing_ok=True)
                except OSError:
                    pass
                reference_index.media_name_counts[removed.path.name.lower()] -= 1
                removed_count += 1
                print(
                    f"Removed {removed.relative_path}; updated 0 Markdown file(s)."
                )
            continue

        if (
            not auto_selected
            and not selected_file.path.suffix
            and selected_file.mime_type in MIME_EXTENSIONS
        ):
            while True:
                rename_choice = prompt(
                    f"Kept file is {selected_file.mime_type} but has no extension. Add "
                    f"{MIME_EXTENSIONS[selected_file.mime_type]} and update its links? [y]es, [n]o, [q]uit: "
                )
                if rename_choice is None:
                    total_note = f" ({auto_count} automatically)" if auto_count > 0 else ""
                    print(
                        f"\nDone. Removed {removed_count} media file(s){total_note}; "
                        f"updated {updated_count} Markdown file(s)."
                    )
                    return
                if rename_choice.lower() == "n":
                    break
                if rename_choice.lower() == "y":
                    renamed_file = rename_extensionless_media(selected_file, vault_root)
                    if renamed_file is not None:
                        rename_updates = update_markdown_references(
                            vault_root, selected_file, renamed_file, reference_index
                        )
                        reference_index.media_name_counts[selected_file.path.name.lower()] -= 1
                        reference_index.media_name_counts[renamed_file.path.name.lower()] += 1
                        kept = renamed_file
                        print(f"Renamed {selected_file.relative_path} to {renamed_file.relative_path}.")
                        print_reference_updates(rename_updates, vault_root)
                    break
                print("Choose y, n, or q.")

        for removed in group:
            if removed == selected_file:
                continue
            updates = update_markdown_references(vault_root, removed, kept, reference_index)
            try:
                removed.path.unlink(missing_ok=True)
            except OSError:
                pass
            reference_index.media_name_counts[removed.path.name.lower()] -= 1
            removed_count += 1
            updated_count += len({update.markdown_path for update in updates})
            print(
                f"Removed {removed.relative_path}; "
                f"updated {len({update.markdown_path for update in updates})} Markdown file(s)."
            )
            print_reference_updates(updates, vault_root)

        if not auto_selected and not remember:
            selected_folder = get_relative_parent(selected_file.path, vault_root)
            for removed in group:
                if removed == selected_file:
                    continue
                removed_folder = get_relative_parent(removed.path, vault_root)
                if (
                    not selected_folder
                    or not removed_folder
                    or selected_folder.lower() == removed_folder.lower()
                ):
                    continue
                pair = (selected_folder, removed_folder)
                folder_pairs_chosen[pair] += 1
                if folder_pairs_chosen[pair] >= 2 and pair not in declined_pairs:
                    already_covered = any(
                        r.matches(selected_file, removed, vault_root) for r in rules
                    )
                    if not already_covered:
                        offered = prompt_and_add_preference(
                            selected_file,
                            [selected_file, removed],
                            vault_root,
                            rules,
                            prompt_count=folder_pairs_chosen[pair],
                        )
                        if not offered:
                            declined_pairs.add(pair)

    auto_note = f" ({auto_count} automatically)" if auto_count > 0 else ""
    print(f"\nDone. Removed {removed_count} media file(s){auto_note}; updated {updated_count} Markdown file(s).")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactively remove byte-identical media files.")
    parser.add_argument(
        "-f",
        "--folder",
        dest="vault_directory",
        help="Root directory to scan (media folders only unless --all-folders is used)",
    )
    parser.add_argument(
        "--all-folders",
        action="store_true",
        help="Scan all folders and file types, excluding dot-prefixed filenames and the output index",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Folder for {DEFAULT_INDEX_NAME} (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--prefer",
        action="append",
        default=[],
        help="Path prefix or folder to prefer when resolving duplicate files (can be specified multiple times)",
    )
    parser.add_argument(
        "--keep-bak",
        "--no-delete-bak",
        action="store_true",
        dest="keep_bak",
        help="Do not delete .bak files (by default, .bak files are deleted)",
    )
    return parser.parse_args()


def main() -> int:
    try:
        return run()
    except KeyboardInterrupt:
        print(
            "\nInterrupted. Stopping; changes already made are not undone. "
            "Any completed index save remains on disk.",
            file=sys.stderr,
        )
        return 130


def run() -> int:
    args = parse_arguments()
    vault_text = args.vault_directory or prompt("Vault directory [.]: ") or "."
    vault_root = Path(vault_text).expanduser().resolve()
    if not vault_root.is_dir():
        print(f"Vault root does not exist: {vault_root}", file=sys.stderr)
        return 1

    output_dir = Path(args.output).expanduser().resolve()
    index_path = output_dir / DEFAULT_INDEX_NAME
    excluded_paths = {index_path.resolve()}
    media_files: list[MediaFile]
    groups: list[list[MediaFile]]
    cached_markdown_files: dict[str, MarkdownReferenceFile] = {}
    if index_path.is_file():
        choice = prompt("Existing media index found. [u]pdate (reuse hashes), [r]egenerate (rehash all), or [q]uit: ")
        if choice is None:
            return 0
        if choice.lower() in ("", "u"):
            try:
                print("Loading cached media index...", flush=True)
                cached_files, cached_markdown_files = load_media_manifest(index_path, vault_root)
                print("Checking media files and reusing hashes for unchanged files...", flush=True)
                media_files, groups = build_media_index(
                    vault_root, cached_files, args.all_folders, excluded_paths
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                print(f"Existing index needs a one-time upgrade ({error}); regenerating it.")
                media_files, groups = build_media_index(
                    vault_root, all_folders=args.all_folders, excluded_paths=excluded_paths
                )
        elif choice.lower() == "r":
            media_files, groups = build_media_index(
                vault_root, all_folders=args.all_folders, excluded_paths=excluded_paths
            )
        else:
            print("Choose u, r, or q.")
            return 1
    else:
        media_files, groups = build_media_index(
            vault_root, all_folders=args.all_folders, excluded_paths=excluded_paths
        )

    bak_files = [
        media_file
        for media_file in media_files
        if media_file.path.name.lower().endswith(".bak")
    ]
    if bak_files and not args.keep_bak:
        deleted_bak = handle_bak_files(bak_files, keep_bak=args.keep_bak)
        if deleted_bak:
            deleted_bak_paths = {file.path for file in deleted_bak}
            media_files = [file for file in media_files if file.path not in deleted_bak_paths]
            for g in groups:
                g[:] = [f for f in g if f.path not in deleted_bak_paths]
            groups = [g for g in groups if len(g) > 1]

    empty_files = [
        media_file
        for media_file in media_files
        if media_file.size == 0
        and not (args.keep_bak and media_file.path.name.lower().endswith(".bak"))
    ]
    if empty_files:
        deleted = handle_empty_files(empty_files)
        if deleted is None:
            return 0
        if deleted:
            deleted_paths = {file.path for file in deleted}
            media_files = [file for file in media_files if file.path not in deleted_paths]
            for g in groups:
                g[:] = [f for f in g if f.path not in deleted_paths]
            groups = [g for g in groups if len(g) > 1]
    if not groups:
        index_path = write_duplicate_index(output_dir, media_files, groups)
        print(f"Duplicate index: {terminal_link(index_path)}")
        print("No byte-identical media files found.")
        return 0
    print(f"Found {len(groups)} set(s) of identical files. Enter q at any prompt to quit.")
    reference_index = build_markdown_reference_index(
        vault_root, media_files, cached_markdown_files
    )
    index_path = write_duplicate_index(output_dir, media_files, groups, reference_index)
    print(f"Duplicate index: {terminal_link(index_path)}")
    rules: list[PreferenceRule] = []
    if args.prefer:
        for pref in args.prefer:
            rules.append(PreferredPathRule(pref))

    folder_groups = find_duplicate_folder_groups(vault_root, media_files)
    if folder_groups:
        keep_going = process_folder_groups(
            folder_groups, vault_root, reference_index, media_files, groups, rules=rules
        )
        if not keep_going:
            return 0
        groups[:] = [g for g in groups if len(g) > 1]
    if not groups:
        print("No remaining byte-identical media files found.")
        return 0
    process_groups(groups, vault_root, reference_index, rules=rules)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())