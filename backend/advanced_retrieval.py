"""Table semantics, parent contexts, query rewriting, and feedback redaction."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from typing import Any

from .table_query import matching_rows


def normalize_term(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\s_\-—–/:：()（）\[\]【】]+", "", normalized)


def _table_cells(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [
        cell.replace(r"\|", "|").strip() for cell in re.split(r"(?<!\\)\|", stripped)
    ]


def table_metadata(markdown: str) -> dict[str, Any]:
    lines = [line for line in markdown.splitlines() if line.strip()]
    if len(lines) < 2:
        return {}
    headers = _table_cells(lines[0])
    rows = []
    cells = []
    row_values = []
    unique_headers = {header for header in headers if headers.count(header) == 1}
    for row_index, line in enumerate(lines[2:], start=1):
        values = _table_cells(line)
        row = {}
        for column_index, header in enumerate(headers):
            value = values[column_index] if column_index < len(values) else ""
            if header in unique_headers:
                row[header] = value
            cells.append(
                {
                    "row": row_index,
                    "column": column_index + 1,
                    "header": header,
                    "value": value,
                }
            )
        rows.append(row)
        row_values.append([values[i] if i < len(values) else "" for i in range(len(headers))])
    context_rows = [
        "; ".join(f"{header} [column_{i + 1}]={values[i]}" for i, header in enumerate(headers))
        for values in row_values
    ]
    return {
        "headers": headers,
        "format_version": 2,
        "columns": [{"id": f"column_{i + 1}", "index": i + 1, "header": h} for i, h in enumerate(headers)],
        "row_values": row_values,
        "rows": rows,
        "cells": cells,
        "semantic_text": "Table columns: "
        + ", ".join(headers)
        + ". Rows: "
        + " | ".join(context_rows),
    }


def attach_parent_context(
    chunks: list[dict], document_id: str, *, max_parent_chars: int = 6000
) -> None:
    if max_parent_chars < 1:
        raise ValueError("max_parent_chars must be positive")
    groups: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    for chunk in chunks:
        groups[tuple(chunk.get("section_path", []))].append(chunk)
    for section, members in groups.items():
        ordered = sorted(
            members,
            key=lambda item: (
                item.get("metadata", {}).get("sequence", 0),
                item["page_start"],
                item["id"],
            ),
        )
        # A table can span several parent batches. Keep its nearby introductory
        # text (for example, a table-wide unit) available in each batch. Do not
        # borrow introductions from another page or duplicate long prose.
        introductions = {}
        introduction = None
        for item in ordered:
            if item.get("kind", "text") == "text":
                introduction = item if len(item["text"]) <= 1000 else None
            elif item.get("kind") == "table" and introduction is not None:
                if item["pages"] == introduction["pages"]:
                    introductions[item["id"]] = introduction
                else:
                    introduction = None
        batches: list[list[dict]] = []
        current: list[dict] = []
        current_chars = 0
        for item in ordered:
            item_chars = max(len(item["markdown"]), len(item["text"]))
            separator_chars = 2 if current else 0
            if (
                current
                and current_chars + separator_chars + item_chars > max_parent_chars
            ):
                batches.append(current)
                current = []
                current_chars = 0
                separator_chars = 0
            current.append(item)
            current_chars += separator_chars + item_chars
        if current:
            batches.append(current)

        for batch_index, batch in enumerate(batches):
            context_members = list(batch)
            batch_ids = {item["id"] for item in batch}
            for item in batch:
                intro = introductions.get(item["id"])
                if intro is not None and intro["id"] not in batch_ids:
                    context_members.insert(0, intro)
                    batch_ids.add(intro["id"])
            parent_markdown = "\n\n".join(item["markdown"] for item in context_members)
            parent_text = "\n\n".join(item["text"] for item in context_members)
            pages = sorted({page for item in context_members for page in item["pages"]})
            identity = (
                f"{document_id}:{'/'.join(section)}:{batch_index}:"
                f"{hashlib.sha256(parent_markdown.encode()).hexdigest()}"
            )
            parent_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
            for child in batch:
                metadata = child.setdefault("metadata", {})
                metadata.update(
                    {
                        "parent_id": parent_id,
                        "parent_markdown": parent_markdown,
                        "parent_text": parent_text,
                        "parent_pages": pages,
                        "parent_section_path": list(section),
                    }
                )


class RuleBasedQueryRewriter:
    """Bounded, deterministic rewrite path suitable for offline operation."""

    _SPLIT = re.compile(r"\s+(?:and|or)\s+|(?:以及|并且|还有)|[；;？?]", re.IGNORECASE)

    def __init__(self, aliases: dict[str, str] | None = None):
        self.aliases = aliases or {}

    def rewrite(self, query: str, max_variants: int) -> list[str]:
        normalized = re.sub(r"\s+", " ", query).strip()
        variants = [normalized]
        without_politeness = re.sub(
            r"^(?:请问|麻烦问下|帮我查一下|could you|please)\s*",
            "",
            normalized,
            flags=re.IGNORECASE,
        ).strip()
        if without_politeness and without_politeness not in variants:
            variants.append(without_politeness)
        for alias, expansion in self.aliases.items():
            if alias.isascii() and all(
                character.isalnum() or character == "_" for character in alias
            ):
                pattern = re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)", re.IGNORECASE)
            else:
                pattern = re.compile(re.escape(alias), re.IGNORECASE)
            expanded = pattern.sub(expansion, without_politeness)
            if expanded != without_politeness and expanded not in variants:
                variants.append(expanded)
            if len(variants) >= max_variants:
                return variants[:max_variants]
        for part in self._SPLIT.split(without_politeness):
            part = part.strip(" ，,。.")
            if len(part) >= 2 and part not in variants:
                variants.append(part)
            if len(variants) >= max_variants:
                break
        return variants[:max_variants]


def reciprocal_rank_fusion(
    routes: list[tuple[str, list]], *, limit: int, rank_constant: int = 60
) -> list[tuple[Any, float, list[str]]]:
    if rank_constant < 1:
        raise ValueError("RRF rank constant must be positive")
    fused: dict[str, tuple[Any, float, list[str]]] = {}
    for query, hits in routes:
        for rank, hit in enumerate(hits, start=1):
            contribution = 1 / (rank_constant + rank)
            existing = fused.get(hit.chunk_id)
            if existing is None:
                fused[hit.chunk_id] = (hit, contribution, [query])
            else:
                old_hit, score, matched_queries = existing
                if query not in matched_queries:
                    matched_queries.append(query)
                fused[hit.chunk_id] = (old_hit, score + contribution, matched_queries)
    ranked = sorted(
        fused.values(),
        key=lambda item: (-item[1], -item[0].score, item[0].chunk_id),
    )
    return ranked[:limit]


def table_matches(metadata: dict[str, Any], filters: tuple) -> bool:
    if not filters:
        return True
    return bool(matching_rows(metadata, dict(filters)))


def redact_feedback_text(value: str) -> str:
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]", value)
    value = re.sub(r"(?<!\d)(?:\+?\d[\d -]{7,}\d)(?!\d)", "[PHONE]", value)
    return value
