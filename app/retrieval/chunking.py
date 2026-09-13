"""
Markdown chunking without a framework.

A document's header block (the `Key: value` lines before the first `## `)
is metadata, not content. The body is split at `## ` / `### ` headings; a
section longer than `max_chars` is packed greedily by paragraph and bullet,
and every chunk is prefixed with the document title and its heading path so
a chunk read in isolation still says what it is about.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_MAX_CHARS = 600
_HEADING = re.compile(r"^(#{2,3})\s+(.*)$")


@dataclass(frozen=True)
class Chunk:
    text: str  # what is embedded and indexed: "<title> — <heading>\n<content>"
    heading: str  # "Key Capabilities" or "Key Capabilities › Available Elements"
    index: int  # position within the document


def body_of(markdown: str) -> str:
    """Everything from the first `## ` heading on; the header block is metadata."""
    match = re.search(r"^##+\s", markdown, re.MULTILINE)
    return markdown[match.start():] if match else markdown


def chunk_markdown(markdown: str, title: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[Chunk]:
    sections = _sections(body_of(markdown))
    chunks: list[Chunk] = []
    for heading, content in sections:
        for piece in _pack(_units(content), max_chars):
            chunks.append(Chunk(text=f"{title} — {heading}\n{piece}", heading=heading, index=len(chunks)))
    return chunks


def _sections(body: str) -> list[tuple[str, str]]:
    """(heading path, content) per heading, in document order."""
    out: list[tuple[str, str]] = []
    h2 = ""
    heading = ""
    buffer: list[str] = []

    def flush() -> None:
        content = "\n".join(buffer).strip()
        if content:
            out.append((heading or "Overview", content))
        buffer.clear()

    for line in body.splitlines():
        match = _HEADING.match(line)
        if match:
            flush()
            level, text = len(match.group(1)), match.group(2).strip()
            if level == 2:
                h2, heading = text, text
            else:
                heading = f"{h2} › {text}" if h2 else text
            continue
        buffer.append(line)
    flush()
    return out


def _units(content: str) -> list[str]:
    """Paragraphs, bullets and whole tables as indivisible units.

    A table stays together so its header row is never separated from its rows;
    an oversize table becomes one oversize chunk rather than a headless tail.
    """
    units: list[str] = []
    for block in re.split(r"\n\s*\n", content):
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        if all(l.lstrip().startswith("|") for l in lines):
            units.append("\n".join(l.strip() for l in lines))
        elif all(l.lstrip().startswith(("-", "*")) for l in lines):
            units.extend(l.strip() for l in lines)  # each bullet on its own
        else:
            units.append(" ".join(l.strip() for l in lines))
    return units


def _pack(units: list[str], max_chars: int) -> list[str]:
    """Greedy packing of units into pieces of at most max_chars (a single oversize unit stands alone)."""
    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for unit in units:
        if current and size + len(unit) + 1 > max_chars:
            pieces.append("\n".join(current))
            current, size = [], 0
        current.append(unit)
        size += len(unit) + 1
    if current:
        pieces.append("\n".join(current))
    return pieces
