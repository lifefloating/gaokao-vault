from __future__ import annotations

from pydantic import BaseModel, Field


class CandidateProfile(BaseModel):
    province_id: int
    year: int = Field(ge=2000, le=2100)
    subject_category_id: int | None = None
    score: int = Field(ge=0)
    rank: int = Field(gt=0)
    batch: str
    rank_window: int = Field(default=5000, gt=0)
    region_preferences: list[str] = Field(default_factory=list)
    major_preferences: list[str] = Field(default_factory=list)
    max_tuition: int | None = Field(default=None, ge=0)
