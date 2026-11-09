#!/usr/bin/env python3
"""Convert Markdown frontmatter to Google Open Knowledge Format (OKF).

Finds the first tag in the frontmatter `tags` list that matches a known
document type, and inserts a `type: <Type>` field as the first frontmatter
field. Removes the matched tag except for `tool`, which is retained.
Supports single tags, block lists, and inline lists such as
`tags: [chat, project-x]`; modified tag lists use block style.
Known types are read from the `type:` field of the template files
(default C:\\notes\\Templates), plus extra tag=Type mappings.

Runs as a dry run unless --apply is supplied. Dry runs list skipped files
and errors, followed by summary counts. Pause Syncthing and other writers
before applying changes.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from yaml.nodes import ScalarNode, SequenceNode


FRONTMATTER_SEPARATOR = "---"

DEFAULT_ROOT = Path("C:/notes")
DEFAULT_TEMPLATES = Path("C:/notes/Templates")
DEFAULT_EXCLUDES = (".obsidian", ".trash", ".git", "Templates")

# tag -> type mappings for tags that have no matching template
DEFAULT_EXTRA_MAPPINGS = {
    "app": "App",
    "tool": "App",
    "note": "Note",
    "phone-call": "Call",
    "dog": "Pet",
    "halmd": "halmd",
    "meeting": "Meeting",
    "meetings": "Meeting",
    "course": "Course",
    "technology": "Technology",
    "service": "Service",
    "resource": "Resource",
}
PRESERVED_TYPE_TAGS = frozenset({"tool"})

TYPE_FIELD_PATTERN = re.compile(r"^[Tt]ype\s*:")
TAGS_FIELD_PATTERN = re.compile(r"^tags\s*:\s*$")
INLINE_TAGS_PATTERN = re.compile(r"^tags\s*:\s*(?P<value>\[.*)$")
SCALAR_TAGS_PATTERN = re.compile(r"^tags\s*:\s*(?P<value>\S.*)$")
TAG_ITEM_PATTERN = re.compile(r"^(\s+-\s*)(.*?)\s*$")

CONVERTED = "converted"
NO_FRONTMATTER = "no frontmatter"
HAS_TYPE = "already has a type field"
NO_TAGS = "no tags field"
NO_MATCH = "no tag matches a known type"
NOT_UTF8 = "not valid UTF-8"


@dataclass
class ConversionResult:
    converted: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    errors: int = 0


class InvalidInlineTagsError(ValueError):
    """An inline tags list cannot be converted without risking data loss."""


class InvalidScalarTagsError(ValueError):
    """A scalar tags value cannot be converted without risking data loss."""


def load_type_map(templates_dir: Path) -> dict[str, str]:
    """Map lowercase tag names to type names from the templates' type fields."""
    type_map: dict[str, str] = {}
    for template in sorted(templates_dir.glob("*.md")):
        lines = read_file(template).splitlines()
        if not lines or lines[0].strip() != FRONTMATTER_SEPARATOR:
            continue
        for line in lines[1:]:
            if line.strip() == FRONTMATTER_SEPARATOR:
                break
            if TYPE_FIELD_PATTERN.match(line):
                value = line.split(":", 1)[1].strip()
                if value:
                    type_map[value.lower()] = value
                break
    return type_map


def normalize_tag(value: str) -> str:
    """Normalize a tags list item for comparison against known types."""
    return value.strip().strip("'\"").lstrip("#").lower()


def convert_inline_tags(
    value: str, type_map: dict[str, str], line_end: str
) -> tuple[list[str] | None, str]:
    try:
        node = yaml.compose(value)
    except yaml.YAMLError as error:
        raise InvalidInlineTagsError(f"invalid inline tags: {error}") from error
    if not isinstance(node, SequenceNode) or not node.flow_style:
        raise InvalidInlineTagsError("invalid inline tags: expected a YAML list")

    tags: list[str | None] = []
    for item in node.value:
        if not isinstance(item, ScalarNode) or item.tag not in (
            "tag:yaml.org,2002:str", "tag:yaml.org,2002:null"
        ):
            raise InvalidInlineTagsError(
                "invalid inline tags: items must be strings or empty values"
            )
        tags.append(None if item.tag == "tag:yaml.org,2002:null" else item.value)

    for index, tag in enumerate(tags):
        type_name = type_map.get(normalize_tag(tag)) if tag is not None else None
        if type_name:
            break
    else:
        raise ValueError(NO_MATCH)

    if tag is not None and normalize_tag(tag) in PRESERVED_TYPE_TAGS:
        return None, type_name

    del tags[index]
    comment = value[node.end_mark.index:]
    if any(tag is not None and tag.strip() for tag in tags):
        serialized = yaml.safe_dump(tags, allow_unicode=True, default_flow_style=False)
        items = ["  " + line + line_end for line in serialized.splitlines()]
    else:
        items = ["  - " + line_end]
    return ["tags:" + comment + line_end, *items], type_name


def convert_scalar_tag(
    value: str, type_map: dict[str, str], line_end: str
) -> tuple[list[str] | None, str]:
    try:
        tokens = list(yaml.scan(value))
        node = yaml.compose(value)
    except yaml.YAMLError as error:
        raise InvalidScalarTagsError(f"invalid scalar tags: {error}") from error
    if any(isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken,
                              yaml.tokens.TagToken)) for token in tokens):
        raise InvalidScalarTagsError("invalid scalar tags: anchors and tags are unsupported")
    if isinstance(node, ScalarNode) and node.tag == "tag:yaml.org,2002:null":
        raise ValueError(NO_MATCH)
    if (not isinstance(node, ScalarNode) or node.tag != "tag:yaml.org,2002:str"
            or node.style not in (None, "'", '"')):
        raise InvalidScalarTagsError("invalid scalar tags: expected a single-line string")
    type_name = type_map.get(normalize_tag(node.value))
    if not type_name:
        raise ValueError(NO_MATCH)
    if normalize_tag(node.value) in PRESERVED_TYPE_TAGS:
        return None, type_name
    comment = value[node.end_mark.index:]
    return ["tags:" + comment + line_end, "  - " + line_end], type_name


def convert_text(text: str, type_map: dict[str, str]) -> tuple[str, str] | None:
    """Return (converted text, type name), or None if no conversion applies.

    Raises ValueError with a skip reason when the file cannot be converted.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != FRONTMATTER_SEPARATOR:
        raise ValueError(NO_FRONTMATTER)
    line_end = "\r\n" if lines[0].endswith("\r\n") else "\n"

    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == FRONTMATTER_SEPARATOR:
            end = index
            break
    if end is None:
        raise ValueError(NO_FRONTMATTER)

    tags_line = None
    for index in range(1, end):
        if TYPE_FIELD_PATTERN.match(lines[index]):
            raise ValueError(HAS_TYPE)
        if tags_line is None and (
            TAGS_FIELD_PATTERN.match(lines[index])
            or INLINE_TAGS_PATTERN.match(lines[index])
            or SCALAR_TAGS_PATTERN.match(lines[index])
        ):
            tags_line = index
    if tags_line is None:
        raise ValueError(NO_TAGS)

    inline_match = INLINE_TAGS_PATTERN.match(lines[tags_line].rstrip("\r\n"))
    if inline_match is not None:
        replacement, type_name = convert_inline_tags(
            inline_match["value"], type_map, line_end
        )
        if replacement is not None:
            lines[tags_line:tags_line + 1] = replacement
        lines.insert(1, f"type: {type_name}" + line_end)
        return "".join(lines), type_name

    scalar_match = SCALAR_TAGS_PATTERN.match(lines[tags_line].rstrip("\r\n"))
    if scalar_match is not None and not scalar_match["value"].startswith("#"):
        for line in lines[tags_line + 1:end]:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line[0].isspace():
                raise InvalidScalarTagsError(
                    "invalid scalar tags: multiline values are unsupported"
                )
            break
        replacement, type_name = convert_scalar_tag(
            scalar_match["value"], type_map, line_end
        )
        if replacement is not None:
            lines[tags_line:tags_line + 1] = replacement
        lines.insert(1, f"type: {type_name}" + line_end)
        return "".join(lines), type_name

    # collect the tags list items that follow the tags: line
    items = []
    index = tags_line + 1
    while index < end:
        match = TAG_ITEM_PATTERN.match(lines[index])
        if match is None:
            break
        items.append((index, match[2]))
        index += 1

    match_index = None
    type_name = None
    for item_index, value in items:
        type_name = type_map.get(normalize_tag(value))
        if type_name:
            match_index = item_index
            break
    if match_index is None:
        raise ValueError(NO_MATCH)

    if normalize_tag(value) in PRESERVED_TYPE_TAGS:
        lines.insert(1, f"type: {type_name}" + line_end)
        return "".join(lines), type_name

    remaining = [value for item_index, value in items if item_index != match_index]
    del lines[match_index]
    if not any(value.strip() for value in remaining):
        # keep an empty item so a tag can easily be added later
        for item_index, _ in reversed(items):
            if item_index != match_index:
                del lines[item_index if item_index < match_index else item_index - 1]
        lines.insert(tags_line + 1, "  - " + line_end)
    lines.insert(1, f"type: {type_name}" + line_end)
    return "".join(lines), type_name


def read_file(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig")


def write_file(path: Path, text: str) -> None:
    data = text.encode("utf-8")
    if path.read_bytes().startswith(b"\xef\xbb\xbf"):
        data = b"\xef\xbb\xbf" + data
    path.write_bytes(data)


def find_markdown_files(root: Path, excludes: set[str]) -> list[Path]:
    found = []
    for directory, dir_names, file_names in os.walk(root):
        dir_names[:] = sorted(name for name in dir_names if name not in excludes)
        found.extend(
            Path(directory) / name
            for name in sorted(file_names)
            if name.lower().endswith(".md")
        )
    return found


def convert_files(
    root: Path,
    type_map: dict[str, str],
    excludes: set[str],
    apply: bool,
    verbose: bool,
) -> ConversionResult:
    result = ConversionResult()
    for path in find_markdown_files(root, excludes):
        try:
            text = read_file(path)
            converted = convert_text(text, type_map)
        except UnicodeDecodeError:
            result.skipped[NOT_UTF8] = result.skipped.get(NOT_UTF8, 0) + 1
            if not apply or verbose:
                print(f"skipped ({NOT_UTF8}): {path}")
            continue
        except (InvalidInlineTagsError, InvalidScalarTagsError) as error:
            result.errors += 1
            print(f"error: {path}: {error}", file=sys.stderr)
            continue
        except ValueError as error:
            reason = str(error)
            result.skipped[reason] = result.skipped.get(reason, 0) + 1
            if reason not in (NO_TAGS, NO_FRONTMATTER) and (
                not apply or (verbose and reason != HAS_TYPE)
            ):
                print(f"skipped ({reason}): {path}")
            continue
        except OSError as error:
            result.errors += 1
            print(f"error: {path}: {error}", file=sys.stderr)
            continue
        new_text, type_name = converted
        if apply:
            try:
                write_file(path, new_text)
            except OSError as error:
                result.errors += 1
                print(f"error: {path}: {error}", file=sys.stderr)
                continue
        result.converted += 1
        if apply:
            print(f"converted [{type_name}]: {path}")
    return result


def parse_mapping(value: str) -> tuple[str, str]:
    tag, separator, type_name = value.partition("=")
    if not separator or not tag.strip() or not type_name.strip():
        raise argparse.ArgumentTypeError(f"expected tag=Type, got: {value!r}")
    return tag.strip().lower(), type_name.strip()


def main(argv: list[str] | None = None) -> int:
    # note filenames often contain characters the Windows console encoding lacks
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help=f"folder to convert recursively (default: {DEFAULT_ROOT})",
    )
    parser.add_argument(
        "--templates",
        type=Path,
        default=DEFAULT_TEMPLATES,
        help=f"folder of templates defining the types (default: {DEFAULT_TEMPLATES})",
    )
    parser.add_argument(
        "--map",
        action="append",
        type=parse_mapping,
        default=[],
        metavar="TAG=TYPE",
        help="extra tag to type mapping, repeatable (e.g. --map phone-call=Call)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=list(DEFAULT_EXCLUDES),
        metavar="NAME",
        help=f"folder name to skip, repeatable (default: {', '.join(DEFAULT_EXCLUDES)})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write changes (default: dry run reports skipped files and counts)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="when applying, also list files skipped for unknown types or encoding",
    )
    arguments = parser.parse_args(argv)

    if not arguments.root.is_dir():
        parser.error(f"not a directory: {arguments.root}")
    if not arguments.templates.is_dir():
        parser.error(f"not a directory: {arguments.templates}")

    type_map = load_type_map(arguments.templates)
    type_map.update(DEFAULT_EXTRA_MAPPINGS)
    type_map.update(arguments.map)
    if not type_map:
        parser.error(f"no types found in {arguments.templates}")

    result = convert_files(
        arguments.root,
        type_map,
        set(arguments.exclude),
        arguments.apply,
        arguments.verbose,
    )

    mode = "" if arguments.apply else " (dry run, use --apply to write)"
    print(f"\nconverted: {result.converted}{mode}")
    for reason, count in sorted(result.skipped.items()):
        print(f"skipped, {reason}: {count}")
    if result.errors:
        print(f"errors: {result.errors}")
    return 1 if result.errors else 0


if __name__ == "__main__":
    sys.exit(main())
