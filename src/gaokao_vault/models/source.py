from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class DataSourceItem(BaseModel):
    source_code: str
    source_name: str
    source_type: str
    authority_level: int = Field(ge=0, le=100)
    province_code: str | None = None
    base_url: str
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceDocumentItem(BaseModel):
    data_source_id: int
    source_url: str
    title: str | None = None
    publish_date: date | None = None
    fetched_at: datetime | None = None
    content_hash: str
    content_type: str | None = None
    storage_key: str | None = None
    parser_name: str | None = None
    parser_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityEvidenceItem(BaseModel):
    entity_type: str
    entity_id: int
    source_document_id: int
    field_name: str | None = None
    extracted_value_hash: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    quality_flags: list[str] = Field(default_factory=list)
