from __future__ import annotations

from pydantic import BaseModel, Field


class MajorAdmissionResultItem(BaseModel):
    school_id: int
    major_id: int
    province_id: int
    year: int = Field(ge=2000, le=2100)
    subject_category_id: int | None = None
    batch: str
    min_score: int | None = None
    min_rank: int | None = None
    avg_score: int | None = None
    avg_rank: int | None = None
    max_score: int | None = None
    max_rank: int | None = None
    admitted_count: int | None = None
    major_name_raw: str | None = None
    subject_category_raw: str | None = None
    batch_raw: str | None = None
    remark: str | None = None
    source_url: str | None = None
