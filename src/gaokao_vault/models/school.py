from __future__ import annotations

from pydantic import BaseModel, Field


class SchoolItem(BaseModel):
    sch_id: int
    name: str
    province_id: int | None = None
    city: str | None = None
    authority: str | None = None
    level: str | None = None
    is_211: bool = False
    is_985: bool = False
    is_double_first: bool = False
    is_private: bool = False
    is_independent: bool = False
    is_sino_foreign: bool = False
    school_type: str | None = None
    website: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    introduction: str | None = None
    logo_url: str | None = None


class SchoolSatisfactionItem(BaseModel):
    school_id: int
    year: int | None = None
    overall_score: float | None = Field(default=None, ge=0, le=5)
    environment_score: float | None = Field(default=None, ge=0, le=5)
    life_score: float | None = Field(default=None, ge=0, le=5)
    vote_count: int | None = None
