"""Runtime configuration for the PDF task service."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    builtin_profile_dir: Path
    max_upload_bytes: int = 50 * 1024 * 1024
    worker_count: int = 2
    ocr_provider: str = "none"
    ocr_command: tuple[str, ...] | None = None
    ocr_timeout_seconds: int = 180
    ocr_dpi: int = 200
    ocr_min_confidence: float = 0.5

    @classmethod
    def from_env(cls) -> Settings:
        project_dir = Path(__file__).resolve().parent.parent
        data_dir = Path(
            os.environ.get(
                "PDF_INSPECTOR_DATA_DIR", project_dir / ".pdf-inspector-data"
            )
        )
        profile_dir = Path(
            os.environ.get(
                "PDF_INSPECTOR_BUILTIN_PROFILE_DIR",
                project_dir / "backend" / "profiles",
            )
        )
        max_upload_mb = int(os.environ.get("PDF_INSPECTOR_MAX_UPLOAD_MB", "50"))
        workers = int(os.environ.get("PDF_INSPECTOR_WORKERS", "2"))
        ocr_provider_raw = os.environ.get("PDF_INSPECTOR_OCR_PROVIDER")
        ocr_timeout = int(os.environ.get("PDF_INSPECTOR_OCR_TIMEOUT_SECONDS", "180"))
        ocr_dpi = int(os.environ.get("PDF_INSPECTOR_OCR_DPI", "200"))
        ocr_min_confidence = float(
            os.environ.get("PDF_INSPECTOR_OCR_MIN_CONFIDENCE", "0.5")
        )
        ocr_command_raw = os.environ.get("PDF_INSPECTOR_OCR_COMMAND_JSON")
        ocr_command = None
        if ocr_command_raw:
            parsed = json.loads(ocr_command_raw)
            if not isinstance(parsed, list) or not parsed or not all(
                isinstance(argument, str) and argument for argument in parsed
            ):
                raise ValueError(
                    "PDF_INSPECTOR_OCR_COMMAND_JSON must be a non-empty JSON string array"
                )
            ocr_command = tuple(parsed)
        ocr_provider = (
            ocr_provider_raw.strip().lower()
            if ocr_provider_raw
            else ("command" if ocr_command is not None else "none")
        )
        if max_upload_mb < 1:
            raise ValueError("PDF_INSPECTOR_MAX_UPLOAD_MB must be positive")
        if workers < 1:
            raise ValueError("PDF_INSPECTOR_WORKERS must be positive")
        if ocr_timeout < 1:
            raise ValueError("PDF_INSPECTOR_OCR_TIMEOUT_SECONDS must be positive")
        if ocr_provider not in {"none", "rapidocr", "command"}:
            raise ValueError(
                "PDF_INSPECTOR_OCR_PROVIDER must be one of: none, rapidocr, command"
            )
        if not 72 <= ocr_dpi <= 600:
            raise ValueError("PDF_INSPECTOR_OCR_DPI must be between 72 and 600")
        if not 0 <= ocr_min_confidence <= 1:
            raise ValueError(
                "PDF_INSPECTOR_OCR_MIN_CONFIDENCE must be between 0 and 1"
            )
        return cls(
            data_dir=data_dir,
            builtin_profile_dir=profile_dir,
            max_upload_bytes=max_upload_mb * 1024 * 1024,
            worker_count=workers,
            ocr_provider=ocr_provider,
            ocr_command=ocr_command,
            ocr_timeout_seconds=ocr_timeout,
            ocr_dpi=ocr_dpi,
            ocr_min_confidence=ocr_min_confidence,
        )

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def result_dir(self) -> Path:
        return self.data_dir / "results"

    @property
    def custom_profile_dir(self) -> Path:
        return self.data_dir / "profiles"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "tasks.sqlite3"

    def create_directories(self) -> None:
        for path in (
            self.data_dir,
            self.upload_dir,
            self.result_dir,
            self.custom_profile_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
