"""API-key authentication and role-based authorization primitives."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

ROLES = {"read": 1, "write": 2, "admin": 3}


@dataclass(frozen=True)
class Principal:
    key_id: str
    role: str


class ApiKeyAuthenticator:
    def __init__(self, keys: tuple[tuple[str, str, str], ...]):
        self._keys = keys

    @property
    def enabled(self) -> bool:
        return bool(self._keys)

    def authenticate(self, supplied_key: str | None) -> Principal | None:
        if not supplied_key:
            return None
        matched: Principal | None = None
        for key_id, secret, role in self._keys:
            if hmac.compare_digest(secret, supplied_key):
                matched = Principal(key_id, role)
        return matched

    @staticmethod
    def extract(headers) -> str | None:
        authorization = headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            return authorization[7:].strip()
        value = headers.get("x-api-key")
        return value.strip() if value else None


def has_permission(principal: Principal, required: str) -> bool:
    return ROLES[principal.role] >= ROLES[required]


def required_permission(method: str, path: str) -> str | None:
    if path in {"/health", "/docs", "/redoc", "/openapi.json"}:
        return None
    if path in {"/metrics", "/v1/audit-events"} or method == "DELETE":
        return "admin"
    if method in {"GET", "HEAD", "OPTIONS"}:
        return "read"
    if path.endswith(("/search", "/ask", "/retrieval-evaluations")):
        return "read"
    return "write"


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
