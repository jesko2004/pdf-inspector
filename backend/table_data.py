"""Convert extracted Markdown tables into normalized business rows."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .profiles import Profile, TableColumnRule, TableRule


@dataclass(frozen=True)
class MarkdownTable:
    page: int
    headers: list[str]
    rows: list[list[str]]
    markdown: str


_SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")
_HEADER_CLEANUP = re.compile(r"[\s_\-—–/\\:：()（）\[\]【】]+")
_CURRENCY_PREFIX = re.compile(
    r"^(?:CNY|RMB|USD\s*\$?|HKD|EUR|JPY|[¥￥$€])\s*", re.IGNORECASE
)
_CURRENCY_SUFFIX = re.compile(
    r"\s*(?:元|圆|CNY|RMB|USD|HKD|EUR|JPY)$", re.IGNORECASE
)
_UNIT_ALIASES = {
    "pcs": "件",
    "pc": "件",
    "piece": "件",
    "pieces": "件",
    "个": "件",
    "件": "件",
    "kg": "kg",
    "公斤": "kg",
    "千克": "kg",
    "g": "g",
    "克": "g",
    "t": "t",
    "吨": "t",
    "m": "m",
    "米": "m",
    "套": "套",
    "台": "台",
    "箱": "箱",
}


def _split_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith(r"\|"):
        stripped = stripped[:-1]
    return [
        cell.replace(r"\|", "|").strip()
        for cell in re.split(r"(?<!\\)\|", stripped)
    ]


def _is_separator(line: str) -> bool:
    cells = _split_row(line)
    return len(cells) >= 2 and all(_SEPARATOR_CELL.fullmatch(cell) for cell in cells)


def parse_markdown_tables(markdown: str, page: int) -> list[MarkdownTable]:
    """Parse GitHub-style tables while retaining their page and original Markdown."""
    lines = markdown.splitlines()
    tables: list[MarkdownTable] = []
    index = 0
    while index + 1 < len(lines):
        if "|" not in lines[index] or not _is_separator(lines[index + 1]):
            index += 1
            continue
        headers = _split_row(lines[index])
        table_lines = [lines[index], lines[index + 1]]
        rows: list[list[str]] = []
        index += 2
        while index < len(lines) and "|" in lines[index] and lines[index].strip():
            row = _split_row(lines[index])
            if len(row) < len(headers):
                row.extend([""] * (len(headers) - len(row)))
            rows.append(row[: len(headers)])
            table_lines.append(lines[index])
            index += 1
        if headers and rows:
            tables.append(
                MarkdownTable(page, headers, rows, "\n".join(table_lines).strip())
            )
    return tables


def _header_key(value: str) -> str:
    value = value.replace("**", "").replace("__", "").strip().casefold()
    return _HEADER_CLEANUP.sub("", value)


def _schema_mapping(headers: list[str], rule: TableRule) -> dict[str, int] | None:
    source_headers = [_header_key(header) for header in headers]
    mapping: dict[str, int] = {}
    claimed: set[int] = set()
    for name, column in rule.columns.items():
        aliases = {_header_key(alias) for alias in column.aliases}
        match = next(
            (
                index
                for index, header in enumerate(source_headers)
                if index not in claimed and header in aliases
            ),
            None,
        )
        if match is not None:
            mapping[name] = match
            claimed.add(match)
        elif column.required:
            return None
    return mapping or None


def _decimal(value: str, rule: TableColumnRule) -> str:
    cleaned = _CURRENCY_PREFIX.sub("", value.strip())
    cleaned = _CURRENCY_SUFFIX.sub("", cleaned)
    if not re.fullmatch(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", cleaned):
        raise ValueError("invalid_decimal")
    try:
        number = Decimal(cleaned.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError("invalid_decimal") from exc
    if rule.type == "integer" and number != number.to_integral_value():
        raise ValueError("invalid_integer")
    if rule.min_value is not None and number < rule.min_value:
        raise ValueError("below_minimum")
    if rule.max_value is not None and number > rule.max_value:
        raise ValueError("above_maximum")
    return format(number, "f")


def normalize_cell(value: str, rule: TableColumnRule) -> str | None:
    value = value.strip()
    if not value:
        return None
    if rule.type in {"decimal", "integer"}:
        return _decimal(value, rule)
    if rule.type == "unit":
        return _UNIT_ALIASES.get(value.casefold(), value)
    return value


def _generic_name(header: str, index: int, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", header.casefold()).strip("_")
    if not base:
        base = f"column_{index + 1}"
    if base[0].isdigit():
        base = f"column_{base}"
    name = base
    suffix = 2
    while name in used:
        name = f"{base}_{suffix}"
        suffix += 1
    used.add(name)
    return name


def extract_business_tables(
    page_markdown: list[tuple[int, str]], profile: Profile
) -> dict:
    """Recognize configured tables and preserve unmatched tables as raw business rows."""
    raw_tables = [
        table
        for page, markdown in page_markdown
        for table in parse_markdown_tables(markdown, page)
    ]
    items: list[dict] = []
    issues: list[dict] = []
    matched_schemas: set[str] = set()

    for table_index, table in enumerate(raw_tables, start=1):
        candidates = []
        for schema_name, rule in profile.tables.items():
            mapping = _schema_mapping(table.headers, rule)
            if mapping is not None:
                candidates.append((len(mapping), schema_name, rule, mapping))
        if candidates:
            _, schema_name, rule, mapping = max(candidates, key=lambda item: item[0])
            matched_schemas.add(schema_name)
            columns = list(rule.columns)
        else:
            schema_name = None
            rule = None
            used: set[str] = set()
            columns = [
                _generic_name(header, index, used)
                for index, header in enumerate(table.headers)
            ]
            mapping = {name: index for index, name in enumerate(columns)}

        table_id = f"{schema_name or 'table'}_{table_index}"
        normalized_rows = []
        table_issues = []
        for row_index, source_row in enumerate(table.rows, start=1):
            row = {}
            for name in columns:
                source_index = mapping.get(name)
                raw_value = (
                    source_row[source_index] if source_index is not None else ""
                )
                column_rule = rule.columns[name] if rule is not None else None
                try:
                    value = (
                        normalize_cell(raw_value, column_rule)
                        if column_rule is not None
                        else (raw_value.strip() or None)
                    )
                except ValueError as exc:
                    value = None
                    table_issues.append(
                        {
                            "row": row_index,
                            "column": name,
                            "reason": str(exc),
                            "raw_value": raw_value,
                        }
                    )
                if column_rule is not None and column_rule.required and value is None:
                    if not any(
                        issue["row"] == row_index and issue["column"] == name
                        for issue in table_issues
                    ):
                        table_issues.append(
                            {
                                "row": row_index,
                                "column": name,
                                "reason": "required_cell_missing",
                                "raw_value": raw_value,
                            }
                        )
                row[name] = value
            normalized_rows.append(row)
        item = {
            "id": table_id,
            "schema_id": schema_name,
            "page": table.page,
            "status": "needs_review" if table_issues else "ready",
            "source_headers": table.headers,
            "columns": columns,
            "rows": normalized_rows,
            "row_sources": [
                {"page": table.page, "row": index}
                for index in range(1, len(normalized_rows) + 1)
            ],
            "issues": table_issues,
            "markdown": table.markdown,
        }
        items.append(item)
        issues.extend({"table_id": table_id, **issue} for issue in table_issues)

    for schema_name, rule in profile.tables.items():
        if rule.required and schema_name not in matched_schemas:
            issues.append(
                {"schema_id": schema_name, "reason": "required_table_missing"}
            )

    return {
        "status": "needs_review" if issues else "ready",
        "items": items,
        "issues": issues,
    }


def table_to_csv(table: dict) -> str:
    """Serialize one normalized table using Excel-friendly UTF-8 text."""
    output = io.StringIO(newline="")
    columns = table.get("columns", [])
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(table.get("rows", []))
    return output.getvalue()
