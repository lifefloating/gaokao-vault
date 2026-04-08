from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

_VARCHAR_LIMITS: dict[str, int] = {
    "name": 100,
    "city": 50,
    "authority": 100,
    "level": 20,
    "school_type": 30,
    "website": 255,
    "phone": 100,
    "email": 100,
    "address": 255,
    "logo_url": 255,
}


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

    @model_validator(mode="before")
    @classmethod
    def truncate_long_strings(cls, data: dict) -> dict:
        for field_name, max_len in _VARCHAR_LIMITS.items():
            val = data.get(field_name)
            if isinstance(val, str) and len(val) > max_len:
                data[field_name] = val[:max_len]
        return data


class SchoolSatisfactionItem(BaseModel):
    school_id: int
    year: int | None = None
    overall_score: float | None = Field(default=None, ge=0, le=5)
    environment_score: float | None = Field(default=None, ge=0, le=5)
    life_score: float | None = Field(default=None, ge=0, le=5)
    vote_count: int | None = None
