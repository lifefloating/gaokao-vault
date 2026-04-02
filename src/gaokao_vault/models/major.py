from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class MajorCategoryItem(BaseModel):
    name: str
    education_level: str
    code: str | None = None


class MajorSubcategoryItem(BaseModel):
    category_id: int
    name: str
    code: str | None = None


class MajorItem(BaseModel):
    source_id: str | None = None
    subcategory_id: int | None = None
    code: str | None = None
    name: str
    education_level: str
    duration: str | None = None
    degree: str | None = None
    description: str | None = None
    employment_rate: str | None = None
    graduate_directions: str | None = None


class SchoolMajorItem(BaseModel):
    school_id: int
    major_id: int


class MajorSatisfactionItem(BaseModel):
    major_id: int
    school_id: int | None = None
    overall_score: float | None = None
    vote_count: int | None = None


class MajorInterpretationItem(BaseModel):
    major_id: int | None = None
    title: str | None = None
    content: str
    author: str | None = None
    publish_date: date | None = None
    source_url: str | None = None
