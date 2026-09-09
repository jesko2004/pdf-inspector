"""Built-in and user-created extraction profile storage."""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from .profiles import Profile, load_profiles


class ProfileAlreadyExistsError(ValueError):
    pass


class ProfileNotFoundError(KeyError):
    pass


class BuiltinProfileError(ValueError):
    pass


class ProfileStore:
    def __init__(self, builtin_dir: Path, custom_dir: Path):
        self.builtin_dir = builtin_dir
        self.custom_dir = custom_dir
        self.custom_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def _load(self) -> tuple[dict[str, Profile], dict[str, Profile]]:
        builtins = load_profiles(self.builtin_dir)
        custom = load_profiles(self.custom_dir, allow_empty=True)
        duplicate_ids = set(builtins) & set(custom)
        if duplicate_ids:
            duplicate = min(duplicate_ids)
            raise ValueError(f"custom profile shadows built-in profile: {duplicate}")
        return builtins, custom

    def list(self) -> list[dict]:
        with self._lock:
            builtins, custom = self._load()
            rows = [
                {**profile.model_dump(mode="json"), "builtin": True}
                for profile in builtins.values()
            ]
            rows.extend(
                {**profile.model_dump(mode="json"), "builtin": False}
                for profile in custom.values()
            )
            return sorted(rows, key=lambda row: row["id"])

    def get(self, profile_id: str) -> Profile:
        with self._lock:
            builtins, custom = self._load()
            try:
                return custom.get(profile_id) or builtins[profile_id]
            except KeyError as exc:
                raise ProfileNotFoundError(profile_id) from exc

    def create(self, profile: Profile) -> Profile:
        with self._lock:
            builtins, custom = self._load()
            if profile.id in builtins or profile.id in custom:
                raise ProfileAlreadyExistsError(profile.id)
            self._write(profile)
            return profile

    def update(self, profile_id: str, profile: Profile) -> Profile:
        if profile.id != profile_id:
            raise ValueError("path profile id must match body id")
        with self._lock:
            builtins, custom = self._load()
            if profile_id in builtins:
                raise BuiltinProfileError("built-in profiles are read-only")
            if profile_id not in custom:
                raise ProfileNotFoundError(profile_id)
            self._write(profile)
            return profile

    def _write(self, profile: Profile) -> None:
        destination = self.custom_dir / f"{profile.id}.json"
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
