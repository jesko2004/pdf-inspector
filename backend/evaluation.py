"""Versioned benchmark inputs and explicit human review contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator


def load_json(path) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("nonfinite JSON number")

    value = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs, parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


class EvaluationDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=100)
    path: str = Field(min_length=1, max_length=500)
    family: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("path")
    @classmethod
    def relative_pdf_path(cls, value: str) -> str:
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or ":" in value or path.suffix.lower() != ".pdf":
            raise ValueError("document path must be a relative PDF path inside the repository")
        return str(path)


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    split: Literal["tuning", "check"]
    query: str = Field(min_length=1, max_length=4000)
    document: str = Field(min_length=1, max_length=100)
    pages: list[StrictInt] = Field(max_length=100)
    required_text: list[str] = Field(max_length=20)
    expected_answer_fragments: list[str] = Field(max_length=20)
    answerable: StrictBool
    category: str = Field(default="general", min_length=1, max_length=100)
    language: str = Field(default="unspecified", min_length=1, max_length=40)

    @field_validator("id", "query", "document", "category", "language")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("required_text", "expected_answer_fragments")
    @classmethod
    def nonblank_fragments(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 2000 for value in values):
            raise ValueError("fragments must be nonblank and at most 2000 characters")
        return values

    @model_validator(mode="after")
    def source_contract(self):
        if any(page < 1 for page in self.pages) or len(set(self.pages)) != len(self.pages):
            raise ValueError("pages must be unique positive integers")
        if self.answerable and (not self.pages or not self.required_text or not self.expected_answer_fragments):
            raise ValueError("answerable cases require pages, source text and answer fragments")
        if not self.answerable and (self.pages or self.required_text or self.expected_answer_fragments):
            raise ValueError("unanswerable cases must not declare answer evidence")
        return self


class EvaluationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=100)
    scenario: str = Field(min_length=1, max_length=1000)
    annotation_status: str = Field(min_length=1, max_length=300)
    scope: str = Field(min_length=1, max_length=2000)
    documents: list[EvaluationDocument] = Field(min_length=1, max_length=500)
    cases: list[EvaluationCase] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def unique_references(self):
        keys = [document.key for document in self.documents]
        ids = [case.id for case in self.cases]
        if len(set(keys)) != len(keys) or len(set(ids)) != len(ids):
            raise ValueError("document keys and case IDs must be unique")
        if any(case.document not in keys for case in self.cases):
            raise ValueError("case refers to an unknown document")
        return self


def validate_dataset(value: dict) -> dict:
    return EvaluationDataset.model_validate(value).model_dump(exclude_none=True)


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


class CaseReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=100)
    reviewer: str = Field(default="", max_length=120)
    reviewed_at: datetime | None = None
    label_verdict: Literal["unreviewed", "confirmed", "incorrect", "uncertain"] = "unreviewed"
    answer_verdict: Literal["unreviewed", "correct", "incorrect", "uncertain"] = "unreviewed"
    citation_verdict: Literal["unreviewed", "supported", "unsupported", "uncertain", "not_applicable"] = "unreviewed"
    failure_stage: Literal["source", "retrieval", "context", "generation", "citation", "refusal", "label", "execution", "unknown"] | None = None
    comment: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def explicit_review(self):
        assessed = any(value != "unreviewed" for value in (self.label_verdict, self.answer_verdict, self.citation_verdict))
        if assessed and (not self.reviewer.strip() or self.reviewed_at is None):
            raise ValueError("assessed reviews require reviewer and reviewed_at")
        if self.reviewed_at is not None and (self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None):
            raise ValueError("reviewed_at must include a timezone")
        if self.failure_stage is not None and not self.comment.strip():
            raise ValueError("failure classification requires a comment")
        return self


class EvaluationReviews(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviews: list[CaseReview] = Field(max_length=2000)

    @model_validator(mode="after")
    def unique_reviews(self):
        ids = [review.case_id for review in self.reviews]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate case reviews")
        return self
