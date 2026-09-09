"""Validated request models for the built-in knowledge-base API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
