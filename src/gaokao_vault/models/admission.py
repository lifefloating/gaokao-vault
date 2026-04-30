from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MajorAdmissionResultItem(BaseModel):
    school_id: int
    major_id: int
    province_id: int
    year: int = Field(ge=2000, le=2100)
    subject_category_id: int | None = None
    batch: str
    batch_code: str | None = None
    batch_category: str | None = None
    batch_segment: str | None = None
    min_score: int | None = None
    min_rank: int | None = None
    avg_score: int | None = None
    avg_rank: int | None = None
    max_score: int | None = None
    max_rank: int | None = None
    admitted_count: int | None = None
    plan_count: int | None = None
    school_code_raw: str | None = None
    school_name_raw: str | None = None
    major_group_code: str | None = None
    major_code_raw: str | None = None
    campus: str | None = None
    program_type: str | None = None
    eligibility_requirements: str | None = None
    physical_exam_or_political_review: str | None = None
    political_review_requirement: str | None = None
    service_obligation: str | None = None
    major_name_raw: str | None = None
    subject_category_raw: str | None = None
    batch_raw: str | None = None
    remark: str | None = None
    source_url: str | None = None
    data_source: str | None = None
    source_updated_at: datetime | None = None
    quality_flags: list[str] = Field(default_factory=list)
