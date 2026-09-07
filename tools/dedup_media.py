#!/usr/bin/env python3

"""Interactively remove byte-identical media files and update Markdown links.

Usage:
    python tools/dedup_media.py -f VAULT_DIRECTORY

The tool scans every folder named ``media`` below the vault directory. With no
arguments, it prompts for the vault directory. Enter ``q`` at
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
from collections import defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import quote


WIKILINK_PATTERN = re.compile(r"(!?\[\[)([^\]\n]+)(\]\])")
MARKDOWN_LINK_PATTERN = re.compile(r"(\]\()([^\s)]+)(?:\s+[^)]*)?(\))")
CRYPTIC_FILENAME_PATTERN = re.compile(
    r"(?:[0-9a-f]{12,}|[0-9]{8,}|(?:attachment|document|dsc|file|image|img|media|photo|pxl|video)[ _-]*[0-9][\w _-]*)$",
    re.IGNORECASE,
)
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


def media_file_paths(vault_root: Path):
    for path in vault_root.rglob("*"):
        if path.is_file() and not path.name.startswith(".") and any(
            parent.name.lower() == "media" for parent in path.parents
        ):
            yield path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def detect_mime_type(path: Path) -> str:
    with path.open("rb") as handle:
        header = handle.read(32)
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
    vault_root: Path, cached_files: dict[str, MediaFile] | None = None
) -> tuple[list[MediaFile], list[list[MediaFile]]]:
    cached_files = cached_files or {}
    by_size: dict[int, list[MediaFile]] = defaultdict(list)
    indexed_count = 0
    print("Indexing media files...", flush=True)
    for indexed_count, path in enumerate(media_file_paths(vault_root), start=1):
        stat_result = path.stat()
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
        for files in by_size.values()
        if len(files) > 1
        for media_file in files
        if not media_file.digest
    ]
    if hash_files:
        print(f"Hashing {len(hash_files):,} new or changed candidate file(s)...", flush=True)
    hashed_count = 0
    for files in by_size.values():
        if len(files) < 2:
            continue
        for media_file in files:
            if media_file.digest:
                continue
            media_file_index = media_files.index(media_file)
            hashed_file = MediaFile(
                path=media_file.path,
                relative_path=media_file.relative_path,
                size=media_file.size,
                mime_type=media_file.mime_type,
                digest=sha256_file(media_file.path),
                modified_time_ns=media_file.modified_time_ns,
            )
            files[files.index(media_file)] = hashed_file
            media_files[media_file_index] = hashed_file
            hashed_count += 1
            if hashed_count == 1 or hashed_count % 100 == 0:
                print(f"\r\033[2KHashed {hashed_count:,} of {len(hash_files):,} candidate files", end="", flush=True)

    groups: list[list[MediaFile]] = []
    for files in by_size.values():
        by_digest: dict[str, list[MediaFile]] = defaultdict(list)
        for media_file in files:
            if media_file.digest:
                by_digest[media_file.digest].append(media_file)
        for matching_files in by_digest.values():
            if len(matching_files) < 2:
                continue
            groups.append(sorted(matching_files, key=lambda media_file: media_file.relative_path.lower()))
    if hashed_count:
        print()
    return media_files, sorted(groups, key=lambda group: group[0].relative_path.lower())


def find_duplicate_groups(vault_root: Path) -> list[list[MediaFile]]:
    _, groups = build_media_index(vault_root)
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
        relative_path = markdown_path.relative_to(vault_root).as_posix()
        cached_file = cached_markdown_files.get(relative_path)
        if cached_file and cached_file.modified_time_ns == markdown_path.stat().st_mtime_ns:
            reference_file = cached_file
            reused_count += 1
        else:
            text, _ = read_markdown(markdown_path)
            reference_file = MarkdownReferenceFile(
                modified_time_ns=markdown_path.stat().st_mtime_ns,
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
        text, encoding = read_markdown(markdown_path)

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


def describe_group(group: list[MediaFile]) -> None:
    print(f"\nSet of identical files: {len(group)} files, {group[0].size:,} bytes each")
    for index, media_file in enumerate(group, start=1):
        extension_note = "; no filename extension" if not media_file.path.suffix else ""
        linked_path = terminal_link(media_file.path, media_file.relative_path)
        print(f"  [{index}] {linked_path} ({media_file.mime_type}{extension_note})")
    for index, (location_file, filename_file) in enumerate(cross_location_filename_options(group), start=len(group) + 1):
        target = Path(location_file.relative_path).parent / filename_file.path.name
        print(f"  [{index}] {target.as_posix()}")


def cross_location_filename_options(group: list[MediaFile]) -> list[tuple[MediaFile, MediaFile]]:
    if group and all(CRYPTIC_FILENAME_PATTERN.fullmatch(media_file.path.stem) for media_file in group):
        return []
    return [
        (location_file, filename_file)
        for location_file in group
        for filename_file in group
        if location_file != filename_file
        and not (location_file.path.parent / filename_file.path.name).exists()
    ]


def process_groups(
    groups: list[list[MediaFile]], vault_root: Path, reference_index: MarkdownReferenceIndex
) -> None:
    removed_count = 0
    updated_count = 0
    for group in groups:
        describe_group(group)
        cross_options = cross_location_filename_options(group)
        while True:
            choice = prompt("Choose an option, [c]ustom path, [s]kip, [q]uit: ")
            if choice is None:
                return
            if choice.lower() == "s":
                break
            if choice.lower() == "c":
                target = prompt("Custom relative path and filename [q]uit: ")
                if target is None:
                    return
                selected_file = group[0]
                try:
                    kept = relocate_media_file(selected_file, target, vault_root)
                except ValueError as error:
                    print(f"Cannot use that path: {error}")
                    continue
                relocation_updates = update_markdown_references(vault_root, selected_file, kept, reference_index)
                reference_index.media_name_counts[selected_file.path.name.lower()] -= 1
                reference_index.media_name_counts[kept.path.name.lower()] += 1
                print(f"Relocated {selected_file.relative_path} to {kept.relative_path}.")
                print_reference_updates(relocation_updates, vault_root)
                break
            try:
                choice_index = int(choice) - 1
            except (ValueError, IndexError):
                print("Choose a listed option, c, s, or q.")
                continue
            if 0 <= choice_index < len(group):
                selected_file = group[choice_index]
                kept = selected_file
            elif choice_index - len(group) < len(cross_options):
                selected_file, filename_file = cross_options[choice_index - len(group)]
                target = selected_file.path.parent / filename_file.path.name
                try:
                    kept = relocate_media_file(selected_file, target.relative_to(vault_root), vault_root)
                except ValueError as error:
                    print(f"Cannot use that option: {error}")
                    continue
                relocation_updates = update_markdown_references(vault_root, selected_file, kept, reference_index)
                reference_index.media_name_counts[selected_file.path.name.lower()] -= 1
                reference_index.media_name_counts[kept.path.name.lower()] += 1
                print(f"Relocated {selected_file.relative_path} to {kept.relative_path}.")
                print_reference_updates(relocation_updates, vault_root)
            else:
                print("Choose a listed option, c, s, or q.")
                continue
            break
        if choice.lower() == "s":
            continue

        if not selected_file.path.suffix and selected_file.mime_type in MIME_EXTENSIONS:
            while True:
                rename_choice = prompt(
                    f"Kept file is {selected_file.mime_type} but has no extension. Add "
                    f"{MIME_EXTENSIONS[selected_file.mime_type]} and update its links? [y]es, [n]o, [q]uit: "
                )
                if rename_choice is None:
                    print(f"\nDone. Removed {removed_count} media file(s); updated {updated_count} Markdown file(s).")
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
            removed.path.unlink()
            reference_index.media_name_counts[removed.path.name.lower()] -= 1
            removed_count += 1
            updated_count += len({update.markdown_path for update in updates})
            print(f"Removed {removed.relative_path}; updated {len({update.markdown_path for update in updates})} Markdown file(s).")
            print_reference_updates(updates, vault_root)
    print(f"\nDone. Removed {removed_count} media file(s); updated {updated_count} Markdown file(s).")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactively remove byte-identical media files.")
    parser.add_argument(
        "-f",
        "--folder",
        dest="vault_directory",
        help="Vault directory containing media folders",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Folder for {DEFAULT_INDEX_NAME} (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    vault_text = args.vault_directory or prompt("Vault directory [.]: ") or "."
    vault_root = Path(vault_text).expanduser().resolve()
    if not vault_root.is_dir():
        print(f"Vault root does not exist: {vault_root}", file=sys.stderr)
        return 1

    output_dir = Path(args.output).expanduser().resolve()
    index_path = output_dir / DEFAULT_INDEX_NAME
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
                media_files, groups = build_media_index(vault_root, cached_files)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                print(f"Existing index needs a one-time upgrade ({error}); regenerating it.")
                media_files, groups = build_media_index(vault_root)
        elif choice.lower() == "r":
            media_files, groups = build_media_index(vault_root)
        else:
            print("Choose u, r, or q.")
            return 1
    else:
        media_files, groups = build_media_index(vault_root)
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
    process_groups(groups, vault_root, reference_index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())