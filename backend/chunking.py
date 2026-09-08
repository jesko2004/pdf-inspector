"""RAG-ready, page-aware Markdown chunking."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_TABLE_SEPARATOR = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)


@dataclass(frozen=True)
class Block:
    kind: str
    markdown: str


def _blocks(markdown: str) -> list[Block]:
    lines = markdown.splitlines()
    blocks: list[Block] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(Block("text", "\n".join(paragraph).strip()))
            paragraph.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        heading = _HEADING.match(line)
        if heading:
            flush_paragraph()
            blocks.append(Block("heading", line.strip()))
            index += 1
            continue
        if (
            index + 1 < len(lines)
            and "|" in line
            and _TABLE_SEPARATOR.match(lines[index + 1])
        ):
            flush_paragraph()
            table_lines = [line, lines[index + 1]]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                table_lines.append(lines[index])
                index += 1
            blocks.append(Block("table", "\n".join(table_lines).strip()))
            continue
        if not line.strip():
            flush_paragraph()
        else:
            paragraph.append(line.rstrip())
        index += 1
    flush_paragraph()
    return blocks


def _split_long_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    pieces = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n", start, end), text.rfind("。", start, end))
            if boundary > start + max_chars // 2:
                end = boundary + 1
        pieces.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return [piece for piece in pieces if piece]


def _split_table(markdown: str, max_chars: int) -> list[str]:
    """Split oversized tables only between rows and repeat the header."""
    if len(markdown) <= max_chars:
        return [markdown]
    lines = markdown.splitlines()
    if len(lines) <= 2:
        return [markdown]
    header = lines[:2]
    parts: list[str] = []
    current = header.copy()
    for row in lines[2:]:
        candidate = "\n".join([*current, row])
        if len(candidate) > max_chars and len(current) > 2:
            parts.append("\n".join(current))
            current = [*header, row]
        else:
            current.append(row)
    if len(current) > 2:
        parts.append("\n".join(current))
    return parts or [markdown]


def _make_chunk(
    document_id: str,
    page: int,
    section_path: list[str],
    kind: str,
    markdown: str,
    sequence: int,
) -> dict:
    content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    identity = (
        f"{document_id}:{page}:{'/'.join(section_path)}:"
        f"{kind}:{sequence}:{content_hash}"
    )
    return {
        "id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
        "kind": kind,
        "markdown": markdown,
        "text": re.sub(r"\*\*|__|`", "", markdown),
        "page_start": page,
        "page_end": page,
        "pages": [page],
        "section_path": section_path.copy(),
        "char_count": len(markdown),
        "content_hash": content_hash,
    }


def chunk_pages(
    pages: list[tuple[int, str]],
    *,
    document_id: str,
    target_chars: int = 1200,
    max_chars: int = 1800,
    overlap_chars: int = 150,
) -> list[dict]:
    """Create deterministic chunks with citations and intact Markdown tables."""
    if not (0 <= overlap_chars < max_chars):
        raise ValueError(
            "overlap_chars must be non-negative and smaller than max_chars"
        )
    if not (1 <= target_chars <= max_chars):
        raise ValueError("target_chars must be between 1 and max_chars")

    chunks: list[dict] = []
    section_path: list[str] = []
    sequence = 0
    for page, markdown in sorted(pages):
        pending: list[str] = []

        def emit_pending() -> None:
            nonlocal sequence
            if not pending:
                return
            combined = "\n\n".join(pending).strip()
            pending.clear()
            for piece in _split_long_text(combined, max_chars, overlap_chars):
                sequence += 1
                chunks.append(
                    _make_chunk(
                        document_id, page, section_path, "text", piece, sequence
                    )
                )

        for block in _blocks(markdown):
            if block.kind == "heading":
                emit_pending()
                match = _HEADING.match(block.markdown)
                assert match is not None
                level = len(match.group(1))
                title = match.group(2).strip()
                section_path[level - 1 :] = [title]
                continue
            if block.kind == "table":
                emit_pending()
                for piece in _split_table(block.markdown, max_chars):
                    sequence += 1
                    chunks.append(
                        _make_chunk(
                            document_id, page, section_path, "table", piece, sequence
                        )
                    )
                continue
            candidate = "\n\n".join([*pending, block.markdown])
            if pending and len(candidate) > target_chars:
                emit_pending()
            pending.append(block.markdown)
        emit_pending()
    return chunks
