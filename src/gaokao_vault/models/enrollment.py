from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class EnrollmentPlanItem(BaseModel):
    school_id: int
    province_id: int
    year: int = Field(ge=2000, le=2100)
    subject_category_id: int | None = None
    batch: str | None = None
    major_name: str | None = None
    major_id: int | None = None
    plan_count: int | None = None
    duration: str | None = None
    tuition: str | None = None
    note: str | None = None


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
