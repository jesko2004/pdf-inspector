"""Verified backup and blue-green restore for local service data."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_sqlite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(source)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()


def create_backup(data_dir: Path, output: Path) -> dict:
    data_dir = data_dir.resolve()
    output = output.resolve()
    if not data_dir.is_dir():
        raise FileNotFoundError(f"data directory does not exist: {data_dir}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"backup already exists: {output}")
    with tempfile.TemporaryDirectory(prefix="pdf-inspector-backup-") as temporary:
        staging = Path(temporary) / "data"
        staging.mkdir()
        for source in sorted(data_dir.rglob("*")):
            if not source.is_file() or source.name.endswith(
                (".sqlite3-wal", ".sqlite3-shm")
            ):
                continue
            relative = source.relative_to(data_dir)
            destination = staging / relative
            if source.suffix == ".sqlite3":
                _copy_sqlite(source, destination)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        files = [
            {
                "path": path.relative_to(staging).as_posix(),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in sorted(staging.rglob("*"))
            if path.is_file()
        ]
        manifest = {
            "format_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "files": files,
        }
        manifest_path = Path(temporary) / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_output = output.with_suffix(output.suffix + ".tmp")
        with tarfile.open(temporary_output, "w:gz") as archive:
            archive.add(manifest_path, arcname="manifest.json")
            archive.add(staging, arcname="data")
        temporary_output.replace(output)
    verify_backup(output)
    return manifest


def _safe_relative(name: str) -> Path:
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"unsafe backup member: {name}")
    return Path(*pure.parts)


def _extract(archive_path: Path, destination: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            relative = _safe_relative(member.name)
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ValueError(f"unsupported backup member: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"cannot read backup member: {member.name}")
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output)


def _verify_directory(root: Path) -> dict:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format_version") != 1 or not isinstance(
        manifest.get("files"), list
    ):
        raise ValueError("unsupported or invalid backup manifest")
    declared = set()
    for entry in manifest["files"]:
        relative = _safe_relative(entry["path"])
        declared.add(relative.as_posix())
        path = root / "data" / relative
        if not path.is_file():
            raise ValueError(f"backup file missing: {relative.as_posix()}")
        if path.stat().st_size != entry["size"] or _sha256(path) != entry["sha256"]:
            raise ValueError(f"backup checksum mismatch: {relative.as_posix()}")
    actual = {
        path.relative_to(root / "data").as_posix()
        for path in (root / "data").rglob("*")
        if path.is_file()
    }
    if actual != declared:
        raise ValueError("backup contains undeclared files")
    return manifest


def verify_backup(archive_path: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="pdf-inspector-verify-") as temporary:
        root = Path(temporary)
        _extract(archive_path.resolve(), root)
        return _verify_directory(root)


def restore_backup(archive_path: Path, target_dir: Path) -> dict:
    target_dir = target_dir.resolve()
    if target_dir.exists() and any(target_dir.iterdir()):
        raise FileExistsError(
            "restore target must be empty; restore to a new directory and switch "
            "PDF_INSPECTOR_DATA_DIR after verification"
        )
    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="pdf-inspector-restore-", dir=target_dir.parent
    ) as temporary:
        root = Path(temporary)
        _extract(archive_path.resolve(), root)
        manifest = _verify_directory(root)
        for source in (root / "data").rglob("*"):
            if source.is_file():
                destination = target_dir / source.relative_to(root / "data")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("data_dir", type=Path)
    create.add_argument("output", type=Path)
    verify = subparsers.add_parser("verify")
    verify.add_argument("archive", type=Path)
    restore = subparsers.add_parser("restore")
    restore.add_argument("archive", type=Path)
    restore.add_argument("target_dir", type=Path)
    arguments = parser.parse_args()
    if arguments.command == "create":
        result = create_backup(arguments.data_dir, arguments.output)
    elif arguments.command == "verify":
        result = verify_backup(arguments.archive)
    else:
        result = restore_backup(arguments.archive, arguments.target_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
