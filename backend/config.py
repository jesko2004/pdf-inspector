"""Runtime configuration for the PDF task service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    builtin_profile_dir: Path
    max_upload_bytes: int = 50 * 1024 * 1024
    worker_count: int = 2

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
        if max_upload_mb < 1:
            raise ValueError("PDF_INSPECTOR_MAX_UPLOAD_MB must be positive")
        if workers < 1:
            raise ValueError("PDF_INSPECTOR_WORKERS must be positive")
        return cls(
            data_dir=data_dir,
            builtin_profile_dir=profile_dir,
            max_upload_bytes=max_upload_mb * 1024 * 1024,
            worker_count=workers,
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
