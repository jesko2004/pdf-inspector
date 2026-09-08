"""Validated business templates and deterministic field extraction."""

from __future__ import annotations

import math
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FieldRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aliases: list[str] = Field(min_length=1, max_length=30)
    type: Literal["text", "decimal", "date"] = "text"
    required: bool = False
    pages: list[int] | None = None
    section_start: str | None = None
    section_end: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    pattern: str | None = Field(default=None, max_length=256)
    min_value: Decimal | None = None
    max_value: Decimal | None = None

    @model_validator(mode="after")
    def validate_rule(self):
        if any(not alias.strip() for alias in self.aliases):
            raise ValueError("aliases must not be blank")
        self.aliases = list(dict.fromkeys(alias.strip() for alias in self.aliases))
        if self.pages is not None and (
            not self.pages or any(p < 1 for p in self.pages)
        ):
            raise ValueError("pages must contain positive, 1-indexed page numbers")
        if any(
            v is not None and not v.strip()
            for v in (self.section_start, self.section_end)
        ):
            raise ValueError("section boundaries must not be blank")
        if self.bbox is not None:
            x1, y1, x2, y2 = self.bbox
            if not all(math.isfinite(value) for value in self.bbox):
                raise ValueError("bbox coordinates must be finite")
            if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
                raise ValueError("bbox must be [x1, y1, x2, y2] with non-negative area")
            if not self.pages:
                raise ValueError("bbox requires an explicit pages list")
        if self.pattern is not None:
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError(f"invalid pattern: {exc}") from exc
        bounds = (self.min_value, self.max_value)
        if any(v is not None and not v.is_finite() for v in bounds):
            raise ValueError("numeric bounds must be finite")
        if any(v is not None for v in bounds) and self.type != "decimal":
            raise ValueError("numeric bounds require decimal type")
        if all(v is not None for v in bounds) and self.min_value > self.max_value:
            raise ValueError("min_value must not exceed max_value")
        return self


class TableColumnRule(BaseModel):
    """Canonical business column and the source headers that may represent it."""

    model_config = ConfigDict(extra="forbid")
    aliases: list[str] = Field(min_length=1, max_length=30)
    type: Literal["text", "decimal", "integer", "unit"] = "text"
    required: bool = False
    min_value: Decimal | None = None
    max_value: Decimal | None = None

    @model_validator(mode="after")
    def validate_rule(self):
        if any(not alias.strip() for alias in self.aliases):
            raise ValueError("aliases must not be blank")
        self.aliases = list(dict.fromkeys(alias.strip() for alias in self.aliases))
        bounds = (self.min_value, self.max_value)
        if any(value is not None and not value.is_finite() for value in bounds):
            raise ValueError("numeric bounds must be finite")
        if any(value is not None for value in bounds) and self.type not in {
            "decimal",
            "integer",
        }:
            raise ValueError("numeric bounds require decimal or integer type")
        if (
            all(value is not None for value in bounds)
            and self.min_value > self.max_value
        ):
            raise ValueError("min_value must not exceed max_value")
        return self


class TableRule(BaseModel):
    """Schema used to recognize and normalize a Markdown table."""

    model_config = ConfigDict(extra="forbid")
    columns: dict[str, TableColumnRule] = Field(min_length=1, max_length=50)
    required: bool = False

    @model_validator(mode="after")
    def validate_columns(self):
        for name in self.columns:
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
                raise ValueError("table column names must be lower-case identifiers")
        return self


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1)
    version: int = Field(ge=1)
    fields: dict[str, FieldRule] = Field(min_length=1, max_length=50)
    tables: dict[str, TableRule] = Field(default_factory=dict, max_length=20)

    @model_validator(mode="after")
    def unique_aliases(self):
        seen = set()
        for name, rule in self.fields.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
                raise ValueError("field names must be lower-case identifiers")
            for alias in rule.aliases:
                if alias.casefold() in seen:
                    raise ValueError(f"duplicate alias: {alias}")
                seen.add(alias.casefold())
        for table_name in self.tables:
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", table_name):
                raise ValueError("table names must be lower-case identifiers")
        return self


def load_profiles(directory: Path, *, allow_empty: bool = False) -> dict[str, Profile]:
    profiles = {}
    for path in sorted(directory.glob("*.json")):
        profile = Profile.model_validate_json(path.read_text(encoding="utf-8"))
        if profile.id in profiles:
            raise ValueError(f"duplicate profile id: {profile.id}")
        profiles[profile.id] = profile
    if not profiles and not allow_empty:
        raise ValueError(f"no profiles found in {directory}")
    return profiles


def normalize_value(raw: str, rule: FieldRule) -> str:
    value = raw.strip()
    if rule.pattern is not None and re.fullmatch(rule.pattern, value) is None:
        raise ValueError("pattern_mismatch")
    if rule.type == "text":
        return value
    if rule.type == "date":
        match = re.fullmatch(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})日?", value)
        if not match:
            raise ValueError("invalid_date")
        try:
            return date(*map(int, match.groups())).isoformat()
        except ValueError as exc:
            raise ValueError("invalid_date") from exc
    # Explicit decimal point and optional comma thousands grouping.
    value = re.sub(
        r"^(?:CNY|RMB|USD|HKD|EUR|[¥￥$€])\s*", "", value, flags=re.IGNORECASE
    )
    value = re.sub(r"\s*(?:元|CNY|RMB|USD|HKD|EUR)$", "", value, flags=re.IGNORECASE)
    if not re.fullmatch(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", value):
        raise ValueError("invalid_decimal")
    try:
        number = Decimal(value.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError("invalid_decimal") from exc
    if rule.min_value is not None and number < rule.min_value:
        raise ValueError("below_minimum")
    if rule.max_value is not None and number > rule.max_value:
        raise ValueError("above_maximum")
    return format(number, "f")


def extract_fields(
    markdown: str,
    profile: Profile,
    scoped_markdown: dict[str, str] | None = None,
) -> dict:
    """Match labeled values, retaining ambiguous candidates for human review."""
    aliases = {
        alias.casefold(): name
        for name, rule in profile.fields.items()
        for alias in rule.aliases
    }
    alternatives = "|".join(
        re.escape(a) for a in sorted(aliases, key=len, reverse=True)
    )
    # A label must be at line start or follow a delimiter, and have a separator.
    label_pattern = re.compile(
        r"(?<!\w)(" + alternatives + r")\s*(?:[:：]|\|)", re.IGNORECASE
    )
    candidates: dict[str, list[dict]] = {name: [] for name in profile.fields}

    def scan(source_markdown: str, allowed_fields: set[str]) -> None:
        active = {
            name: rule.section_start is None for name, rule in profile.fields.items()
        }
        page = None
        for source in source_markdown.splitlines():
            marker = re.fullmatch(r"\s*<!-- Page (\d+) -->\s*", source)
            if marker:
                page = int(marker.group(1))
                active = {
                    name: rule.section_start is None
                    for name, rule in profile.fields.items()
                }
                continue
            line = source.replace("**", "").replace("__", "").strip().lstrip("# ")
            for name, rule in profile.fields.items():
                if (
                    rule.section_start
                    and rule.section_start.casefold() in line.casefold()
                ):
                    active[name] = True
                if rule.section_end and rule.section_end.casefold() in line.casefold():
                    active[name] = False
            matches = list(label_pattern.finditer(line))
            for index, match in enumerate(matches):
                name = aliases[match.group(1).casefold()]
                if name not in allowed_fields:
                    continue
                rule = profile.fields[name]
                if not active[name] or (
                    rule.pages is not None and page not in rule.pages
                ):
                    continue
                stop = (
                    matches[index + 1].start()
                    if index + 1 < len(matches)
                    else len(line)
                )
                raw = line[match.end() : stop].strip().strip("|;； ")
                # In a key/value table only the adjacent cell is the value.
                raw = raw.split("|")[0].strip()
                if not raw:
                    continue
                candidate = {
                    "raw_value": raw,
                    "page": page,
                    "source_text": source,
                }
                if rule.bbox is not None:
                    candidate["bbox"] = list(rule.bbox)
                try:
                    candidate["value"] = normalize_value(raw, rule)
                except ValueError as exc:
                    candidate.update(value=None, reason=str(exc))
                candidates[name].append(candidate)

    scoped_markdown = scoped_markdown or {}
    unscoped_fields = set(profile.fields) - set(scoped_markdown)
    if unscoped_fields:
        scan(markdown, unscoped_fields)
    for field_name, source_markdown in scoped_markdown.items():
        if field_name in profile.fields:
            scan(source_markdown, {field_name})

    fields, issues = {}, []
    for name, rule in profile.fields.items():
        found = candidates[name]
        valid = {c["value"] for c in found if c["value"] is not None}
        reason = None
        if not found:
            reason = "required_field_missing" if rule.required else None
        elif any(c["value"] is None for c in found):
            reason = next(c["reason"] for c in found if c["value"] is None)
        elif len(valid) > 1:
            reason = "conflicting_values"
        chosen = found[0] if found else {}
        fields[name] = {
            "value": chosen.get("value") if reason is None else None,
            "page": chosen.get("page"),
            "source_text": chosen.get("source_text"),
            "status": "needs_review"
            if reason
            else ("extracted" if found else "missing"),
            "reason": reason,
            "candidates": found,
        }
        if reason:
            issues.append({"field": name, "reason": reason})
    return {
        "profile_id": profile.id,
        "profile_version": profile.version,
        "status": "needs_review" if issues else "ready",
        "fields": fields,
        "issues": issues,
    }
