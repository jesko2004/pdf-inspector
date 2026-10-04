"""Exact, same-row table predicates and evidence projection.

Column identities are positional (column_1, column_2, ...). Units are a small
explicit allowlist; currency conversion and guesses from bare $/¥ are forbidden.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, localcontext
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class TableQueryError(ValueError):
    """Invalid or ambiguous user-supplied table conditions."""


def text_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


# Scales are exact Decimal strings, never binary floating point.
_UNITS = {
    "g": ("mass", "1"), "kg": ("mass", "1000"), "t": ("mass", "1000000"),
    "mm": ("length", "0.001"), "cm": ("length", "0.01"),
    "m": ("length", "1"), "km": ("length", "1000"),
    "ml": ("volume", "0.001"), "l": ("volume", "1"),
    "pa": ("pressure", "1"), "kpa": ("pressure", "1000"),
    "mpa": ("pressure", "1000000"), "pcs": ("count", "1"),
}
_UNIT_ALIASES = {"克": "g", "千克": "kg", "公斤": "kg", "吨": "t",
                 "毫米": "mm", "厘米": "cm", "米": "m", "千米": "km",
                 "毫升": "ml", "升": "l", "件": "pcs"}
_CURRENCIES = {"cny": "CNY", "rmb": "CNY", "元": "CNY", "人民币": "CNY",
               "usd": "USD", "us$": "USD", "美元": "USD",
               "eur": "EUR", "€": "EUR", "欧元": "EUR",
               "gbp": "GBP", "£": "GBP", "jpy": "JPY", "日元": "JPY",
               "hkd": "HKD", "港币": "HKD", "krw": "KRW", "₩": "KRW"}
_NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_QUANTITY = re.compile(rf"^([^\d+\-]*?)\s*({_NUMBER})\s*([^\d]*?)$")


def _decimal(value: str) -> Decimal:
    value = unicodedata.normalize("NFKC", value).strip()
    if len(value) > 80 or re.fullmatch(_NUMBER, value) is None:
        raise TableQueryError("numeric values must be finite decimal strings (e.g. 950.00)")
    return Decimal(value.replace(",", ""))


def _unit(value: str) -> str:
    key = text_key(value)
    key = _UNIT_ALIASES.get(key, key)
    if key not in _UNITS:
        raise TableQueryError(f"unsupported table unit: {value}")
    return key


def _currency(value: str) -> str:
    key = text_key(value)
    if key not in _CURRENCIES:
        raise TableQueryError(f"unsupported or ambiguous table currency: {value}")
    return _CURRENCIES[key]


class TableCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    op: Literal["eq", "contains", "gt", "gte", "lt", "lte", "between"] = "eq"
    value: str | None = Field(default=None, max_length=2000)
    min_value: str | None = Field(default=None, max_length=80)
    max_value: str | None = Field(default=None, max_length=80)
    value_type: Literal["text", "number"] = "text"
    unit: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, max_length=40)
    unit_column: str | None = Field(default=None, max_length=200)
    currency_column: str | None = Field(default=None, max_length=200)

    @property
    def numeric(self) -> bool:
        return self.value_type == "number" or self.op not in {"eq", "contains"}

    @model_validator(mode="after")
    def validate_condition(self):
        if self.op == "between":
            if self.value is not None or self.min_value is None or self.max_value is None:
                raise ValueError("between requires min_value and max_value only")
            if _decimal(self.min_value) > _decimal(self.max_value):
                raise ValueError("min_value must not exceed max_value")
        else:
            if self.value is None or not self.value.strip():
                raise ValueError("table condition value must not be blank")
            if self.min_value is not None or self.max_value is not None:
                raise ValueError("bounds are only allowed for between")
            if self.numeric:
                _decimal(self.value)
        if self.op == "contains" and self.numeric:
            raise ValueError("contains only supports text")
        if not self.numeric and any((self.unit, self.currency, self.unit_column, self.currency_column)):
            raise ValueError("units and currencies require a numeric predicate")
        if self.unit:
            _unit(self.unit)
        if self.currency:
            _currency(self.currency)
        if self.unit_column is not None and (not self.unit_column.strip() or not self.unit):
            raise ValueError("unit_column requires a nonblank column and unit")
        if self.currency_column is not None and (not self.currency_column.strip() or not self.currency):
            raise ValueError("currency_column requires a nonblank column and currency")
        if self.unit is not None and not self.unit.strip():
            raise ValueError("unit must not be blank")
        if self.currency is not None and not self.currency.strip():
            raise ValueError("currency must not be blank")
        return self


TableFilters = Mapping[str, str | TableCondition | dict[str, Any]]


def compile_filters(values: TableFilters | None) -> dict[str, TableCondition]:
    result = {}
    for key, value in (values or {}).items():
        if not isinstance(key, str) or not key.strip():
            raise TableQueryError("table column must not be blank")
        key = key.strip()
        if key in result:
            raise TableQueryError("duplicate table columns after trimming")
        try:
            result[key] = value if isinstance(value, TableCondition) else TableCondition.model_validate(
                {"value": value} if isinstance(value, str) else value
            )
        except (ValidationError, ValueError) as exc:
            raise TableQueryError(f"invalid table condition for {key}: {exc}") from exc
    return result


def table_rows(table: dict) -> tuple[list[str], list[list[str]]]:
    headers = table.get("headers", [])
    if not isinstance(headers, list) or not all(isinstance(h, str) for h in headers):
        return [], []
    # Reconstruct old metadata from cells, which preserve duplicate columns.
    cells = table.get("cells", [])
    if cells:
        positions = {(c["row"], c["column"]): str(c.get("value", "")) for c in cells}
        row_numbers = sorted({row for row, _column in positions})
        return headers, [[positions.get((r, c + 1), "") for c in range(len(headers))] for r in row_numbers]
    values = table.get("row_values")
    if isinstance(values, list):
        return headers, [[str(row[c]) if c < len(row) else "" for c in range(len(headers))] for row in values]
    if len(set(map(text_key, headers))) != len(headers):
        raise TableQueryError("legacy table has duplicate headers without positional cells; re-ingest it")
    return headers, [[str(row.get(h, "")) for h in headers] for row in table.get("rows", [])]


def _column(headers: list[str], name: str) -> int | None:
    positional = re.fullmatch(r"column_([1-9]\d*)", name)
    if positional:
        index = int(positional[1]) - 1
        return index if index < len(headers) else None
    matches = [i for i, h in enumerate(headers) if text_key(h) == text_key(name)]
    if len(matches) > 1:
        raise TableQueryError(f"ambiguous table column {name}; use column_1, column_2, etc.")
    return matches[0] if matches else None


def _numeric_match(raw: str, condition: TableCondition, row: list[str], headers: list[str]) -> bool:
    parsed = _QUANTITY.fullmatch(unicodedata.normalize("NFKC", raw).strip())
    if not parsed:
        return False
    prefix, number, suffix = parsed.groups()
    try:
        amount = _decimal(number)
        source_unit = None
        source_currency = None
        ambiguous_symbol = None
        for token in (prefix.strip(), suffix.strip()):
            if not token:
                continue
            if token in {"$", "¥"}:
                ambiguous_symbol = token
            elif text_key(token) in _CURRENCIES:
                currency = _currency(token)
                if source_currency is not None and source_currency != currency:
                    return False
                source_currency = currency
            else:
                unit = _unit(token)
                if source_unit is not None and source_unit != unit:
                    return False
                source_unit = unit
        for column_name, kind in ((condition.unit_column, "unit"), (condition.currency_column, "currency")):
            if column_name is None:
                continue
            index = _column(headers, column_name)
            if index is None or not row[index].strip():
                return False
            if kind == "unit":
                unit = _unit(row[index])
                if source_unit is not None and source_unit != unit:
                    return False
                source_unit = unit
            else:
                currency = _currency(row[index])
                if source_currency is not None and source_currency != currency:
                    return False
                source_currency = currency
        if ambiguous_symbol and (source_currency is None or
                (ambiguous_symbol == "¥" and source_currency not in {"CNY", "JPY"}) or
                (ambiguous_symbol == "$" and source_currency not in {"USD", "HKD"})):
            return False
        expected_currency = _currency(condition.currency) if condition.currency else None
        if source_currency != expected_currency:
            return False
        expected_unit = _unit(condition.unit) if condition.unit else None
        if (source_unit is None) != (expected_unit is None):
            return False
        if source_unit is not None and expected_unit is not None:
            source_dimension, source_scale = _UNITS[source_unit]
            dimension, scale = _UNITS[expected_unit]
            if source_dimension != dimension:
                return False
            with localcontext() as context:
                context.prec = 100
                amount = amount * Decimal(source_scale) / Decimal(scale)
        if condition.op == "between":
            return _decimal(condition.min_value) <= amount <= _decimal(condition.max_value)
        expected = _decimal(condition.value)
        return {"eq": amount == expected, "gt": amount > expected, "gte": amount >= expected,
                "lt": amount < expected, "lte": amount <= expected}[condition.op]
    except TableQueryError:
        # An unrecognized source value is unknown, never an inferred match.
        return False


def matching_rows(metadata: dict, filters: TableFilters | None) -> list[dict]:
    predicates = compile_filters(filters)
    table = metadata.get("table")
    if not isinstance(table, dict):
        return []
    headers, rows = table_rows(table)
    compiled = []
    for name, condition in predicates.items():
        index = _column(headers, name)
        if index is None:
            return []
        # Validate sibling column identities even when no row satisfies the query.
        for sibling in (condition.unit_column, condition.currency_column):
            if sibling is not None and _column(headers, sibling) is None:
                return []
        compiled.append((index, condition))
    result = []
    for number, row in enumerate(rows, 1):
        if all(_numeric_match(row[index], condition, row, headers) if condition.numeric else
               (text_key(row[index]) == text_key(condition.value) if condition.op == "eq" else
                text_key(condition.value) in text_key(row[index])) for index, condition in compiled):
            result.append({"row": number, "cells": [
                {"column_id": f"column_{i + 1}", "column": i + 1, "header": h, "value": row[i]}
                for i, h in enumerate(headers)
            ]})
    return result


def project_rows(metadata: dict, filters: TableFilters) -> tuple[str, list[dict]]:
    rows = matching_rows(metadata, filters)
    headers = metadata["table"]["headers"]
    def escaped(value):
        return value.replace("|", r"\|").replace("\n", " ")
    lines = ["| " + " | ".join(escaped(h) for h in headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(escaped(c["value"]) for c in row["cells"]) + " |")
    return "\n".join(lines), rows
