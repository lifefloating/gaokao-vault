from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class SpecialEnrollmentItem(BaseModel):
    enrollment_type: str
    school_id: int | None = None
    year: int = Field(ge=2000, le=2100)
    title: str | None = None
    content: str | None = None
    publish_date: date | None = None
    source_url: str | None = None
