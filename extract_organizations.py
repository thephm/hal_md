#!/usr/bin/env python3
"""
build_organizations_json.py

Part of the hal_md toolset (https://github.com/thephm/hal_md).

Walks a folder and its subfolders (-s / --source) looking for Person
markdown files (i.e. files whose frontmatter `tags` includes `person`
and whose filename is NOT a dated interaction file like `2024-03-24.md`)
and builds/updates an `organizations.json` file (-c / --config) using:

  1. the `organizations` frontmatter field on the Person file, and
  2. the `## Positions` section in the body, where each bullet is expected
     to look like:

         - Job Title, [[Organization Name]]

     The job title (everything before the first comma) is ignored. The
     organization name is taken from the wikilink(s) found after the
     comma (falling back to plain text if there's no wikilink).

For every organization name found, the script first checks
organizations.json to see if it already exists -- matching against each
record's `organization` name, its `slug`, and its `aliases` -- before
creating a new record. New records get a generated `slug`:

  - the organization name has common legal-entity suffixes stripped
    (Inc., LLC, Ltd., LLB, etc. -- see LEGAL_SUFFIXES below)
  - the remaining name is lowercased
  - runs of whitespace/punctuation become a single hyphen

The full/original form of the name (including any legal suffix) is kept
as an alias on the new record so the corp/inc/ltd form of the name still
resolves back to the exact same record next time.

Assumptions (this repo doesn't currently publish a single canonical
slugify()/dedup helper, so these mirror the conventions used elsewhere
in hal_md, e.g. create_people_json.py and templates/Organization.md):

  - organizations.json is either a plain JSON list of organization
    records, or a dict of the form {"organizations": [...]}. Either is
    read and re-written in the same shape it was found in. If the file
    doesn't exist yet, a plain list is created.
  - Each organization record follows templates/Organization.md's
    frontmatter fields: organization, slug, aliases, url, email, phone,
    linkedin_id, x_id, city, province, country.
  - The Person frontmatter `organizations` field may contain either
    organization slugs (if you've already linked to existing
    Organization.md files) or plain organization names -- both are
    checked against organizations.json before anything new is created.

Requires PyYAML:
    pip install pyyaml

Usage:
    python3 build_organizations_json.py -s /path/to/vault -c /path/to/config
    python3 build_organizations_json.py -s /path/to/vault -c /path/to/config -d
    python3 build_organizations_json.py -s /path/to/vault -c /path/to/config -n
    python3 build_organizations_json.py -s /path/to/vault -c /path/to/config -v
    python3 build_organizations_json.py -s /path/to/vault -c /path/to/config -x 100

Options:
    -s, --source    Folder to recursively scan for Person markdown files (required)
    -c, --config    Folder containing (or to contain) organizations.json (required)
    -d, --debug     Print extra info as files/bullets/aliases are processed
    -v, --verbose   Print folders and files as they are scanned
    -x, --max       Maximum number of person markdown files to process
    -n, --dry-run   Don't write organizations.json, just report what would change
"""

import os
import re
import sys
import json
import argparse
import unicodedata

import yaml

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ORGANIZATIONS_FILENAME = 'organizations.json'
DEFAULT_CONFIG_DIR = os.environ.get(
    'HAL_MD_CONFIG_DIR',
    (r'C:\data\dev-output\config' if os.name == 'nt' else '/mnt/c/data/dev-output/config'),
)
MAX_ORGANIZATION_NAME_WORDS = 10

CANONICAL_ORGANIZATION_NAMES = {
    'school of continuing studies': 'McGill University',
    'wheelabrator canada': 'Wheelabrator',
    'wheelabrator group': 'Wheelabrator',
}
CANONICAL_ORGANIZATION_ALIASES = {
    'wheelabrator': ('Wheelabrator Group', 'Wheelabrator Canada'),
}

IGNORED_ORGANIZATION_NAMES = {
    'ignore',
    'none',
    'tbd',
    'undisclosed',
    'i&it corporate systems',
    'i&it cyber security',
    'i&it data & automation',
    'i&it development & delivery',
    'i&it end user computing',
    'i&it field support services',
    'i&it foundational technology & infrastructure',
    'i&it infrastructure support',
    'i&it product operations',
    'i&it security',
    'i&it security architecture',
    'i&it systems architecture & information security',
    'health & wellness',
    'it service desk & service management',
    'it service management',
    'special projects & decentralized engineering',
}

MOJIBAKE_REPLACEMENTS = {
    '├╝': 'ü',
    '├ë': 'é',
    '├â': 'à',
    '├®': 'î',
    '├┤': 'ô',
    '├ç': 'ç',
    '├ï': 'ï',
    '├ª': 'è',
}

# Legal-entity suffixes to strip off the end of an organization name before
# generating its slug (and before using it as the canonical `organization`
# name). Matched case-insensitively, with or without a trailing period.
# Trim this list down if you don't want e.g. "Corp"/"Co" treated as a
# stripped suffix -- the user only explicitly asked for LLB, LLC, Ltd., Inc.
LEGAL_SUFFIXES = [
    "incorporated",
    "inc",
    "llc",
    "l.l.c",
    "llp",
    "l.l.p",
    "lp",
    "l.p",
    "ltd",
    "llb",
    "corp",
    "corporation",
    "co",
    "plc",
    "gmbh",
    "limited",
]

DATE_FILENAME_RE = re.compile(r'^\d{4}-\d{2}-\d{2}(?:[^\\/]*)\.md$', re.IGNORECASE)
WIKILINK_RE = re.compile(r'\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]')
FULL_WIKILINK_RE = re.compile(r'^\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]$')
POSITIONS_HEADING_RE = re.compile(r'^\s{0,3}#{1,6}\s*Positions\s*$', re.IGNORECASE)
HEADING_RE = re.compile(r'^\s{0,3}#{1,6}\s')
POSITION_DATE_RE = re.compile(
    r'^\d{4}(?:-\d{2})?(?:\s+to\s+\d{4}(?:-\d{2})?)?(?:\s+#\w+)?$',
    re.IGNORECASE,
)
WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'&./()-]*")
SLUG_LIKE_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)+$')
SELF_EMPLOYED_TRAILING_RE = re.compile(r'\s*\(\s*self[\s-]*employed\s*\)\s*$', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Markdown / frontmatter helpers
# ---------------------------------------------------------------------------

def read_markdown(filepath):
    """
    Read a markdown file and split it into (frontmatter_dict, body_lines).
    Returns (None, lines) if there's no valid frontmatter block.
    """
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    if not lines or lines[0].strip() != '---':
        return None, lines

    end_index = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == '---':
            end_index = i
            break

    if end_index is None:
        return None, lines

    yaml_text = ''.join(lines[1:end_index])
    body_lines = lines[end_index + 1:]

    try:
        frontmatter = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        print(f"Error parsing YAML in {filepath}: {e}")
        return None, body_lines

    if not isinstance(frontmatter, dict):
        return None, body_lines

    return frontmatter, body_lines


def is_date_filename(filename):
    """True if filename looks like a dated interaction file, e.g. 2024-03-24.md"""
    return bool(DATE_FILENAME_RE.match(filename))


def get_tags(frontmatter):
    """Normalize the `tags` frontmatter field to a list of lowercase strings."""
    tags = frontmatter.get('tags')
    if tags is None:
        return []
    if isinstance(tags, str):
        tags = tags.strip('[]').split(',')
    if isinstance(tags, list):
        return [str(t).strip().lower() for t in tags if str(t).strip()]
    return []


def get_list_field(frontmatter, field):
    """Normalize a frontmatter field (comma string or list) to a list of strings."""
    value = frontmatter.get(field)
    if value is None:
        return []
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        if value.startswith('[') and value.endswith(']'):
            value = value[1:-1]
        return [v.strip() for v in value.split(',') if v.strip()]
    if isinstance(value, list):
        return [str(v).strip() for v in value if v is not None and str(v).strip()]
    return []


def split_frontmatter_organization_value(value):
    """Split a frontmatter organization value when it clearly lists multiple orgs."""
    text = str(value).strip()
    if not text:
        return []

    # Common pattern in imported data: "Org A / Org B".
    if ' / ' in text:
        parts = [part.strip() for part in text.split(' / ') if part.strip()]
        if len(parts) > 1:
            return parts

    return [text]


def clean_wikilink_text(value):
    """Strip [[...]] / [[...|alias]] wrapping from a single value, if present."""
    value = value.strip()
    m = FULL_WIKILINK_RE.match(value)
    if m:
        return m.group(1).strip()

    # Handle malformed/partial wikilink wrappers such as "[[Org" or "Org]]".
    if value.startswith('[['):
        value = value[2:]
    if value.endswith(']]'):
        value = value[:-2]
    if value.startswith('['):
        value = value[1:]
    if value.endswith(']'):
        value = value[:-1]
    if '|' in value:
        value = value.split('|', 1)[0]

    return value


def repair_common_mojibake(value):
    """Repair common UTF-8 mojibake sequences found in source text."""
    repaired = value
    for bad, good in MOJIBAKE_REPLACEMENTS.items():
        repaired = repaired.replace(bad, good)
    return repaired


def canonicalize_organization_name(name):
    """Collapse known subordinate or variant names into canonical organizations."""
    cleaned = repair_common_mojibake(clean_wikilink_text(name))
    return CANONICAL_ORGANIZATION_NAMES.get(cleaned.lower(), cleaned)


def should_ignore_organization(name):
    """Return True when a candidate name should not be treated as an organization."""
    return clean_wikilink_text(name).strip().lower() in IGNORED_ORGANIZATION_NAMES


def get_word_count(value):
    """Count word-like tokens in a candidate organization name."""
    return len(WORD_RE.findall(value))


def is_valid_organization_name(name):
    """Return True when a candidate organization name passes basic sanity checks."""
    return bool(name and get_word_count(name) <= MAX_ORGANIZATION_NAME_WORDS)


def extract_positions_organizations(body_lines):
    """
    Walk the '## Positions' section of a Person file's body and pull out
    organization names from bullets like:

        - Job Title, [[Organization Name]]

    The part before the first comma (the job title) is ignored. Only the
    next comma-delimited segment is treated as the organization segment, so
    later location/date metadata does not get promoted into an organization.
    Organizations in this section must be written as [[wikilinks]]; plain text
    is ignored to avoid treating free-form sentence fragments as organizations.
    """
    names = []
    in_positions = False

    for raw_line in body_lines:
        line = raw_line.rstrip('\n')

        if POSITIONS_HEADING_RE.match(line):
            in_positions = True
            continue

        if in_positions and HEADING_RE.match(line):
            # hit the next section, e.g. "## Notes"
            break

        if not in_positions:
            continue

        bullet = line.strip()
        if not bullet.startswith(('-', '*')):
            continue

        bullet_text = bullet[1:].strip()
        if ',' in bullet_text:
            _title, rest = bullet_text.split(',', 1)
        else:
            rest = bullet_text

        org_segment, _, _remainder = rest.partition(',')
        org_segment = org_segment.strip()

        wikilinks = list(WIKILINK_RE.finditer(org_segment))
        if wikilinks:
            for m in wikilinks:
                name = m.group(1).strip()
                if name:
                    names.append(name)

    return names


# ---------------------------------------------------------------------------
# Slug / name helpers
# ---------------------------------------------------------------------------

def _is_legal_suffix(token):
    return token.strip().strip('.').lower() in LEGAL_SUFFIXES


def strip_legal_suffix(name):
    """
    Remove a trailing legal-entity suffix from an organization name, e.g.:
        "Acme, Inc."       -> "Acme"
        "Acme LLC"         -> "Acme"
        "Acme Corp., Ltd." -> "Acme"
    """
    name = SELF_EMPLOYED_TRAILING_RE.sub('', name).strip()

    parts = [p.strip() for p in name.split(',') if p.strip()]
    if not parts:
        return name.strip()

    while len(parts) > 1 and _is_legal_suffix(parts[-1]):
        parts.pop()

    result = parts[0]
    words = result.split()
    while len(words) > 1 and _is_legal_suffix(words[-1]):
        words.pop()

    cleaned = ' '.join(words).strip()
    return cleaned if cleaned else name.strip()


def slugify(name):
    """lowercase the name and replace runs of non-alphanumerics with a hyphen"""
    s = repair_common_mojibake(name)
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = s.replace('&', ' and ')
    s = re.sub(r"['\u2019]", "", s)  # drop straight/curly apostrophes
    s = re.sub(r'[^a-z0-9]+', '-', s)
    s = s.strip('-')
    s = re.sub(r'-{2,}', '-', s)
    return s


def unique_slug(base_slug, organizations):
    """Make sure base_slug doesn't collide with an existing record's slug."""
    existing = {org.get('slug', '') for org in organizations}
    if base_slug not in existing:
        return base_slug
    i = 2
    while f"{base_slug}-{i}" in existing:
        i += 1
    return f"{base_slug}-{i}"


# ---------------------------------------------------------------------------
# organizations.json read/write + lookup/create
# ---------------------------------------------------------------------------

def get_organizations_path(config_dir):
    """Resolve organizations.json inside the provided config directory."""
    return os.path.join(config_dir, ORGANIZATIONS_FILENAME)

def load_organizations(config_path):
    """
    Returns (organizations_list, wrapped) where `wrapped` is True if the
    file on disk is shaped like {"organizations": [...]} rather than a
    bare list -- so we can write it back out the same way.
    """
    if not os.path.exists(config_path):
        return [], False

    with open(config_path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error parsing {config_path}: {e}")
            sys.exit(1)

    if isinstance(data, list):
        return data, False

    if isinstance(data, dict) and isinstance(data.get('organizations'), list):
        return data['organizations'], True

    print(f"Unexpected structure in {config_path}; expected a JSON list or "
          f"{{'organizations': [...]}}")
    sys.exit(1)


def save_organizations(config_path, organizations, wrapped):
    organizations.sort(key=lambda org: (get_org_name(org).lower(), str(org.get('slug', '')).lower()))
    data = {"organizations": organizations} if wrapped else organizations
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write('\n')


def get_org_name(org):
    """Return the canonical display name for an organization record."""
    return str(org.get('name') or org.get('organization') or '').strip()


def get_match_keys(name):
    """Return normalized keys used to match organization names consistently."""
    cleaned = clean_wikilink_text(name).strip()
    stripped = strip_legal_suffix(cleaned) or cleaned

    keys = set()
    for value in (cleaned, stripped, slugify(cleaned), slugify(stripped)):
        value = str(value).strip().lower()
        if value:
            keys.add(value)
    return keys


def normalize_existing_record(org, preferred_name=None):
    """Coerce legacy organization records toward the current JSON shape."""
    current_name = get_org_name(org)
    if preferred_name:
        preferred_name = preferred_name.strip()

    canonical_name = canonicalize_organization_name(preferred_name or current_name)
    if canonical_name:
        org['name'] = canonical_name

    if 'organization' in org:
        org.pop('organization', None)

    org.setdefault('aliases', [])
    if current_name and current_name.casefold() != canonical_name.casefold() and current_name not in org['aliases']:
        org['aliases'].append(current_name)
    for alias in CANONICAL_ORGANIZATION_ALIASES.get(canonical_name.casefold(), ()):
        if alias not in org['aliases']:
            org['aliases'].append(alias)
    org.setdefault('url', '')
    org.setdefault('linkedin_id', '')
    org.setdefault('x_id', '')
    org.setdefault('city', '')
    org.setdefault('province', '')
    org.setdefault('country', '')
    people = org.get('people')
    if isinstance(people, list):
        org['people'] = sorted({str(p).strip() for p in people if str(p).strip()}, key=lambda s: s.lower())
    else:
        org['people'] = []
    org.setdefault('description', '')
    org.pop('email', None)
    org.pop('phone', None)


def add_person_to_organization(org, person_slug):
    """Add person slug to organization.people if it is not already present."""
    if not person_slug:
        return
    people = org.setdefault('people', [])
    if person_slug not in people:
        people.append(person_slug)
        people.sort(key=lambda s: str(s).lower())


def find_existing(organizations, name):
    """Find a record matching `name` against organization name, slug, or aliases."""
    keys = get_match_keys(name)
    if not keys:
        return None
    for org in organizations:
        if get_match_keys(get_org_name(org)) & keys:
            return org
        if str(org.get('slug', '')).strip().lower() in keys:
            return org
        for alias in (org.get('aliases') or []):
            if get_match_keys(str(alias)) & keys:
                return org
    return None


def ensure_organization(organizations, raw_name, debug=False, source_file=None, source_hint=None, person_slug=None):
    """
    Look up `raw_name` in `organizations`; if found, make sure this exact
    spelling is recorded as an alias. If not found, create a new record.
    """
    original_name = clean_wikilink_text(raw_name)
    name = canonicalize_organization_name(raw_name)
    if not name:
        return None
    if should_ignore_organization(name):
        if debug:
            src = f" (from {source_file})" if source_file else ""
            print(f"  - skipped non-organization '{name}'{src}")
        return None
    if not is_valid_organization_name(name):
        if debug:
            src = f" (from {source_file})" if source_file else ""
            print(f"  - skipped organization candidate '{name}'{src}: exceeds {MAX_ORGANIZATION_NAME_WORDS} words")
        return None

    existing = find_existing(organizations, name)
    if existing:
        normalize_existing_record(existing, preferred_name=name)
        add_person_to_organization(existing, person_slug)
        aliases = existing.setdefault('aliases', [])
        if original_name and original_name.strip().lower() != get_org_name(existing).lower():
            if original_name not in aliases:
                aliases.append(original_name)
                if debug:
                    print(f"  + alias '{original_name}' -> existing organization "
                          f"'{get_org_name(existing)}'")
        if name.strip().lower() != get_org_name(existing).lower():
            if name not in aliases:
                aliases.append(name)
                if debug:
                    print(f"  + alias '{name}' -> existing organization "
                          f"'{get_org_name(existing)}'")
        return existing

    # Frontmatter organization values are often slugs that should resolve to an
    # existing record. If a slug-like value does not match anything, skip it
    # instead of creating a duplicate pseudo-organization.
    if source_hint == 'frontmatter' and SLUG_LIKE_RE.match(name):
        if debug:
            src = f" (from {source_file})" if source_file else ""
            print(f"  - skipped unresolved organization slug '{name}'{src}")
        return None

    clean_name = strip_legal_suffix(name) or name
    slug = unique_slug(slugify(clean_name), organizations)

    aliases = []
    if original_name != clean_name:
        aliases.append(original_name)
    if name != clean_name and name not in aliases:
        aliases.append(name)

    new_org = {
        "name": clean_name,
        "slug": slug,
        "aliases": aliases,
        "url": "",
        "linkedin_id": "",
        "x_id": "",
        "city": "",
        "province": "",
        "country": "",
        "people": [],
        "description": "",
    }
    add_person_to_organization(new_org, person_slug)
    organizations.append(new_org)

    if debug:
        src = f" (from {source_file})" if source_file else ""
        print(f"  + new organization '{clean_name}' -> slug '{slug}'{src}")

    return new_org


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------

def get_person_slug(frontmatter, filepath):
    """Get a stable person slug from frontmatter, falling back to folder name."""
    slug = str(frontmatter.get('slug') or '').strip()
    if slug:
        return slug
    return os.path.basename(os.path.dirname(filepath)).strip()


def process_file(filepath, organizations, debug=False):
    filename = os.path.basename(filepath)

    if is_date_filename(filename):
        return

    frontmatter, body_lines = read_markdown(filepath)
    if not frontmatter:
        return

    if 'person' not in get_tags(frontmatter):
        return

    person_slug = get_person_slug(frontmatter, filepath)

    if debug:
        print(f"Person file: {filepath}")
        if person_slug:
            print(f"  slug: {person_slug}")

    for raw_value in get_list_field(frontmatter, 'organizations'):
        for name in split_frontmatter_organization_value(raw_value):
            ensure_organization(
                organizations,
                name,
                debug=debug,
                source_file=filepath,
                source_hint='frontmatter',
                person_slug=person_slug,
            )

    for name in extract_positions_organizations(body_lines):
        ensure_organization(
            organizations,
            name,
            debug=debug,
            source_file=filepath,
            source_hint='positions',
            person_slug=person_slug,
        )

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Build/update organizations.json from hal_md Person markdown files."
    )
    parser.add_argument('-s', '--source', required=True,
                         help='Folder to recursively scan for Person markdown files')
    parser.add_argument('-c', '--config', default=DEFAULT_CONFIG_DIR,
                         help=f'Folder containing (or to contain) organizations.json (default: {DEFAULT_CONFIG_DIR})')
    parser.add_argument('-d', '--debug', action='store_true',
                         help='Print extra info as files/bullets/aliases are processed')
    parser.add_argument('-v', '--verbose', action='store_true',
                         help='Print folders and files as they are scanned')
    parser.add_argument('-x', '--max', type=int, default=None,
                         help='Maximum number of person markdown files to process')
    parser.add_argument('-n', '--dry-run', action='store_true',
                         help="Don't write organizations.json, just report what would change")
    args = parser.parse_args()

    if not os.path.isdir(args.source):
        print(f"Source folder not found: {args.source}")
        sys.exit(1)

    if not os.path.isdir(args.config):
        print(f"Config folder not found: {args.config}")
        sys.exit(1)

    config_path = get_organizations_path(args.config)

    organizations, wrapped = load_organizations(config_path)
    for org in organizations:
        normalize_existing_record(org)
    starting_count = len(organizations)

    file_count = 0
    person_file_count = 0
    for root, _, files in os.walk(args.source):
        dirs = _
        dirs[:] = [
            dirname for dirname in dirs
            if not dirname.startswith('.') and dirname.lower() != 'media'
        ]
        if os.path.normpath(root) == os.path.normpath(args.source):
            continue
        for filename in files:
            if filename.startswith('.'):
                continue
            if is_date_filename(filename):
                continue
            filepath = os.path.join(root, filename)
            if args.verbose:
                print(f"  file: {filepath}")
            if not filename.lower().endswith('.md'):
                continue
            file_count += 1

            frontmatter_preview_len = len(organizations)
            if process_file(filepath, organizations, debug=args.debug):
                person_file_count += 1
                if args.max is not None and person_file_count >= args.max:
                    break
            if len(organizations) != frontmatter_preview_len or args.debug:
                pass  # debug output already printed inside process_file
        if args.max is not None and person_file_count >= args.max:
            break

    added = len(organizations) - starting_count

    print(f"Scanned {file_count} markdown file(s) under {args.source}")
    if args.max is not None:
        print(f"Processed {person_file_count} person file(s) (max {args.max})")
    print(f"Organizations: {starting_count} before, {len(organizations)} after "
          f"({added} added)")

    if args.dry_run:
        print("Dry run: organizations.json was not written.")
    else:
        save_organizations(config_path, organizations, wrapped)
        print(f"Wrote {config_path}")


if __name__ == '__main__':
    main()