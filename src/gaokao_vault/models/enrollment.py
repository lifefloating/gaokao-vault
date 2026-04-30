from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class EnrollmentPlanItem(BaseModel):
    school_id: int
    province_id: int
    year: int = Field(ge=2000, le=2100)
    subject_category_id: int | None = None
    batch: str | None = None
    batch_code: str | None = None
    batch_category: str | None = None
    batch_segment: str | None = None
    major_name: str | None = None
    major_id: int | None = None
    plan_count: int | None = None
    duration: str | None = None
    tuition: str | None = None
    note: str | None = None
    major_group_code: str | None = None
    major_code_raw: str | None = None
    campus: str | None = None
    education_location: str | None = None
    selection_requirement: str | None = None
    physical_exam_limit: str | None = None
    single_subject_limit: str | None = None
    adjustment_rule: str | None = None
    program_type: str | None = None
    eligibility_requirements: str | None = None
    physical_exam_or_political_review: str | None = None
    political_review_requirement: str | None = None
    service_obligation: str | None = None
    data_source: str | None = None
    source_url: str | None = None
    source_updated_at: datetime | None = None
    quality_flags: list[str] = Field(default_factory=list)


class CharterItem(BaseModel):
    school_id: int
    year: int = Field(ge=2000, le=2100)
    title: str | None = None
    content: str
    publish_date: date | None = None
    source_url: str | None = None


class TimelineItem(BaseModel):
    province_id: int
    year: int = Field(ge=2000, le=2100)
    batch: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    note: str | None = None
