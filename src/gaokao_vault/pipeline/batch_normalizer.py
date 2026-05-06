from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BatchInfo:
    code: str | None
    category: str | None
    segment: str | None = None


def normalize_batch(raw_batch: str | None) -> BatchInfo:
    text = (raw_batch or "").strip()
    segment = _extract_segment(text)
    if "提前批" in text:
        return BatchInfo(code="early", category="提前批", segment=segment)
    if _is_regular_batch(text):
        return BatchInfo(code="regular", category="普通批", segment=segment)
    return BatchInfo(code=None, category=None, segment=segment)


def _extract_segment(text: str) -> str | None:
    for segment in ("A段", "B段", "C段"):
        if segment in text:
            return segment
    return None


def _is_regular_batch(text: str) -> bool:
    if not text:
        return False
    if any(keyword in text for keyword in ("艺术", "体育", "专项", "强基", "综合评价", "保送", "特殊")):
        return False
    return (
        "普通类" in text
        or "普通批" in text
        or "本科批" in text
        or "本科一批" in text
        or "本科二批" in text
        or "专科批" in text
        or "高职批" in text
    )
