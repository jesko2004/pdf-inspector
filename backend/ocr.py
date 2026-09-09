"""Pluggable per-page OCR integration for mixed and scanned PDFs."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import Settings


@dataclass(frozen=True)
class OcrPage:
    page: int
    markdown: str
    confidence: float | None = None


class OcrProvider(Protocol):
    name: str

    def extract_pages(self, pdf_path: Path, pages: list[int]) -> list[OcrPage]: ...


class CommandOcrProvider:
    """Run an OCR adapter without a shell and consume its JSON stdout."""

    name = "command"

    def __init__(self, command: tuple[str, ...], timeout_seconds: int = 180):
        if not command:
            raise ValueError("OCR command must not be empty")
        self.command = command
        self.timeout_seconds = timeout_seconds

    def extract_pages(self, pdf_path: Path, pages: list[int]) -> list[OcrPage]:
        page_list = ",".join(map(str, pages))
        command = [
            argument.replace("{pdf}", str(pdf_path)).replace("{pages}", page_list)
            for argument in self.command
        ]
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=self.timeout_seconds,
        )
        payload = json.loads(completed.stdout)
        entries = payload.get("pages") if isinstance(payload, dict) else payload
        if not isinstance(entries, list):
            raise ValueError(
                "OCR command must return a JSON list or a {pages: [...]} object"
            )
        requested = set(pages)
        results = []
        for entry in entries:
            page = int(entry["page"])
            markdown = str(entry.get("markdown") or entry.get("text") or "").strip()
            if page not in requested or not markdown:
                continue
            confidence = entry.get("confidence")
            results.append(
                OcrPage(
                    page=page,
                    markdown=markdown,
                    confidence=float(confidence) if confidence is not None else None,
                )
            )
        return results


def create_ocr_provider(settings: Settings) -> OcrProvider | None:
    if settings.ocr_command is None:
        return None
    return CommandOcrProvider(settings.ocr_command, settings.ocr_timeout_seconds)
