from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class SpecialEnrollmentItem(BaseModel):
    enrollment_type: str
    special_admission_type: str | None = None
    province_code: str | None = None
    school_id: int | None = None
    school_code_raw: str | None = None
    school_name_raw: str | None = None
    year: int = Field(ge=2000, le=2100)
    title: str | None = None
    content: str | None = None
    content_text: str | None = None
    publish_date: date | None = None
    source_url: str | None = None
    source_section: str | None = None
    detail_url: str | None = None
    application_url: str | None = None
    registration_window: dict[str, str | None] = Field(default_factory=dict)
    registration_start: date | None = None
    registration_end: date | None = None
    milestones: dict[str, str | None] = Field(default_factory=dict)
    shortlist_rule: str | None = None
    selection_rule: str | None = None
    school_assessment: str | None = None
    school_exam_rule: str | None = None
    composite_score_formula: str | None = None
    admission_rule: str | None = None
    eligible_majors: list[str] = Field(default_factory=list)
    quality_flags: list[str] = Field(default_factory=list)
