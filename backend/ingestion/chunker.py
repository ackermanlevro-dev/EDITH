from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


@dataclass
class Chunk:
    content: str
    chunk_index: int
    heading_path: str | None
    metadata: dict = field(default_factory=dict)


def _split_into_sections(text: str) -> list[tuple[list[str], str]]:
    """Split markdown on headings, keeping the heading breadcrumb (e.g.
    ["Troubleshooting", "GRUB rescue"]) for each section body."""
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [([], text)] if text.strip() else []

    sections: list[tuple[list[str], str]] = []
    stack: list[tuple[int, str]] = []

    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append(([], preamble))

    for i, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip()
        stack = [s for s in stack if s[0] < level]
        stack.append((level, title))

        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()

        if body:
            sections.append(([t for _, t in stack], body))

    return sections


def _split_body(body: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Pack paragraphs into ~chunk_size pieces. Only falls back to a hard
    character split when a single paragraph alone exceeds chunk_size."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    pieces: list[str] = []
    current = ""

    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            pieces.append(current)

        if len(para) <= chunk_size:
            current = para
        else:
            step = max(chunk_size - chunk_overlap, 1)
            for start in range(0, len(para), step):
                pieces.append(para[start : start + chunk_size])
            current = ""

    if current:
        pieces.append(current)

    if chunk_overlap and len(pieces) > 1:
        overlapped = [pieces[0]]
        for prev, cur in zip(pieces, pieces[1:]):
            tail = prev[-chunk_overlap:]
            overlapped.append(cur if tail in cur else f"{tail}\n\n{cur}")
        return overlapped

    return pieces


def chunk_markdown(
    text: str,
    *,
    title: str | None,
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
) -> list[Chunk]:
    """Structure-aware chunker: split by heading first, then pack paragraphs
    within each section to ~chunk_size, so a chunk never straddles two
    unrelated headings and always carries its section as context."""
    chunks: list[Chunk] = []
    index = 0

    for heading_stack, body in _split_into_sections(text):
        heading_path = " > ".join(heading_stack) if heading_stack else None
        for piece in _split_body(body, chunk_size, chunk_overlap):
            chunks.append(
                Chunk(
                    content=piece,
                    chunk_index=index,
                    heading_path=heading_path,
                    metadata={
                        "document_title": title,
                        "heading": heading_stack[-1] if heading_stack else None,
                    },
                )
            )
            index += 1

    return chunks
