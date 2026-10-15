"""Source-neutral rendering, ordering, and merging for Person position timelines."""

import re

from .summarization import _normalize_bullets


_DATE_TAIL_RE = re.compile(
    r",?\s+(?P<start>\d{4}(?:-\d{2}(?:-\d{2})?)?)"
    r"(?:\s+to\s+(?P<end>\d{4}(?:-\d{2}(?:-\d{2})?)?))?"
    r"(?:\s+#current)?$",
    re.IGNORECASE,
)
_ENDED_CURRENT_RE = re.compile(
    r"(?P<date>\d{4}(?:-\d{2}(?:-\d{2})?)?\s+to\s+\d{4}(?:-\d{2}(?:-\d{2})?)?)\s+#current$",
    re.IGNORECASE,
)
_MORE_RE = re.compile(r"\s*(?:…|\.\.\.)\s*more\s*$", re.IGNORECASE)


def timeline_date_range(item: dict) -> str:
    start_date = str(item.get("start_date") or "").strip()
    end_date = str(item.get("end_date") or "").strip()
    if end_date:
        return f"{start_date} to {end_date}" if start_date else end_date
    if not start_date:
        return "#current" if item.get("current") else ""
    return f"{start_date} #current"


def sort_timeline_items(items: list[dict]) -> list[dict]:
    """Sort undated items first, completed items chronologically, then current items."""
    def sort_key(item: dict) -> tuple[int, str]:
        if item.get("current") and not item.get("end_date"):
            return 2, str(item.get("start_date") or "")
        if item.get("start_date"):
            return 1, str(item["start_date"])
        return 0, ""

    return sorted(items, key=sort_key)


def render_timeline(
    items: list[dict],
    *,
    organization_links=None,
    city_link=None,
    title_cleaner=None,
    skip_item=None,
    description_summarizer=None,
) -> list[str]:
    """Render timeline item dictionaries as Markdown bullets and quoted descriptions.

    Optional callbacks let a source adapter provide organization link resolution,
    city/title cleanup, and source-specific row filtering.
    """
    if not items:
        return ["- "]

    lines = []
    for item in items:
        if skip_item and skip_item(item):
            continue
        title = str(item.get("title") or "")
        if title_cleaner:
            title = title_cleaner(title)
        else:
            title = re.sub(r"\s*,\s*", ", ", " ".join(title.split())).strip()

        organizations = organization_links(item) if organization_links else _default_organization_links(item)
        city = str(item.get("city") or "").strip()
        if city and city_link:
            city = city_link(city)
        elif city:
            city = f"[[{city}]]"

        parts = [part for part in [title, *organizations, city, timeline_date_range(item)] if part]
        lines.append(f"- {', '.join(parts)}" if parts else "- ")

        description = str(item.get("description") or "")
        if description_summarizer and description.strip():
            description = description_summarizer.summarize(description)
        rendered_description = format_timeline_description(description)
        if rendered_description:
            lines.extend(["", rendered_description, ""])

    while len(lines) > 1 and lines[-1] == "" and lines[-2] == "":
        lines.pop()
    return lines if lines else ["- "]


def _default_organization_links(item: dict) -> list[str]:
    organizations = item.get("organizations")
    if not isinstance(organizations, list) or not organizations:
        organization = item.get("organization")
        organizations = [organization] if organization else []
    return [f"[[{str(organization).strip()}]]" for organization in organizations if str(organization or "").strip()]


def format_timeline_description(description: str) -> str:
    normalized = _normalize_bullets(description)
    if not normalized.strip():
        return ""
    lines = normalized.splitlines()
    non_empty_lines = [line for line in lines if line.strip()]
    if any(re.match(r"^\s*(?:>\s*)?-\s+", line) for line in non_empty_lines):
        flattened = " ".join(
            _normalize_parenthetical_spacing(
                re.sub(r"^(?:>\s*)?(?:-\s+)+", "", line.strip())
            )
            for line in non_empty_lines
        )
        return f"  > {flattened}" if flattened else ""
    if len(non_empty_lines) == 1:
        lines = [re.sub(r"^\s*-\s+", "", line).strip() if line.strip() else line for line in lines]
    return "\n".join(f"  > {line}" if line else "  >" for line in lines)


def _normalize_parenthetical_spacing(value: str) -> str:
    return re.sub(r"(?<=[A-Za-z0-9])\(", " (", value)


def merge_timeline_sections(
    existing_markdown: str,
    generated_markdown: str,
    section_heading: str = "## Positions",
) -> str:
    """Merge existing and generated timeline blocks, preferring newly generated matches."""
    existing_lines = existing_markdown.splitlines()
    generated_lines = generated_markdown.splitlines()
    existing_bounds = _section_bounds(existing_lines, section_heading)
    generated_bounds = _section_bounds(generated_lines, section_heading)
    if existing_bounds is None or generated_bounds is None:
        return generated_markdown

    existing_start, existing_end = existing_bounds
    generated_start, generated_end = generated_bounds
    merged_by_key = {}
    for block in _position_blocks(existing_lines[existing_start + 1 : existing_end]):
        normalized_block = _remove_current_from_ended_position(block)
        key = _position_identity(normalized_block)
        if key:
            merged_by_key[key] = normalized_block
    for block in _position_blocks(generated_lines[generated_start + 1 : generated_end]):
        key = _position_identity(block)
        if key:
            merged_by_key[key] = block

    merged_blocks = sorted(merged_by_key.values(), key=_position_sort_key)
    section_lines = [""]
    if merged_blocks:
        for index, block in enumerate(merged_blocks):
            if index:
                section_lines.append("")
            section_lines.extend(block)
        section_lines.append("")
    else:
        section_lines.extend(["- ", ""])

    result = "\n".join(
        generated_lines[: generated_start + 1] + section_lines + generated_lines[generated_end:]
    )
    return result + ("\n" if generated_markdown.endswith("\n") else "")


def _section_bounds(lines: list[str], heading: str) -> tuple[int, int] | None:
    start = next((index for index, line in enumerate(lines) if line.strip() == heading), None)
    if start is None:
        return None
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return start, end


def _position_blocks(lines: list[str]) -> list[list[str]]:
    blocks = []
    for line in lines:
        if line.startswith("- "):
            if blocks:
                while blocks[-1] and not blocks[-1][-1].strip():
                    blocks[-1].pop()
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)
    for block in blocks:
        while block and not block[-1].strip():
            block.pop()
    return [block for block in blocks if block[0].strip() != "- "]


def _remove_current_from_ended_position(block: list[str]) -> list[str]:
    if not block:
        return block
    match = _ENDED_CURRENT_RE.search(block[0])
    if not match:
        return block
    return [block[0][: match.start()] + match.group("date"), *block[1:]]


def _position_identity(block: list[str]) -> str:
    if not block:
        return ""
    bullet = _DATE_TAIL_RE.sub("", block[0].strip())
    bullet = re.sub(
        r"\[\[([^\]]+)\]\]",
        lambda match: f"[[{_clean_organization_name(match.group(1))}]]",
        bullet,
    )
    return " ".join(bullet.split()).casefold()


def _position_sort_key(block: list[str]) -> tuple[int, str]:
    if not block:
        return 0, ""
    match = _DATE_TAIL_RE.search(block[0].strip())
    if not match:
        return (2, "") if re.search(r"\s+#current$", block[0]) else (0, "")
    start, end = match.group("start"), match.group("end")
    return (1, start) if end else (2, start)


def _clean_organization_name(value: str) -> str:
    name = str(value or "").strip()
    return re.sub(
        r"(?:[,\s]+(?:inc\.?|incorporated|corporation|corp\.?|company|co\.?|limited|ltd\.?|llc|l\.l\.c\.|llp|l\.l\.p\.|lp|l\.p\.|plc|gmbh|s\.a\.|s\.a\.s\.|sarl|ag|bv|pte\.?\s+ltd\.?|pty\.?\s+ltd\.?))+$",
        "",
        name,
        flags=re.IGNORECASE,
    ).strip(" ,-–—")
