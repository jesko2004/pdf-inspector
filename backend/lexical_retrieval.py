"""Small-corpus BM25 over the authoritative, filtered indexed-chunk snapshot.

No independent lexical index is kept: deletes, versions and failed batches use
the same metadata snapshot as retrieval. This is a single-instance MVP, not an
inverted-index implementation for large corpora.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence

from .advanced_retrieval import table_matches
from .vector_store import VectorSearchHit


def lexical_tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    tokens = []
    for token in re.findall(r"[a-z0-9]+(?:[._/-][a-z0-9]+)*|[\u3400-\u9fff]+", normalized):
        if "\u3400" <= token[0] <= "\u9fff":
            tokens.extend(token)
            tokens.extend(token[index : index + 2] for index in range(len(token) - 1))
        else:
            tokens.append(token)
    return tokens


def bm25_search(
    query: str,
    chunks: list[dict],
    *,
    knowledge_base_id: str,
    top_k: int,
    page_start: int | None = None,
    page_end: int | None = None,
    kinds: Sequence[str] = (),
    section_path_prefix: Sequence[str] = (),
    table_filters: dict[str, str] | None = None,
    k1: float = 1.2,
    b: float = 0.75,
) -> list[VectorSearchHit]:
    if k1 <= 0 or not 0 <= b <= 1:
        raise ValueError("BM25 requires k1 > 0 and 0 <= b <= 1")
    terms = set(lexical_tokens(query))
    if not terms:
        return []
    # Compute corpus statistics on the authorized version snapshot, independently
    # of page/kind/table filters, so query filters do not silently alter IDF.
    frequencies = [Counter(lexical_tokens(chunk["text"])) for chunk in chunks]
    lengths = [sum(frequency.values()) for frequency in frequencies]
    average = sum(lengths) / len(lengths) if lengths else 0
    if not average:
        return []
    document_frequencies = {
        term: sum(term in frequency for frequency in frequencies) for term in terms
    }
    hits = []
    for chunk, frequency, length in zip(chunks, frequencies, lengths):
        if page_start is not None and chunk["page_end"] < page_start:
            continue
        if page_end is not None and chunk["page_start"] > page_end:
            continue
        if kinds and chunk["kind"] not in kinds:
            continue
        if section_path_prefix and chunk["section_path"][: len(section_path_prefix)] != list(section_path_prefix):
            continue
        if not table_matches(chunk["metadata"], tuple(sorted((table_filters or {}).items()))):
            continue
        score = 0.0
        for term in terms:
            count = frequency[term]
            if not count:
                continue
            df = document_frequencies[term]
            idf = math.log(1 + (len(chunks) - df + 0.5) / (df + 0.5))
            score += idf * count * (k1 + 1) / (count + k1 * (1 - b + b * length / average))
        if score > 0:
            hits.append(VectorSearchHit(
                chunk_id=chunk["id"], knowledge_base_id=knowledge_base_id,
                document_id=chunk["document_id"], score=score,
                content_hash=chunk["content_hash"], text=chunk["text"],
                page_start=chunk["page_start"], page_end=chunk["page_end"],
                section_path=chunk["section_path"], kind=chunk["kind"],
                metadata={**chunk["metadata"], "pages": chunk["pages"], "score_kind": "bm25"},
            ))
    return sorted(hits, key=lambda hit: (-hit.score, hit.document_id, hit.chunk_id))[:top_k]
