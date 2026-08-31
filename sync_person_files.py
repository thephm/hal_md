"""Synchronize selected Person.md fields without reserializing personal notes."""

import argparse
import csv
import datetime as dt
import difflib
import hashlib
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from markdown_cleanup import normalize_heading_spacing
from text_encoding import repair_mojibake


def default_dev_output_dir(platform: str | None = None, environment: dict[str, str] | None = None) -> Path:
    environment = environment if environment is not None else os.environ
    default = r"C:\data\dev-output" if (platform or os.name) == "nt" else "/mnt/c/data/dev-output"
    return Path(environment.get("HAL_MD_DEV_OUTPUT_DIR", default))


def default_config_dir(platform: str | None = None, environment: dict[str, str] | None = None) -> Path:
    environment = environment if environment is not None else os.environ
    return Path(environment.get("HAL_MD_CONFIG_DIR", default_dev_output_dir(platform, environment) / "config"))


DEFAULT_STATE_DIR = default_dev_output_dir() / "people_sync_state"
DEFAULT_ORGANIZATIONS_PATH = default_config_dir() / "organizations.json"
CONTACT_FIELDS = ("mobile", "email", "linkedin_id")
FRONTMATTER_FIELD_ORDER = (
    "tags", "first_name", "last_name", "aliases", "slug", "birthday", "title",
    "skills", "interests", "organizations", "url", "email", "mobile", "phone",
    "x_id", "linkedin_id", "linkedin_url", "city", "province", "country",
)
SECTION_ORDER = ("## Bio", "## References", "## Life Events", "## People", "## Positions", "## Notes")
H2_PATTERN = re.compile(r"(?m)^## [^\r\n]+\r?$")
DATE_PATTERN = re.compile(r"\b(\d{4}(?:-\d{2}(?:-\d{2})?)?)\b")
DATED_FILE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}(?:\D.*)?\.md$", re.I)
WIKILINK_DATE_PATTERN = re.compile(r"!\[\[[^\]]*/(\d{4}-\d{2}-\d{2})\.md\]\]")
INLINE_DATE_PATTERN = re.compile(r"(?m)^\s*[-*]?\s*(\d{4}-\d{2}-\d{2}):")
CHANGE_REPORT_FIELDS = ("date", "time", "action", "field", "name", "old_value", "new_value", "path", "slug")


@dataclass
class PersonDocument:
    path: Path
    raw: str
    frontmatter: dict[str, Any]
    frontmatter_start: int
    frontmatter_end: int

    @property
    def slug(self) -> str:
        return str(self.frontmatter.get("slug") or "")

    @property
    def name(self) -> str:
        return " ".join(
            str(self.frontmatter.get(key) or "").strip()
            for key in ("first_name", "last_name")
            if self.frontmatter.get(key)
        ) or self.path.stem


def read_document(path: Path) -> PersonDocument | None:
    """Read a Person note while retaining exact source text and YAML offsets."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        logging.warning("Skipping unreadable file %s: %s", path, error)
        return None
    match = re.match(r"\A(?:\ufeff)?---\r?\n(?P<yaml>.*?)(?P<end>^---\r?\n?)", raw, re.S | re.M)
    if not match:
        logging.debug("Skipping file without frontmatter: %s", path)
        return None
    try:
        frontmatter = yaml.safe_load(match.group("yaml")) or {}
    except yaml.YAMLError as error:
        logging.warning("Skipping malformed frontmatter %s: %s", path, error)
        return None
    if not isinstance(frontmatter, dict):
        logging.warning("Skipping non-mapping frontmatter: %s", path)
        return None
    tags = frontmatter.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    if "person" not in tags:
        return None
    return PersonDocument(path, raw, frontmatter, match.start(), match.end())


def document_from_raw(path: Path, raw: str) -> PersonDocument:
    match = re.match(r"\A(?:\ufeff)?---\r?\n(?P<yaml>.*?)(?P<end>^---\r?\n?)", raw, re.S | re.M)
    if not match:
        raise ValueError("raw document lost YAML frontmatter")
    frontmatter = yaml.safe_load(match.group("yaml")) or {}
    return PersonDocument(path, raw, frontmatter, match.start(), match.end())


def discover_people(root: Path) -> list[PersonDocument]:
    people: list[PersonDocument] = []
    for path in root.rglob("*.md"):
        if "media" in path.parts or DATED_FILE_PATTERN.match(path.name):
            continue
        document = read_document(path)
        if document:
            people.append(document)
    return people


def split_csv_values(values: Iterable[str] | None) -> set[str]:
    return {item.strip() for value in values or [] for item in value.split(",") if item.strip()}


def tag_values(document: PersonDocument) -> set[str]:
    tags = document.frontmatter.get("tags", [])
    return {str(tag) for tag in (tags if isinstance(tags, list) else [tags])}


def scope_people(people: list[PersonDocument], args: argparse.Namespace) -> list[PersonDocument]:
    requested_slugs = split_csv_values(args.slug)
    requested_linkedin_ids = split_csv_values(args.linkedin_id)
    if requested_slugs or requested_linkedin_ids:
        return [person for person in people if person.slug in requested_slugs or str(person.frontmatter.get("linkedin_id", "")) in requested_linkedin_ids]
    requested_tags = split_csv_values(args.tag)
    scoped = [person for person in people if not requested_tags or tag_values(person) & requested_tags]
    return scoped[:args.max] if args.max else scoped


def duplicate_slugs(people: Iterable[PersonDocument]) -> dict[str, list[PersonDocument]]:
    grouped: dict[str, list[PersonDocument]] = {}
    for person in people:
        if person.slug:
            grouped.setdefault(person.slug, []).append(person)
    return {slug: matches for slug, matches in grouped.items() if len(matches) > 1}


def section_span(raw: str, heading: str) -> tuple[int, int] | None:
    match = re.search(rf"(?m)^{re.escape(heading)}\r?$", raw)
    if not match:
        return None
    content_start = match.end()
    if raw[content_start:content_start + 2] == "\r\n":
        content_start += 2
    elif raw[content_start:content_start + 1] == "\n":
        content_start += 1
    next_heading = H2_PATTERN.search(raw, content_start)
    return content_start, next_heading.start() if next_heading else len(raw)


def section_content(raw: str, heading: str) -> str:
    span = section_span(raw, heading)
    return raw[span[0]:span[1]] if span else ""


def linkedin_profile_url(values: dict[str, Any]) -> str:
    url = str(values.get("linkedin_url") or "").strip()
    if url:
        return url
    linkedin_id = str(values.get("linkedin_id") or "").strip()
    return f"https://www.linkedin.com/in/{linkedin_id}" if linkedin_id else ""


def replace_section(raw: str, heading: str, content: str, insert_before_first_section: bool = False, trailing_blank_line: bool = False) -> str:
    line_end = "\r\n" if "\r\n" in raw else "\n"
    content = line_end + content.rstrip("\r\n") + line_end * (2 if trailing_blank_line else 1)
    span = section_span(raw, heading)
    if span:
        return raw[:span[0]] + content + raw[span[1]:]
    if insert_before_first_section:
        first_section = H2_PATTERN.search(raw)
        if first_section:
            return raw[:first_section.start()] + heading + line_end + content + line_end + raw[first_section.start():]
    try:
        later_sections = SECTION_ORDER[SECTION_ORDER.index(heading) + 1:]
    except ValueError:
        later_sections = ()
    insert_at = next(
        (match.start() for candidate in later_sections if (match := re.search(rf"(?m)^{re.escape(candidate)}\r?$", raw))),
        None,
    )
    if insert_at is not None:
        separator = "" if trailing_blank_line else line_end
        return raw[:insert_at] + heading + line_end + content + separator + raw[insert_at:]
    separator = "" if raw.endswith(("\n", "\r")) else line_end
    return raw + separator + line_end + heading + line_end + content


def yaml_value(value: Any, line_end: str) -> str:
    if isinstance(value, list):
        return "".join(f"  - {yaml_value(item, line_end)}{line_end}" for item in value)
    if value is None:
        return ""
    serialized = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True, width=1000).strip()
    return serialized.split("\n...", 1)[0]


def safe_filename(value: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value).strip(". ") or "Person"


def field_span(document: PersonDocument, field: str) -> tuple[int, int] | None:
    yaml_text = document.raw[document.frontmatter_start:document.frontmatter_end]
    match = re.search(rf"(?m)^{re.escape(field)}:\s*.*(?:\r?\n|$)", yaml_text)
    if not match:
        return None
    end = match.end()
    while end < len(yaml_text):
        next_line = re.match(r"[ \t].*(?:\r?\n|$)", yaml_text[end:])
        if not next_line:
            break
        end += next_line.end()
    return document.frontmatter_start + match.start(), document.frontmatter_start + end


def replace_field(document: PersonDocument, field: str, value: Any) -> str:
    line_end = "\r\n" if "\r\n" in document.raw else "\n"
    if isinstance(value, list):
        replacement = f"{field}:{line_end}{yaml_value(value, line_end)}"
    else:
        replacement = f"{field}: {yaml_value(value, line_end)}{line_end}"
    span = field_span(document, field)
    if span:
        return document.raw[:span[0]] + replacement + document.raw[span[1]:]
    closing_start = document.raw.rfind("---", document.frontmatter_start, document.frontmatter_end)
    try:
        field_index = FRONTMATTER_FIELD_ORDER.index(field)
    except ValueError:
        return document.raw[:closing_start] + replacement + document.raw[closing_start:]
    later_fields = FRONTMATTER_FIELD_ORDER[field_index + 1:]
    insert_at = next(
        (span[0] for candidate in later_fields if (span := field_span(document, candidate))),
        None,
    )
    if insert_at is None:
        earlier_fields = FRONTMATTER_FIELD_ORDER[:field_index]
        previous_spans = [field_span(document, candidate) for candidate in earlier_fields]
        insert_at = next((span[1] for span in reversed(previous_spans) if span), closing_start)
    return document.raw[:insert_at] + replacement + document.raw[insert_at:]


def date_precision(value: str) -> int:
    return len(value) if DATE_PATTERN.fullmatch(value) else 0


def shared_month(value: str) -> str:
    return value[:7] if len(value) >= 7 else value


def date_as_day(value: str) -> dt.date | None:
    try:
        if len(value) == 4:
            return dt.date.fromisoformat(f"{value}-01-01")
        if len(value) == 7:
            return dt.date.fromisoformat(f"{value}-01")
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def source_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def normalized_name(person: PersonDocument) -> str:
    return re.sub(r"[^a-z]", "", person.name.casefold())


def position_blocks(content: str) -> list[str]:
    starts = list(re.finditer(r"(?m)^[*-] .*$", content))
    if not starts:
        return [content] if content.strip() else []
    prefix = content[:starts[0].start()]
    blocks = [prefix] if prefix.strip() else []
    blocks.extend(content[start.start(): starts[index + 1].start() if index + 1 < len(starts) else len(content)] for index, start in enumerate(starts))
    return blocks


def normalized_position_organization(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_value.casefold())


def load_organization_aliases(path: Path) -> dict[str, str]:
    """Map organization names and aliases to their canonical registry display name."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        logging.warning("Could not load organization aliases from %s: %s", path, error)
        return {}
    records = data.get("organizations", []) if isinstance(data, dict) else data
    if not isinstance(records, list):
        logging.warning("Ignoring organization aliases with unexpected structure: %s", path)
        return {}
    aliases: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        canonical = str(record.get("name") or record.get("organization") or "").strip()
        if not canonical:
            continue
        values = [record.get("name"), *(record.get("aliases") or [])]
        for value in values:
            key = normalized_position_organization(str(value or ""))
            if key:
                aliases[key] = canonical
    return aliases


def position_organization(block: str, aliases: dict[str, str] | None = None) -> str:
    first_line = block.splitlines()[0] if block else ""
    links = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]|\[([^\]]+)\]\([^)]*\)", first_line)
    links = [wikilink or markdown_link for wikilink, markdown_link in links]
    organization = normalized_position_organization(links[0]) if links else ""
    return normalized_position_organization((aliases or {}).get(organization, organization))


def normalize_position_organization_link(block: str, aliases: dict[str, str]) -> str:
    """Replace a recognized position organization link with its canonical Wikilink."""
    match = re.search(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]|\[([^\]]+)\]\([^)]*\)", block)
    if not match:
        return block
    organization = normalized_position_organization(match.group(1) or match.group(2))
    canonical = aliases.get(organization)
    if not canonical:
        return block
    return block[:match.start()] + f"[[{canonical}]]" + block[match.end():]


def replace_position_organization_link(block: str, source: str) -> str:
    pattern = r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]|\[([^\]]+)\]\([^)]*\)"
    target_match, source_match = re.search(pattern, block), re.search(pattern, source)
    if not target_match or not source_match:
        return block
    return block[:target_match.start()] + source_match.group(0) + block[target_match.end():]


def position_title(block: str) -> str:
    first_line = block.splitlines()[0] if block else ""
    title = re.split(r"\[\[[^\]]+\]\]|\[[^\]]+\]\([^)]*\)", first_line, maxsplit=1)[0]
    return normalized_position_organization(title)


def is_undated_education(block: str) -> bool:
    first_line = block.splitlines()[0] if block else ""
    return not position_dates(block) and bool(re.search(r"\b(?:b\.?sc|m\.?sc|bachelor|master|ph\.?d|diploma|certificate)\b", first_line, re.I))


def position_dates(block: str) -> list[str]:
    return DATE_PATTERN.findall(block.splitlines()[0] if block else "")


def dates_overlap(left: list[str], right: list[str]) -> bool:
    if not left or not right:
        return False
    left_start, left_end = left[0], left[-1] if len(left) > 1 else "9999-12-31"
    right_start, right_end = right[0], right[-1] if len(right) > 1 else "9999-12-31"
    return left_start[:7] <= right_end[:7] and right_start[:7] <= left_end[:7]


def has_description(block: str) -> bool:
    return any(line.lstrip().startswith(">") or line.strip().startswith("```") for line in block.splitlines()[1:])


def quoted_description(block: str) -> list[str]:
    return [line for line in block.splitlines()[1:] if line.lstrip().startswith(">")]


def description_word_count(block: str) -> int:
    return len(re.findall(r"\w+", "\n".join(block.splitlines()[1:])))


def replace_position_description(block: str, source: str) -> str:
    source_description = quoted_description(source)
    if not source_description:
        return block
    line_end = "\r\n" if "\r\n" in block else "\n"
    first_line = block.splitlines()[0] if block else ""
    description = line_end.join(f"  {line.lstrip()}" for line in source_description)
    return f"{first_line}{line_end}{line_end}{description}{line_end}"


def sort_position_blocks(blocks: list[str]) -> list[str]:
    dated_blocks = sorted(
        (block for block in blocks if position_dates(block)),
        key=lambda block: position_dates(block)[0],
    )
    dated_iterator = iter(dated_blocks)
    return [next(dated_iterator) if position_dates(block) else block for block in blocks]


def normalize_single_bullet_description(block: str) -> str:
    bullet_lines = list(re.finditer(r"(?m)^(?P<prefix>[ \t]*>)[ \t]*-[ \t]*(?P<text>.+)\r?$", block))
    return bullet_lines[0].group("prefix") + " " + bullet_lines[0].group("text") + block[bullet_lines[0].end():] if len(bullet_lines) == 1 else block


def deduplicate_position_blocks(blocks: list[str], aliases: dict[str, str]) -> list[str]:
    deduplicated: list[str] = []
    for block in blocks:
        normalized = normalize_position_organization_link(block, aliases)
        duplicate = any(
            existing.strip() == normalized.strip()
            or (
                position_title(existing) == position_title(normalized)
                and position_organization(existing, aliases)
                and position_organization(existing, aliases) == position_organization(normalized, aliases)
                and dates_overlap(position_dates(existing), position_dates(normalized))
            )
            for existing in deduplicated
        )
        if not duplicate:
            deduplicated.append(normalized)
    return deduplicated


class SyncStore:
    def __init__(self, root: Path, dry_run: bool):
        self.root, self.dry_run = root, dry_run
        self.matches = self._load("matches.json", {})
        self.decisions = self._load("field_decisions.json", {})
        self.pending = self._load("pending_review.json", [])

    def _load(self, name: str, default: Any) -> Any:
        path = self.root / name
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            logging.warning("Ignoring invalid state file %s: %s", path, error)
            return default

    def save(self, name: str, value: Any) -> None:
        if self.dry_run:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / name).write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")

    def decision(self, slug: str, field: str, other_value: Any) -> str | None:
        entry = self.decisions.get(f"{slug}:{field}")
        return entry.get("decision") if entry and entry.get("other_hash") == source_hash(other_value) else None

    def queue(self, item: dict[str, Any]) -> bool:
        key = (item["slug"], item["field"], item["other_hash"])
        if any((entry["slug"], entry["field"], entry["other_hash"]) == key for entry in self.pending):
            return False
        self.pending.append(item)
        return True


class PersonSynchronizer:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.organization_aliases = load_organization_aliases(Path(getattr(args, "organizations_config", DEFAULT_ORGANIZATIONS_PATH)))
        self.store = SyncStore(Path(args.state_dir), args.dry_run)
        self.changes: list[dict[str, Any]] = []
        self.reviews: list[dict[str, Any]] = []
        self.matches: list[dict[str, Any]] = []
        self.reused_decisions = 0

    def record_change(self, person: PersonDocument, field: str, old_value: Any, new_value: Any, action: str = "updated") -> None:
        if old_value == new_value:
            return
        timestamp = dt.datetime.now()
        self.changes.append({
            "date": timestamp.date().isoformat(),
            "time": timestamp.strftime("%H:%M:%S"),
            "slug": person.slug,
            "name": person.name,
            "path": str(person.path),
            "action": action,
            "field": field,
            "old_value": json.dumps(old_value, ensure_ascii=False, default=str),
            "new_value": json.dumps(new_value, ensure_ascii=False, default=str),
        })

    def backup_and_write(self, person: PersonDocument, updated: str) -> None:
        if updated == person.raw:
            return
        if self.args.dry_run:
            return
        updated_document = document_from_raw(person.path, updated)
        updated = replace_field(updated_document, "last_updated", dt.date.today())
        backup_root = Path(self.args.state_dir) / "backups" / dt.date.today().isoformat()
        backup_root.mkdir(parents=True, exist_ok=True)
        filename = f"{safe_filename(person.name)}.md"
        backup = backup_root / filename
        if backup.exists():
            filename = f"{safe_filename(person.name)} ({safe_filename(person.slug)}).md"
            backup = backup_root / filename
        if backup.exists():
            backup = backup_root / f"{backup.stem} {dt.datetime.now():%H%M%S}.md"
        shutil.copy2(person.path, backup)
        person.path.write_text(updated, encoding="utf-8", newline="")

    def repair_mojibake_in_people(self, people: list[PersonDocument]) -> None:
        for person in people:
            repaired = repair_mojibake(person.raw)
            if repaired != person.raw:
                self.record_change(person, "text_encoding", "mojibake", "utf-8", "repaired_encoding")
                self.backup_and_write(person, repaired)

    def normalize_markdown_in_people(self, people: list[PersonDocument]) -> None:
        for person in people:
            normalized = normalize_heading_spacing(person.raw)
            if normalized != person.raw:
                self.record_change(person, "heading_spacing", "inconsistent", "normalized", "normalized_markdown")
                self.backup_and_write(person, normalized)

    def conflict(self, person: PersonDocument, field: str, personal: Any, other: Any, kind: str = "contact_info") -> None:
        decision = self.store.decision(person.slug, field, other)
        if decision:
            self.reused_decisions += 1
            return
        item = {"slug": person.slug, "name": person.name, "path": str(person.path), "field": field, "type": kind, "personal": personal, "other": other, "other_hash": source_hash(other)}
        if self.store.queue(item):
            self.reviews.append(item)

    def merge_positions(self, person: PersonDocument, other: PersonDocument, raw: str) -> str:
        personal_content, other_content = section_content(raw, "## Positions"), section_content(other.raw, "## Positions")
        personal_blocks = deduplicate_position_blocks(position_blocks(personal_content), self.organization_aliases)
        other_blocks = [normalize_position_organization_link(block, self.organization_aliases) for block in position_blocks(other_content)]
        used: set[int] = set()
        for other_block in other_blocks:
            organization, other_dates = position_organization(other_block, self.organization_aliases), position_dates(other_block)
            other_title = position_title(other_block)
            matched_index = next(
                (
                    index for index, block in enumerate(personal_blocks)
                    if index not in used and (
                        organization and position_organization(block, self.organization_aliases) == organization and dates_overlap(position_dates(block), other_dates)
                        or is_undated_education(block) and is_undated_education(other_block) and position_title(block) == other_title
                    )
                ),
                None,
            )
            if matched_index is None:
                personal_blocks.append(other_block)
                continue
            used.add(matched_index)
            personal_block = personal_blocks[matched_index]
            personal_lines = personal_block.splitlines(keepends=True)
            other_lines = other_block.splitlines(keepends=True)
            personal_block = replace_position_organization_link(personal_block, other_block)
            personal_blocks[matched_index] = personal_block
            if (
                personal_lines
                and other_lines
                and re.search(r"(?:^|\s)#current\b", personal_lines[0], re.I)
                and len(other_dates) > 1
            ):
                personal_block = other_lines[0] + "".join(personal_lines[1:])
                personal_blocks[matched_index] = personal_block
            for personal_date, other_date in zip(position_dates(personal_block), other_dates):
                if shared_month(personal_date) != shared_month(other_date):
                    self.conflict(person, f"position:{organization}:date", personal_date, other_date, "position_date")
                elif date_precision(other_date) > date_precision(personal_date):
                    personal_block = personal_block.replace(personal_date, other_date, 1)
                    personal_blocks[matched_index] = personal_block
            if not has_description(personal_block) and quoted_description(other_block):
                line_end = "\r\n" if "\r\n" in raw else "\n"
                append = line_end + line_end.join(f"  {line.lstrip()}" for line in quoted_description(other_block)) + line_end
                personal_blocks[matched_index] = personal_block.rstrip("\r\n") + append
            elif quoted_description(other_block) and description_word_count(other_block) < description_word_count(personal_block):
                personal_blocks[matched_index] = replace_position_description(personal_block, other_block)
        merged_blocks = deduplicate_position_blocks(personal_blocks, self.organization_aliases)
        merged = "".join(block if block.endswith(("\n", "\r")) else block + "\n" for block in sort_position_blocks(merged_blocks))
        return replace_section(raw, "## Positions", merged, trailing_blank_line=True)

    def merge_pair(self, person: PersonDocument, other: PersonDocument) -> None:
        raw = person.raw
        personal_values = person.frontmatter
        other_values = other.frontmatter
        for field in ("skills", "organizations"):
            personal_items = list(personal_values.get(field) or [])
            merged_items = [*personal_items]
            for item in other_values.get(field) or []:
                if item not in merged_items:
                    merged_items.append(item)
            if merged_items != personal_items:
                raw = replace_field(document_from_raw(person.path, raw), field, merged_items)
                self.record_change(person, field, personal_items, merged_items)
        for field in ("first_name", "last_name"):
            if not personal_values.get(field) and other_values.get(field):
                old_value = personal_values.get(field)
                raw = replace_field(document_from_raw(person.path, raw), field, other_values[field])
                self.record_change(person, field, old_value, other_values[field])
        for field in CONTACT_FIELDS:
            personal, source = personal_values.get(field), other_values.get(field)
            if source and not personal:
                raw = replace_field(document_from_raw(person.path, raw), field, source)
                self.record_change(person, field, personal, source)
            elif source and personal != source:
                decision = self.store.decision(person.slug, field, source)
                if decision == "accepted_other":
                    raw = replace_field(document_from_raw(person.path, raw), field, source)
                    self.record_change(person, field, personal, source, "accepted_decision")
                elif decision:
                    self.reused_decisions += 1
                else:
                    self.conflict(person, field, personal, source)
        birthday, source_birthday = str(personal_values.get("birthday") or ""), str(other_values.get("birthday") or "")
        if birthday and source_birthday and shared_month(birthday) != shared_month(source_birthday):
            self.conflict(person, "birthday", birthday, source_birthday, "birthday_mismatch")
        profile_url = linkedin_profile_url(other_values)
        references = section_content(raw, "## References")
        if profile_url and profile_url not in references:
            reference_number = max((int(value) for value in re.findall(r"(?m)^\s*(\d+)\.\s", references)), default=0) + 1
            references = f"{references.rstrip()}\n\n" if references.strip() else ""
            references += f"{reference_number}. [LinkedIn]({profile_url})"
            raw = replace_section(raw, "## References", references, trailing_blank_line=True)
            self.record_change(person, "References", section_content(person.raw, "## References"), references)
        personal_bio, other_bio = section_content(raw, "## Bio").strip(), section_content(other.raw, "## Bio").strip()
        if other_bio:
            if not personal_bio or difflib.SequenceMatcher(None, personal_bio, other_bio).ratio() >= self.args.bio_similarity:
                raw = replace_section(raw, "## Bio", other_bio, insert_before_first_section=True)
            elif other_bio not in personal_bio:
                raw = replace_section(raw, "## Bio", f"{personal_bio}\n>\n{other_bio}")
            self.record_change(person, "Bio", personal_bio, section_content(raw, "## Bio").strip())
        old_positions = section_content(raw, "## Positions")
        raw = self.merge_positions(person, other, raw)
        self.record_change(person, "Positions", old_positions, section_content(raw, "## Positions"))
        self.backup_and_write(person, raw)

    def create_person(self, other: PersonDocument, existing_slugs: set[str]) -> None:
        base = re.sub(r"[^a-z0-9]+", "-", other.name.casefold()).strip("-") or "person"
        slug, sequence = base, 2
        while slug in existing_slugs:
            slug, sequence = f"{base}-{sequence}", sequence + 1
        existing_slugs.add(slug)
        folder, target = Path(self.args.existing) / slug, None
        target = folder / f"{safe_filename(other.name)}.md"
        raw = replace_field(other, "slug", slug)
        if not self.args.dry_run:
            folder.mkdir(parents=True, exist_ok=True)
            target.write_text(raw, encoding="utf-8", newline="")
        self.store.matches[slug] = {"other_path": str(other.path), "method": "created", "updated_at": dt.datetime.now().isoformat()}
        timestamp = dt.datetime.now()
        self.changes.append({"date": timestamp.date().isoformat(), "time": timestamp.strftime("%H:%M:%S"), "slug": slug, "name": other.name, "path": str(target), "action": "created_file", "field": "file", "old_value": "", "new_value": str(other.path)})

    def match_and_sync(self, personal: list[PersonDocument], other: list[PersonDocument], blocked_existing_slugs: set[str] | None = None, known_existing_slugs: set[str] | None = None) -> None:
        original_personal = personal
        personal = [document_from_raw(person.path, repair_mojibake(person.raw)) for person in personal]
        other = [document_from_raw(person.path, repair_mojibake(person.raw)) for person in other]
        by_slug, by_linkedin = {person.slug: person for person in personal}, {str(person.frontmatter.get("linkedin_id")): person for person in personal if person.frontmatter.get("linkedin_id")}
        persisted_paths = {
            str(Path(entry.get("other_path", "")).resolve()): by_slug[slug]
            for slug, entry in self.store.matches.items()
            if slug in by_slug and entry.get("other_path")
        }
        existing_slugs = known_existing_slugs or set(by_slug)
        blocked_existing_slugs = blocked_existing_slugs or set()
        matched_personal: set[str] = set()
        for source in other:
            if source.slug and source.slug in blocked_existing_slugs:
                self.matches.append({"slug": source.slug, "other": str(source.path), "status": "skipped_slug_conflict"})
                continue
            match, method = persisted_paths.get(str(source.path.resolve())), "persisted"
            if not match:
                match, method = by_slug.get(source.slug), "slug"
            if not match and source.frontmatter.get("linkedin_id"):
                match, method = by_linkedin.get(str(source.frontmatter["linkedin_id"])), "linkedin_id"
            if not match:
                candidates = [(difflib.SequenceMatcher(None, normalized_name(person), normalized_name(source)).ratio(), person) for person in personal if person.slug not in matched_personal]
                score, candidate = max(candidates, default=(0.0, None), key=lambda item: item[0])
                if score >= self.args.auto_match_threshold:
                    match, method = candidate, "name_similarity"
                elif score >= self.args.review_match_threshold:
                    self.conflict(candidate, "identity", candidate.name, source.name, "ambiguous_match")
                    self.matches.append({"other": str(source.path), "status": "needs_review", "score": score})
                    continue
            if match:
                matched_personal.add(match.slug)
                previous = self.store.matches.get(match.slug, {})
                previous_id = previous.get("other_linkedin_id")
                current_id = source.frontmatter.get("linkedin_id")
                if previous_id and current_id and previous_id != current_id:
                    logging.warning("LinkedIn ID changed for linked person %s: %s -> %s", match.slug, previous_id, current_id)
                    self.matches.append({"slug": match.slug, "other": str(source.path), "status": "linkedin_id_changed", "method": method})
                self.store.matches[match.slug] = {"other_path": str(source.path), "other_linkedin_id": current_id, "method": method, "updated_at": dt.datetime.now().isoformat()}
                self.matches.append({"slug": match.slug, "other": str(source.path), "status": "matched", "method": method})
                self.merge_pair(match, source)
            else:
                self.create_person(source, existing_slugs)
                self.matches.append({"other": str(source.path), "status": "other_only_created"})
        for person in personal:
            if person.slug not in matched_personal:
                original = next(original for original in original_personal if original.path == person.path)
                self.backup_and_write(original, person.raw)
                self.matches.append({"slug": person.slug, "status": "personal_only"})

    def normalize_positions(self, people: list[PersonDocument]) -> None:
        pattern = re.compile(r"(?m)^(?P<bullet>[*-] [^\r\n]+\r?\n)(?P<blank>\r?\n)?[ \t]*```\r?\n(?P<body>.*?)[ \t]*```(?P<end>\r?\n|$)", re.S)
        for person in people:
            def convert(match: re.Match[str]) -> str:
                line_end = "\r\n" if "\r\n" in match.group(0) else "\n"
                paragraphs: list[str] = []
                lines: list[str] = []
                for line in match.group("body").splitlines():
                    text = line.strip()
                    if text:
                        lines.append(text)
                    elif lines:
                        paragraphs.append(" ".join(lines))
                        lines = []
                if lines:
                    paragraphs.append(" ".join(lines))
                if len(paragraphs) == 1:
                    quoted = f"  > {paragraphs[0]}{line_end}"
                else:
                    quoted = "".join(f"  > - {paragraph}{line_end}" for paragraph in paragraphs)
                return match.group("bullet") + (match.group("blank") or line_end) + quoted
            positions = section_content(person.raw, "## Positions")
            normalized = pattern.sub(convert, positions)
            blocks = [normalize_single_bullet_description(block) for block in position_blocks(normalized)]
            ordered = "".join(block if block.endswith(("\n", "\r")) else block + "\n" for block in sort_position_blocks(blocks))
            updated = replace_section(person.raw, "## Positions", ordered, trailing_blank_line=True) if positions else person.raw
            self.record_change(person, "Positions", positions, section_content(updated, "## Positions"), "normalized_positions")
            self.backup_and_write(person, updated)

    def reconnect_rows(self, people: list[PersonDocument]) -> list[dict[str, Any]]:
        cutoff = dt.date.today() - dt.timedelta(days=self.args.lookback_days)
        rows: list[dict[str, Any]] = []
        for original in people:
            person = read_document(original.path)
            if not person:
                continue
            interaction_dates = [dt.date.fromisoformat(value) for value in WIKILINK_DATE_PATTERN.findall(person.raw)]
            interaction_dates.extend(dt.date.fromisoformat(value) for value in INLINE_DATE_PATTERN.findall(section_content(person.raw, "## Notes")))
            for block in position_blocks(section_content(person.raw, "## Positions")):
                dates = position_dates(block)
                if not dates:
                    continue
                change_date = date_as_day(dates[0])
                if not change_date:
                    continue
                if change_date < cutoff:
                    continue
                title = block.splitlines()[0][2:] if block.splitlines() else ""
                organization = position_organization(block, self.organization_aliases)
                change_type = "education" if re.search(r"\b(degree|university|college|school|certificate|education)\b", title, re.I) else "job"
                last_interaction = max((value for value in interaction_dates if value >= change_date), default=None)
                if last_interaction:
                    continue
                rows.append({"slug": person.slug, "name": person.name, "change_type": change_type, "organization_or_institution": organization, "title_or_degree": title, "change_date": change_date.isoformat(), "last_interaction_date": "", "days_since_change": (dt.date.today() - change_date).days})
        return sorted(rows, key=lambda row: row["days_since_change"], reverse=True)

    def write_reports(self, people: list[PersonDocument], slug_conflicts: list[dict[str, str]] | None = None) -> None:
        state_root = Path(self.args.state_dir)
        state_root.mkdir(parents=True, exist_ok=True)
        changes_report = "changes_proposed.csv" if self.args.dry_run else "changes_applied.csv"
        for name, rows in (("match_report.csv", self.matches), ("manual_review.csv", self.reviews), (changes_report, self.changes), ("reconnect_with.csv", self.reconnect_rows(people))):
            keys = CHANGE_REPORT_FIELDS if name == changes_report else sorted({key for row in rows for key in row}) or ["status"]
            report_path = state_root / name
            if name == "changes_applied.csv" and report_path.exists():
                with report_path.open(newline="", encoding="utf-8") as file:
                    existing_rows = list(csv.DictReader(file))
                rows = [*existing_rows, *rows]
            with report_path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=keys)
                writer.writeheader()
                writer.writerows(rows)
        if slug_conflicts:
            with (state_root / "slug_conflicts.csv").open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=("set", "slug", "path"))
                writer.writeheader()
                writer.writerows(slug_conflicts)
        if self.args.dry_run:
            return
        self.store.save("matches.json", self.store.matches)
        self.store.save("pending_review.json", self.store.pending)
        history_path = state_root / "sync_history.json"
        history = self.store._load("sync_history.json", [])
        history.append({"timestamp": dt.datetime.now().isoformat(), "dry_run": self.args.dry_run, "people_processed": len(people), "changes": len(self.changes), "new_reviews": len(self.reviews), "reused_decisions": self.reused_decisions})
        self.store.save("sync_history.json", history)


def read_review_command(prompt: str) -> str:
    print(prompt, end="", flush=True)
    if not sys.stdin.isatty():
        return input().strip().lower()[:1]
    if os.name == "nt":
        import msvcrt
        command = msvcrt.getwch()
    else:
        import termios
        import tty
        descriptor = sys.stdin.fileno()
        saved = termios.tcgetattr(descriptor)
        try:
            tty.setraw(descriptor)
            command = sys.stdin.read(1)
        finally:
            termios.tcsetattr(descriptor, termios.TCSADRAIN, saved)
    print(command)
    return command.lower()


def review_pending(args: argparse.Namespace, slugs: set[str] | None = None) -> int:
    store = SyncStore(Path(args.state_dir), False)
    pending = [item for item in store.pending if slugs is None or item["slug"] in slugs]
    untouched = [item for item in store.pending if slugs is not None and item["slug"] not in slugs]
    remaining: list[dict[str, Any]] = []
    for index, item in enumerate(pending, 1):
        print(f"\nReviewing {index} of {len(pending)} - {item['name']} ({item['slug']}) - {item['field']}")
        print(f"\033[31m- {item.get('personal', '')}\033[0m\n\033[32m+ {item.get('other', '')}\033[0m")
        command = read_review_command("[a]ccept  [r]eject  [i]gnore  [e]dit  [q]uit: ")
        if command == "q":
            remaining.extend(pending[index - 1:])
            break
        if command == "e":
            editor = args.editor or os.environ.get("EDITOR") or os.environ.get("VISUAL") or "code"
            subprocess.run([*shlex.split(editor), item["path"]], check=False)
            edited = read_document(Path(item["path"]))
            field = item["field"]
            resolved = edited and field in (*CONTACT_FIELDS, "birthday") and edited.frontmatter.get(field) == item["other"]
            if not resolved:
                remaining.append(item)
        elif command in ("a", "r"):
            store.decisions[f"{item['slug']}:{item['field']}"] = {"decision": "accepted_other" if command == "a" else "kept_personal", "other_hash": item["other_hash"], "timestamp": dt.datetime.now().isoformat()}
            store.save("field_decisions.json", store.decisions)
        else:
            remaining.append(item)
    store.pending = [*untouched, *remaining]
    store.save("pending_review.json", store.pending)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synchronize Person Markdown notes while preserving unrelated text.")
    parser.add_argument("-e", "--existing", help="Existing Person-file folder, modified in place")
    parser.add_argument("-i", "--incoming", help="Read-only Person-file folder to merge from")
    parser.add_argument("-t", "--state-dir", default=DEFAULT_STATE_DIR)
    parser.add_argument("--organizations-config", default=str(DEFAULT_ORGANIZATIONS_PATH), help="Organization registry used to resolve position aliases")
    parser.add_argument("-c", "--config", help="Optional JSON configuration")
    parser.add_argument("--editor")
    parser.add_argument("-d", "--debug", action="store_true")
    parser.add_argument("-n", "--dry-run", action="store_true")
    parser.add_argument("-x", "--max", type=int)
    parser.add_argument("-g", "--tag", action="append")
    parser.add_argument("--linkedin-id", action="append")
    parser.add_argument("-p", "--slug", action="append")
    parser.add_argument("-m", "--normalize-positions", action="store_true")
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--auto-match-threshold", type=float, default=0.96)
    parser.add_argument("--review-match-threshold", type=float, default=0.80)
    parser.add_argument("--bio-similarity", type=float, default=0.70)
    parser.add_argument("-w", "--lookback-days", type=int, default=365)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING, format="%(levelname)s: %(message)s")
    if args.review:
        return review_pending(args)
    if not args.existing:
        build_parser().error("--existing is required unless --review is used")
    if args.config:
        with Path(args.config).open(encoding="utf-8") as file:
            for key, value in json.load(file).items():
                if hasattr(args, key):
                    setattr(args, key, value)
    existing_root = Path(args.existing).resolve()
    incoming_root = Path(args.incoming).resolve() if args.incoming else None
    state_root = Path(args.state_dir).resolve()

    def discover_existing_people() -> list[PersonDocument]:
        people = discover_people(existing_root)
        return [
            person for person in people
            if not (
                (incoming_root and incoming_root.is_relative_to(existing_root) and person.path.resolve().is_relative_to(incoming_root))
                or (state_root.is_relative_to(existing_root) and person.path.resolve().is_relative_to(state_root))
                or person.path.resolve().relative_to(existing_root).parts[0].casefold().startswith("people-")
            )
        ]

    discovered_existing = discover_existing_people()
    personal = scope_people(discovered_existing, args)
    duplicates = duplicate_slugs(personal)
    all_existing_duplicates = duplicate_slugs(discovered_existing)
    slug_conflicts = [{"set": "personal", "slug": slug, "path": str(person.path)} for slug, people in duplicates.items() for person in people]
    if duplicates:
        logging.error("Skipping duplicate personal slugs: %s", ", ".join(duplicates))
        personal = [person for person in personal if person.slug not in duplicates]
    synchronizer = PersonSynchronizer(args)
    synchronizer.repair_mojibake_in_people(personal)
    if not args.dry_run:
        discovered_existing = discover_existing_people()
        personal = scope_people(discovered_existing, args)
    synchronizer.normalize_markdown_in_people(personal)
    if not args.dry_run:
        discovered_existing = discover_existing_people()
        personal = scope_people(discovered_existing, args)
    if args.incoming:
        other = discover_people(Path(args.incoming))
        requested_tags = split_csv_values(args.tag)
        requested_slugs = split_csv_values(args.slug)
        requested_linkedin_ids = split_csv_values(args.linkedin_id)
        if requested_slugs or requested_linkedin_ids:
            other = [person for person in other if person.slug in requested_slugs or str(person.frontmatter.get("linkedin_id", "")) in requested_linkedin_ids]
        elif requested_tags:
            other = [person for person in other if tag_values(person) & requested_tags]
        duplicate_other = duplicate_slugs(other)
        slug_conflicts.extend({"set": "other", "slug": slug, "path": str(person.path)} for slug, people in duplicate_other.items() for person in people)
        if duplicate_other:
            logging.error("Skipping duplicate source slugs: %s", ", ".join(duplicate_other))
            other = [person for person in other if person.slug not in duplicate_other]
        synchronizer.match_and_sync(personal, other, set(all_existing_duplicates), {person.slug for person in discovered_existing if person.slug})
        if args.normalize_positions and not args.dry_run:
            personal = scope_people(discover_existing_people(), args)
    elif not args.normalize_positions:
        build_parser().error("--incoming is required unless --normalize-positions or --review is used")
    if args.normalize_positions:
        synchronizer.normalize_positions(personal)
    synchronizer.write_reports(personal, slug_conflicts)
    print(f"Processed {len(personal)} people; {len(synchronizer.changes)} changes; {len(synchronizer.reviews)} new reviews; {synchronizer.reused_decisions} reused decisions.")
    pending_slugs = {item["slug"] for item in synchronizer.store.pending} & {person.slug for person in personal}
    if pending_slugs and not args.dry_run:
        return review_pending(args, pending_slugs)
    return 0


if __name__ == "__main__":
    sys.exit(main())