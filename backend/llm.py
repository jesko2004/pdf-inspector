"""LLM provider contracts for grounded RAG answers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LlmError(RuntimeError):
    pass


@dataclass(frozen=True)
class LlmResult:
    text: str
    usage: dict[str, int]


class LlmProvider(Protocol):
    name: str
    model: str

    def generate(
        self, messages: list[dict[str, str]], *, max_tokens: int
    ) -> LlmResult: ...

    def stream(
        self, messages: list[dict[str, str]], *, max_tokens: int
    ) -> Iterable[str]: ...


class ExtractiveLlmProvider:
    """Offline provider that returns source text without inventing facts."""

    name = "extractive"

    def __init__(self, model: str = "extractive-v1"):
        self.model = model

    @staticmethod
    def _answer(messages: list[dict[str, str]]) -> str:
        prompt = messages[-1]["content"]
        marker = "<source "
        start = prompt.find(marker)
        if start < 0:
            return (
                "知识库中没有足够信息 / Not enough information in the knowledge base."
            )
        content_start = prompt.find("\n", start)
        content_end = prompt.find("</source>", content_start)
        if content_start < 0 or content_end < 0:
            return (
                "知识库中没有足够信息 / Not enough information in the knowledge base."
            )
        evidence = prompt[content_start + 1 : content_end].strip()
        return evidence[:2000]

    def generate(self, messages: list[dict[str, str]], *, max_tokens: int) -> LlmResult:
        answer = truncate_to_tokens(self._answer(messages), max_tokens)
        return LlmResult(answer, {"completion_tokens": estimate_tokens(answer)})

    def stream(
        self, messages: list[dict[str, str]], *, max_tokens: int
    ) -> Iterable[str]:
        answer = truncate_to_tokens(self._answer(messages), max_tokens)
        for start in range(0, len(answer), 24):
            yield answer[start : start + 24]


Transport = Callable[[Request, float], bytes]
StreamTransport = Callable[[Request, float], Iterable[bytes]]


def _default_transport(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _default_stream_transport(request: Request, timeout: float) -> Iterable[bytes]:
    with urlopen(request, timeout=timeout) as response:
        yield from response


class OpenAICompatibleLlmProvider:
    name = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout_seconds: float = 120,
        transport: Transport = _default_transport,
        stream_transport: StreamTransport = _default_stream_transport,
    ):
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("LLM base URL must use http:// or https://")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.stream_transport = stream_transport

    @property
    def endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def _request(
        self, messages: list[dict[str, str]], max_tokens: int, *, stream: bool
    ) -> Request:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )

    @staticmethod
    def _request_error(exc: Exception) -> LlmError:
        if isinstance(exc, HTTPError):
            detail = exc.read(1000).decode("utf-8", errors="replace")
            return LlmError(f"LLM endpoint returned HTTP {exc.code}: {detail}")
        return LlmError(f"LLM endpoint request failed: {exc}")

    def generate(self, messages: list[dict[str, str]], *, max_tokens: int) -> LlmResult:
        try:
            raw = self.transport(
                self._request(messages, max_tokens, stream=False),
                self.timeout_seconds,
            )
        except (HTTPError, URLError, OSError) as exc:
            raise self._request_error(exc) from exc
        try:
            payload = json.loads(raw)
            text = payload["choices"][0]["message"]["content"].strip()
            usage = {key: int(value) for key, value in payload.get("usage", {}).items()}
        except (
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise LlmError("LLM endpoint returned an invalid response") from exc
        if not text:
            raise LlmError("LLM endpoint returned an empty answer")
        return LlmResult(text, usage)

    def stream(
        self, messages: list[dict[str, str]], *, max_tokens: int
    ) -> Iterable[str]:
        try:
            lines = self.stream_transport(
                self._request(messages, max_tokens, stream=True),
                self.timeout_seconds,
            )
            for raw_line in lines:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                payload = json.loads(data)
                choices = payload.get("choices", [])
                if not choices:
                    continue
                content = choices[0].get("delta", {}).get("content")
                if content:
                    yield str(content)
        except (HTTPError, URLError, OSError) as exc:
            raise self._request_error(exc) from exc
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LlmError("LLM stream returned an invalid event") from exc


def estimate_tokens(text: str) -> int:
    ascii_count = sum(ord(character) < 128 for character in text)
    non_ascii_count = len(text) - ascii_count
    return max(1, (ascii_count + 3) // 4 + non_ascii_count)


def truncate_to_tokens(text: str, budget: int) -> str:
    if budget <= 0:
        return ""
    if estimate_tokens(text) <= budget:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_tokens(text[:middle]) <= budget:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip()


def create_llm_provider(
    *,
    provider: str,
    model: str,
    base_url: str | None,
    api_key: str | None,
    timeout_seconds: float,
) -> LlmProvider:
    if provider == "extractive":
        return ExtractiveLlmProvider(model)
    if provider == "openai_compatible":
        if not base_url:
            raise LlmError(
                "PDF_INSPECTOR_LLM_BASE_URL is required for openai_compatible"
            )
        return OpenAICompatibleLlmProvider(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    raise LlmError(f"unknown LLM provider: {provider}")
