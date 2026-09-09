"""RAG-ready, page-aware Markdown chunking."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_TABLE_SEPARATOR = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)


@dataclass(frozen=True)
class Block:
    kind: str
    markdown: str


@dataclass(frozen=True)
class ChunkQualityConfig:
    """Conservative defaults for removing retrieval noise without losing tables."""

    min_text_chars: int = 8
    min_alnum_ratio: float = 0.2
    repeated_margin_min_pages: int = 3
    repeated_margin_page_ratio: float = 0.6
    margin_lines: int = 2


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
    plain_text = _plain_text(markdown)
    return {
        "id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
        "kind": kind,
        "markdown": markdown,
        "text": plain_text,
        "page_start": page,
        "page_end": page,
        "pages": [page],
        "section_path": section_path.copy(),
        "char_count": len(markdown),
        "content_hash": content_hash,
        "source_occurrences": 1,
    }


def _plain_text(markdown: str) -> str:
    text = re.sub(r"<!--.*?-->", "", markdown, flags=re.DOTALL)
    text = re.sub(r"!?\[([^]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`~]", "", text)
    return text.strip()


def _normalized_content(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def _normalized_margin(text: str) -> str:
    normalized = _normalized_content(_plain_text(text))
    normalized = re.sub(r"\d+", "#", normalized)
    return normalized.strip(" -|—–_#")


def _is_protected_margin_line(line: str) -> bool:
    """Keep structures whose removal could corrupt section or table semantics."""
    return bool(
        _HEADING.match(line)
        or _TABLE_SEPARATOR.match(line)
        or line.count("|") >= 2
    )


def _remove_repeated_margins(
    pages: list[tuple[int, str]], config: ChunkQualityConfig
) -> tuple[list[tuple[int, str]], int, list[str]]:
    """Remove recurring first/last lines, including page-number variations."""
    positions: dict[int, set[int]] = {}
    candidates: Counter[str] = Counter()
    examples: dict[str, str] = {}
    eligible_pages = 0
    for page, markdown in pages:
        lines = markdown.splitlines()
        nonempty = [index for index, line in enumerate(lines) if line.strip()]
        # Keep a body line between the inspected top and bottom bands. This
        # prevents short pages from having their entire content treated as a margin.
        if len(nonempty) <= config.margin_lines * 2:
            continue
        eligible_pages += 1
        indexes = set(
            nonempty[: config.margin_lines] + nonempty[-config.margin_lines :]
        )
        positions[page] = indexes
        per_page = set()
        for index in indexes:
            if _is_protected_margin_line(lines[index]):
                continue
            normalized = _normalized_margin(lines[index])
            if normalized:
                per_page.add(normalized)
                examples.setdefault(normalized, lines[index].strip())
        candidates.update(per_page)

    threshold = max(
        config.repeated_margin_min_pages,
        math.ceil(eligible_pages * config.repeated_margin_page_ratio),
    )
    repeated = {
        normalized
        for normalized, count in candidates.items()
        if count >= threshold
    }
    if not repeated:
        return pages, 0, []

    cleaned = []
    removed_count = 0
    for page, markdown in pages:
        lines = markdown.splitlines()
        removable = positions.get(page, set())
        kept = []
        for index, line in enumerate(lines):
            if (
                index in removable
                and not _is_protected_margin_line(line)
                and _normalized_margin(line) in repeated
            ):
                removed_count += 1
                continue
            kept.append(line)
        cleaned.append((page, "\n".join(kept).strip()))
    return cleaned, removed_count, sorted(examples[item] for item in repeated)


def _quality_reason(chunk: dict, config: ChunkQualityConfig) -> str | None:
    text = _normalized_content(chunk["text"])
    alnum_count = sum(character.isalnum() for character in text)
    visible_count = sum(not character.isspace() for character in text)
    if alnum_count == 0:
        return "no_alphanumeric_content"
    if chunk["kind"] == "table":
        # A small two-column lookup row can be valuable even when it is short.
        return None
    if alnum_count < config.min_text_chars:
        return "too_short"
    if visible_count and alnum_count / visible_count < config.min_alnum_ratio:
        return "low_alphanumeric_ratio"
    return None


def _filter_and_deduplicate(
    chunks: list[dict], config: ChunkQualityConfig
) -> tuple[list[dict], Counter[str], int]:
    accepted: list[dict] = []
    rejected: Counter[str] = Counter()
    by_identity: dict[tuple[str, tuple[str, ...], str], dict] = {}
    duplicates = 0
    for chunk in chunks:
        reason = _quality_reason(chunk, config)
        if reason is not None:
            rejected[reason] += 1
            continue
        identity = (
            chunk["kind"],
            tuple(chunk["section_path"]),
            _normalized_content(chunk["markdown"]),
        )
        original = by_identity.get(identity)
        if original is None:
            by_identity[identity] = chunk
            accepted.append(chunk)
            continue
        duplicates += 1
        original["pages"] = sorted(set([*original["pages"], *chunk["pages"]]))
        original["page_start"] = min(original["pages"])
        original["page_end"] = max(original["pages"])
        original["source_occurrences"] += chunk["source_occurrences"]
    return accepted, rejected, duplicates


def chunk_pages(
    pages: list[tuple[int, str]],
    *,
    document_id: str,
    target_chars: int = 1200,
    max_chars: int = 1800,
    overlap_chars: int = 150,
    quality_config: ChunkQualityConfig | None = None,
) -> list[dict]:
    """Create deterministic chunks with citations and intact Markdown tables."""
    chunks, _report = chunk_pages_with_report(
        pages,
        document_id=document_id,
        target_chars=target_chars,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
        quality_config=quality_config,
    )
    return chunks


def chunk_pages_with_report(
    pages: list[tuple[int, str]],
    *,
    document_id: str,
    target_chars: int = 1200,
    max_chars: int = 1800,
    overlap_chars: int = 150,
    quality_config: ChunkQualityConfig | None = None,
) -> tuple[list[dict], dict]:
    """Create chunks and return observable filtering/deduplication statistics."""
    if not (0 <= overlap_chars < max_chars):
        raise ValueError(
            "overlap_chars must be non-negative and smaller than max_chars"
        )
    if not (1 <= target_chars <= max_chars):
        raise ValueError("target_chars must be between 1 and max_chars")
    config = quality_config or ChunkQualityConfig()
    if config.min_text_chars < 0:
        raise ValueError("min_text_chars must be non-negative")
    if not 0 <= config.min_alnum_ratio <= 1:
        raise ValueError("min_alnum_ratio must be between 0 and 1")
    if config.repeated_margin_min_pages < 2:
        raise ValueError("repeated_margin_min_pages must be at least 2")
    if not 0 < config.repeated_margin_page_ratio <= 1:
        raise ValueError("repeated_margin_page_ratio must be between 0 and 1")
    if config.margin_lines < 1:
        raise ValueError("margin_lines must be positive")

    sorted_pages = sorted(pages)
    cleaned_pages, removed_margin_lines, repeated_margins = (
        _remove_repeated_margins(sorted_pages, config)
    )

    chunks: list[dict] = []
    section_path: list[str] = []
    sequence = 0
    for page, markdown in cleaned_pages:
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
    candidate_count = len(chunks)
    chunks, rejected, duplicate_count = _filter_and_deduplicate(chunks, config)
    report = {
        "pages_processed": len(sorted_pages),
        "candidate_chunks": candidate_count,
        "emitted_chunks": len(chunks),
        "duplicates_removed": duplicate_count,
        "low_quality_removed": sum(rejected.values()),
        "rejected_by_reason": dict(sorted(rejected.items())),
        "repeated_margin_lines_removed": removed_margin_lines,
        "repeated_margins": repeated_margins,
        "deduplication_mode": "exact_normalized_within_section",
    }
    return chunks, report
