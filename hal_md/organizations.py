"""Shared organization registry, alias resolution, and compound-name matching."""

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


ORGANIZATIONS_FILE_NAME = "organizations.json"

_CONNECTOR_RE = re.compile(r"^(?:['\u2019]s(?=\s|$)\s*|(?:,|&|/|\+|and|at)\s+)", re.IGNORECASE)
_BOUNDARY_CHARS = ",&/'\u2019"


@dataclass(frozen=True)
class OrganizationRecord:
    name: str
    slug: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    url: str = ""
    linkedin_id: str = ""
    x_id: str = ""
    city: str = ""
    province: str = ""
    country: str = ""
    description: str = ""


class OrganizationsConfig:
    """Resolve a registry's display names/aliases and optionally persist unknown names."""

    def __init__(self, records=None, alias_to_name=None, path: Path | None = None, paths=None, raw_data=None, writable: bool = True):
        self.records = records or []
        self.alias_to_name = build_alias_index(self.records) if alias_to_name is None else alias_to_name
        self.path = path
        self.paths = list(paths) if paths is not None else ([path] if path else [])
        self.raw_data = raw_data if isinstance(raw_data, list) else []
        self.writable = writable
        self.prompt_for_unknown = False
        self._resolved_unknowns: dict[str, str] = {}

    @classmethod
    def load_optional(cls, config_folder: Path, logger=None):
        path = Path(config_folder) / ORGANIZATIONS_FILE_NAME
        if not path.exists() or not path.is_file():
            return cls(path=path)

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            if logger:
                logger.warn(f"could not parse {path}: {exc}")
            else:
                logging.getLogger(__name__).warning("could not parse %s: %s", path, exc)
            return cls(path=path, writable=False)

        records = parse_organization_records(raw)
        if not isinstance(raw, list):
            if logger:
                logger.warn(f"{path} must contain a JSON list; preserving the file without updates")
            else:
                logging.getLogger(__name__).warning("%s must contain a JSON list; preserving the file without updates", path)
            return cls(records=records, path=path, paths=[path], writable=False)
        if logger:
            logger.info(f"loaded {len(records)} organization record(s) from {path}")
        return cls(records=records, path=path, paths=[path], raw_data=raw)

    def split(self, raw_name: str) -> list[str]:
        return split_compound_organization(raw_name, self.alias_to_name)

    def slug_for_name(self, name: str) -> str:
        canonical_name = self.alias_to_name.get(normalize_organization_key(name), name)
        normalized_name = normalize_organization_key(canonical_name)
        for record in self.records:
            if normalize_organization_key(record.name) == normalized_name:
                return record.slug
        return ""

    def slug_for_value(self, value: str) -> str:
        canonical_slug = self.slug_for_name(value)
        if canonical_slug:
            return canonical_slug
        slug = _slug_key(value)
        for record in self.records:
            if slug and slug in {_slug_key(name) for name in (record.slug, record.name, *record.aliases)}:
                return record.slug
        return ""

    def resolve_unknown(self, raw_name: str) -> str:
        raw_name = " ".join(str(raw_name or "").split())
        key = normalize_organization_key(raw_name)
        if not raw_name:
            return raw_name
        if key in self.alias_to_name:
            return self.alias_to_name[key]
        if not self.writable or not self.path:
            return raw_name
        if key in self._resolved_unknowns:
            return self._resolved_unknowns[key]

        canonical_name = raw_name
        if self.prompt_for_unknown:
            while True:
                entered_name = input(f"Unknown organization '{raw_name}'. Canonical name (Enter to use shown, '-' to skip): ").strip()
                if entered_name == "-":
                    self._resolved_unknowns[key] = raw_name
                    return raw_name
                canonical_name = entered_name or raw_name
                if normalize_organization_key(canonical_name) in self.alias_to_name or _slug_key(canonical_name):
                    break
                logging.getLogger(__name__).warning(
                    "Cannot generate an organization slug from %r. Enter a different name or '-' to skip.",
                    canonical_name,
                )

        canonical_key = normalize_organization_key(canonical_name)
        existing_name = self.alias_to_name.get(canonical_key)
        if existing_name:
            canonical_name = existing_name
        else:
            base_slug = _slug_key(canonical_name)
            if not base_slug:
                raise ValueError(f"Cannot generate an organization slug from {canonical_name!r}")
            existing_slugs = {record.slug for record in self.records}
            slug = base_slug
            suffix = 2
            while slug in existing_slugs:
                slug = f"{base_slug}-{suffix}"
                suffix += 1
            self.raw_data.append({"name": canonical_name, "slug": slug, "people": []})

        if normalize_organization_key(canonical_name) != key:
            self._append_alias(canonical_name, raw_name)
        self._refresh()
        self.save()
        self._resolved_unknowns[key] = canonical_name
        return canonical_name

    def link_person(self, person_slug: str, organizations: list[str]) -> bool:
        """Persist a person's membership in known organizations without creating records."""
        if not person_slug.strip():
            raise ValueError("A person slug is required to link organizations")
        if not self.writable or self.path is None:
            raise ValueError("Cannot link a person without a writable organization registry")

        canonical_names = {
            self.alias_to_name.get(normalize_organization_key(value))
            for value in organizations
        }
        canonical_names.discard(None)
        slugs = {self.slug_for_value(value) for value in organizations}
        slugs.discard("")
        matches = [
            item for item in self.raw_data
            if isinstance(item, dict) and (
                (item.get("slug") and item.get("slug") in slugs)
                or (item.get("name") or item.get("organization")) in canonical_names
            )
        ]
        for item in matches:
            if not isinstance(item.get("people", []), list):
                raise ValueError(f"Organization {item.get('name')!r} has an invalid people list")

        changed = False
        for item in matches:
            people = item.setdefault("people", [])
            if person_slug not in people:
                people.append(person_slug)
                people.sort(key=lambda value: str(value).lower())
                changed = True
        if changed:
            self.save()
        return changed

    def _append_alias(self, canonical_name: str, alias: str) -> None:
        canonical_key = normalize_organization_key(canonical_name)
        for item in self.raw_data:
            if not isinstance(item, dict):
                continue
            if normalize_organization_key(item.get("name") or item.get("organization")) != canonical_key:
                continue
            aliases = list(parse_aliases(item.get("aliases") or item.get("aliases:") or []))
            if normalize_organization_key(alias) not in {normalize_organization_key(value) for value in aliases}:
                aliases.append(alias)
            item["aliases"] = aliases
            item.pop("aliases:", None)
            return

    def _refresh(self) -> None:
        self.records = parse_organization_records(self.raw_data)
        self.alias_to_name = build_alias_index(self.records)

    def save(self) -> None:
        if not self.writable or self.path is None:
            raise ValueError("Cannot save an organization registry without a writable path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.raw_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def normalize_organization_key(value: str) -> str:
    """Match case/whitespace and canonically equivalent Unicode, retaining accents."""
    return unicodedata.normalize("NFC", " ".join(str(value or "").split())).lower()


def _slug_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize_organization_key(value)).strip("-")


def parse_organization_records(raw) -> list[OrganizationRecord]:
    if isinstance(raw, dict):
        raw = raw.get("organizations", raw)
    if not isinstance(raw, list):
        return []

    records = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("organization") or "").strip()
        if not name:
            continue
        aliases = parse_aliases(item.get("aliases") or item.get("aliases:") or [])
        records.append(
            OrganizationRecord(
                name=name,
                slug=str(item.get("slug") or "").strip(),
                aliases=aliases,
                url=str(item.get("url") or "").strip(),
                linkedin_id=str(item.get("linkedin_id") or "").strip(),
                x_id=str(item.get("x_id") or "").strip(),
                city=str(item.get("city") or "").strip(),
                province=str(item.get("province") or "").strip(),
                country=str(item.get("country") or "").strip(),
                description=str(item.get("description") or "").strip(),
            )
        )
    return records


def parse_aliases(raw_aliases) -> tuple[str, ...]:
    if isinstance(raw_aliases, str):
        raw_aliases = raw_aliases.split(";")
    elif not isinstance(raw_aliases, list):
        raw_aliases = []
    return tuple(str(alias).strip() for alias in raw_aliases if str(alias or "").strip())


def build_alias_index(records) -> dict[str, str]:
    index = {}
    for record in records:
        for name in (record.name, *record.aliases):
            key = normalize_organization_key(name)
            if key:
                index[key] = record.name
    return index


def _strip_leading_connector(text: str) -> str:
    stripped = text.strip(" ,")
    match = _CONNECTOR_RE.match(stripped)
    if match:
        stripped = stripped[match.end():].strip()
    return stripped


def _split_parent_university_school(text: str, normalized: str, alias_to_name: dict) -> list:
    for alias in sorted(alias_to_name, key=len, reverse=True):
        if not alias.startswith(("school of ", "faculty of ")):
            continue
        if not normalized.endswith(f" {alias}"):
            continue
        parent = text[: -len(alias)].strip()
        parent_canonical = alias_to_name.get(normalize_organization_key(parent))
        if parent_canonical:
            return [parent_canonical]
    return []


def split_compound_organization(raw_name: str, alias_to_name: dict) -> list[str]:
    original_text = " ".join(str(raw_name or "").split())
    text = unicodedata.normalize("NFC", original_text)
    if not text:
        return []
    if not alias_to_name:
        return [original_text]

    normalized = normalize_organization_key(text)
    canonical = alias_to_name.get(normalized)
    if canonical:
        return [canonical]

    school_split = _split_parent_university_school(text, normalized, alias_to_name)
    if school_split:
        return school_split

    for alias in sorted(alias_to_name, key=len, reverse=True):
        if not alias or len(alias) >= len(normalized) or not normalized.startswith(alias):
            continue
        boundary = text[len(alias):]
        if boundary and not boundary[0].isspace() and boundary[0] not in _BOUNDARY_CHARS:
            continue
        stripped_boundary = boundary.lstrip()
        if not (
            stripped_boundary.startswith((",", "&", "/", "+"))
            or _CONNECTOR_RE.match(stripped_boundary)
        ):
            continue
        remainder = _strip_leading_connector(boundary)
        if remainder and remainder != text:
            return [alias_to_name[alias], *split_compound_organization(remainder, alias_to_name)]

    return [original_text]
