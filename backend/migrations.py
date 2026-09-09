"""Small, dependency-free SQLite schema migration runner."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def apply_migrations(
    connection: sqlite3.Connection,
    component: str,
    migrations: tuple[Migration, ...],
) -> None:
    """Apply ordered migrations once and reject divergent migration history."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            component TEXT NOT NULL,
            version INTEGER NOT NULL,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (component, version)
        )
        """
    )
    applied = {
        int(row[0]): str(row[1])
        for row in connection.execute(
            "SELECT version, name FROM schema_migrations WHERE component = ?",
            (component,),
        ).fetchall()
    }
    expected_versions = [migration.version for migration in migrations]
    if expected_versions != sorted(set(expected_versions)):
        raise RuntimeError(f"{component} migrations must have unique ordered versions")
    known = {migration.version: migration.name for migration in migrations}
    for version, name in applied.items():
        if known.get(version) != name:
            raise RuntimeError(
                f"unknown or renamed {component} migration: {version} ({name})"
            )
    for migration in migrations:
        if migration.version in applied:
            continue
        escaped_component = component.replace("'", "''")
        escaped_name = migration.name.replace("'", "''")
        try:
            connection.executescript(
                "BEGIN IMMEDIATE;\n"
                f"{migration.sql}\n"
                "INSERT INTO schema_migrations(component, version, name) "
                f"VALUES ('{escaped_component}', {migration.version}, "
                f"'{escaped_name}');\n"
                "COMMIT;"
            )
        except Exception:
            connection.rollback()
            raise
