from __future__ import annotations

import re

import yaml

_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Splits a Markdown file into (frontmatter dict, body without it).

    A vault will always have plenty of notes with no frontmatter at all, and
    occasionally malformed YAML - neither should ever break ingestion, so
    both cases just fall back to (empty dict, the original text unchanged)
    rather than raising.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}, text

    if not isinstance(data, dict):
        return {}, text

    return data, text[match.end():]


def extract_wikilinks(body: str) -> list[str]:
    """[[Note]], [[Note|Display text]], and [[Note#Heading]] all resolve to
    the same target note title - only that part is kept. Order-preserving,
    de-duplicated."""
    seen: list[str] = []
    for m in _WIKILINK_RE.finditer(body):
        title = m.group(1).strip()
        if title and title not in seen:
            seen.append(title)
    return seen


def normalize_tags(raw: object) -> list[str]:
    """Obsidian frontmatter tags show up as either a YAML list or a
    comma-separated string in the wild - accept both."""
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    if isinstance(raw, str):
        return [t.strip() for t in raw.split(",") if t.strip()]
    return []
