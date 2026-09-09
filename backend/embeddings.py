"""Embedding provider contracts and built-in implementations."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class EmbeddingError(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbeddingProvider:
    """Deterministic local feature hashing for development and offline tests."""

    name = "hash"

    def __init__(self, model: str = "hash-v1", dimensions: int = 256):
        if dimensions < 8:
            raise ValueError("hash embedding dimensions must be at least 8")
        self.model = model
        self.dimensions = dimensions

    @staticmethod
    def _tokens(text: str) -> list[str]:
        normalized = unicodedata.normalize("NFKC", text).casefold()
        words = re.findall(r"[\w]+", normalized, flags=re.UNICODE)
        compact = re.sub(r"\s+", "", normalized)
        ngrams = [compact[index : index + 3] for index in range(len(compact) - 2)]
        return [*words, *ngrams]

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            if not isinstance(text, str) or not text.strip():
                raise EmbeddingError("embedding input must contain non-empty strings")
            vector = [0.0] * self.dimensions
            for token in self._tokens(text):
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                value = int.from_bytes(digest, "big")
                index = value % self.dimensions
                vector[index] += -1.0 if (value >> 32) & 1 else 1.0
            norm = math.sqrt(sum(value * value for value in vector))
            if norm == 0:
                raise EmbeddingError("embedding input produced an empty feature vector")
            vectors.append([value / norm for value in vector])
        return vectors


Transport = Callable[[Request, float], bytes]


def _default_transport(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:
        return response.read()


class OpenAICompatibleEmbeddingProvider:
    """Call an OpenAI-compatible `/embeddings` HTTP endpoint."""

    name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        dimensions: int,
        timeout_seconds: float = 60,
        transport: Transport = _default_transport,
    ):
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("embedding base URL must use http:// or https://")
        if dimensions < 1:
            raise ValueError("embedding dimensions must be positive")
        if timeout_seconds <= 0:
            raise ValueError("embedding timeout must be positive")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    @property
    def endpoint(self) -> str:
        if self.base_url.endswith("/embeddings"):
            return self.base_url
        return f"{self.base_url}/embeddings"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts or any(
            not isinstance(text, str) or not text.strip() for text in texts
        ):
            raise EmbeddingError("embedding input must contain non-empty strings")
        payload = json.dumps(
            {
                "model": self.model,
                "input": texts,
                "encoding_format": "float",
                "dimensions": self.dimensions,
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.endpoint, data=payload, headers=headers, method="POST")
        try:
            raw = self.transport(request, self.timeout_seconds)
        except HTTPError as exc:
            detail = exc.read(1000).decode("utf-8", errors="replace")
            raise EmbeddingError(
                f"embedding endpoint returned HTTP {exc.code}: {detail}"
            ) from exc
        except (OSError, URLError) as exc:
            raise EmbeddingError(f"embedding endpoint request failed: {exc}") from exc
        try:
            response: Any = json.loads(raw)
            entries = response["data"]
            ordered = sorted(entries, key=lambda item: int(item["index"]))
            if [int(item["index"]) for item in ordered] != list(range(len(texts))):
                raise ValueError("embedding indexes are missing or duplicated")
            vectors = [list(map(float, item["embedding"])) for item in ordered]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise EmbeddingError(
                "embedding endpoint returned an invalid response"
            ) from exc
        if len(vectors) != len(texts):
            raise EmbeddingError(
                f"embedding endpoint returned {len(vectors)} vectors for {len(texts)} inputs"
            )
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise EmbeddingError(
                    f"embedding dimension mismatch: expected {self.dimensions}, got {len(vector)}"
                )
            if any(not math.isfinite(value) for value in vector):
                raise EmbeddingError("embedding endpoint returned a non-finite value")
        return vectors


def create_embedding_provider(
    *,
    provider: str,
    model: str,
    dimensions: int,
    base_url: str | None,
    api_key: str | None,
    timeout_seconds: float,
) -> EmbeddingProvider:
    if provider == "hash":
        return HashEmbeddingProvider(model, dimensions)
    if provider == "openai_compatible":
        if not base_url:
            raise EmbeddingError(
                "PDF_INSPECTOR_EMBEDDING_BASE_URL is required for openai_compatible"
            )
        return OpenAICompatibleEmbeddingProvider(
            base_url=base_url,
            api_key=api_key,
            model=model,
            dimensions=dimensions,
            timeout_seconds=timeout_seconds,
        )
    raise EmbeddingError(f"unknown embedding provider: {provider}")
