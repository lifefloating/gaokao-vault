from __future__ import annotations

from pydantic import BaseModel, Field


class ScoreLineItem(BaseModel):
    province_id: int
    year: int = Field(ge=2000, le=2100)
    subject_category_id: int | None = None
    batch: str
    score: int | None = None
    note: str | None = None
    special_name: str | None = None


class ScoreSegmentItem(BaseModel):
    province_id: int
    year: int = Field(ge=2000, le=2100)
    subject_category_id: int | None = None
    score: int
    segment_count: int
    cumulative_count: int
