from __future__ import annotations

import re

PROGRAM_KEYWORDS = (
    ("公费师范", "公费师范"),
    ("优师", "优师专项"),
    ("军校", "军校"),
    ("军事", "军校"),
    ("公安", "公安"),
    ("警校", "公安"),
    ("航海", "航海"),
    ("定向", "定向"),
    ("专项", "专项计划"),
)


def extract_program_type(*texts: str | None) -> str | None:
    combined = _join_texts(*texts)
    for keyword, program_type in PROGRAM_KEYWORDS:
        if keyword in combined:
            return program_type
    return None


def extract_eligibility_requirements(text: str | None) -> str | None:
    return _extract_rule(text, ("资格", "报考条件", "报名条件"))


def extract_political_review_requirement(text: str | None) -> str | None:
    return _extract_rule(text, ("政审", "政治考核", "政治审查"))


def extract_physical_exam_limit(text: str | None) -> str | None:
    return _extract_rule(text, ("体检", "色盲", "色弱", "限报", "不招"))


def extract_single_subject_limit(text: str | None) -> str | None:
    return _extract_rule(text, ("单科", "英语", "数学", "语文"))


def extract_adjustment_rule(text: str | None) -> str | None:
    return _extract_rule(text, ("调剂",))


def extract_physical_exam_or_political_review(text: str | None) -> str | None:
    physical_exam = extract_physical_exam_limit(text)
    political_review = extract_political_review_requirement(text)
    return _join_rules(physical_exam, political_review)


def extract_service_obligation(text: str | None) -> str | None:
    return _extract_rule(text, ("服务期", "服务年限", "定向就业", "服从分配", "协议"))


def _extract_rule(text: str | None, keywords: tuple[str, ...]) -> str | None:
    if not text:
        return None
    parts = [part.strip() for part in re.split(r"[\n,\uFF0C;\uFF1B\u3002.]", text) if part.strip()]
    matches = [part for part in parts if any(keyword in part for keyword in keywords)]
    return ";".join(matches) if matches else None


def _join_texts(*texts: str | None) -> str:
    return " ".join(text for text in texts if text)


def _join_rules(*rules: str | None) -> str | None:
    values = [rule for rule in rules if rule]
    return ";".join(values) if values else None
