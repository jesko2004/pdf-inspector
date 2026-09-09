"""Validated request models for the built-in knowledge-base API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class KnowledgeBaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    embedding_provider: str | None = None
    embedding_model: str | None = Field(default=None, max_length=200)
    embedding_dimensions: int | None = Field(default=None, ge=8, le=4096)

    @field_validator("name", "embedding_provider", "embedding_model")
    @classmethod
    def strip_nonblank_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str) -> str:
        return value.strip()


class KnowledgeBaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class KnowledgeDocumentIngest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1, max_length=100)
    document_key: str | None = Field(default=None, max_length=300)

    @field_validator("task_id", "document_key")
    @classmethod
    def strip_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped


class KnowledgeBaseReindex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    embedding_provider: str | None = None
    embedding_model: str | None = Field(default=None, max_length=200)
    embedding_dimensions: int | None = Field(default=None, ge=8, le=4096)

    @field_validator("embedding_provider", "embedding_model")
    @classmethod
    def strip_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=10, ge=1, le=100)
    min_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    kinds: list[str] = Field(default_factory=list, max_length=20)
    section_path_prefix: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be blank")
        return stripped

    @field_validator("document_ids", "kinds", "section_path_prefix")
    @classmethod
    def normalize_string_lists(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            stripped = value.strip()
            if not stripped:
                raise ValueError("filter values must not be blank")
            if stripped not in normalized:
                normalized.append(stripped)
        return normalized

    @model_validator(mode="after")
    def validate_page_range(self) -> KnowledgeSearchRequest:
        if (
            self.page_start is not None
            and self.page_end is not None
            and self.page_start > self.page_end
        ):
            raise ValueError("page_start must not be greater than page_end")
        return self


class RetrievalExpectedSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1, max_length=100)
    pages: list[int] = Field(default_factory=list, max_length=100)

    @field_validator("document_id")
    @classmethod
    def strip_document_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("document_id must not be blank")
        return stripped

    @field_validator("pages")
    @classmethod
    def validate_pages(cls, values: list[int]) -> list[int]:
        if any(page < 1 for page in values):
            raise ValueError("expected pages must be positive")
        return sorted(set(values))


class RetrievalEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=1, max_length=4000)
    expected_sources: list[RetrievalExpectedSource] = Field(
        min_length=1, max_length=100
    )

    @field_validator("id", "query")
    @classmethod
    def strip_nonblank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped


class KnowledgeRetrievalEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[RetrievalEvaluationCase] = Field(min_length=1, max_length=500)
    top_k: int = Field(default=10, ge=1, le=100)
    min_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    kinds: list[str] = Field(default_factory=list, max_length=20)
    section_path_prefix: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("document_ids", "kinds", "section_path_prefix")
    @classmethod
    def normalize_string_lists(cls, values: list[str]) -> list[str]:
        return KnowledgeSearchRequest.normalize_string_lists(values)

    @model_validator(mode="after")
    def validate_page_range(self) -> KnowledgeRetrievalEvaluationRequest:
        if (
            self.page_start is not None
            and self.page_end is not None
            and self.page_start > self.page_end
        ):
            raise ValueError("page_start must not be greater than page_end")
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("evaluation case IDs must be unique")
        return self
