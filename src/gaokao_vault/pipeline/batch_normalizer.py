from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BatchInfo:
    code: str
    category: str
    segment: str | None = None


def normalize_batch(raw_batch: str | None) -> BatchInfo:
    text = (raw_batch or "").strip()
    segment = _extract_segment(text)
    if "提前批" in text:
        return BatchInfo(code="early", category="提前批", segment=segment)
    return BatchInfo(code="regular", category="普通批", segment=segment)


def _extract_segment(text: str) -> str | None:
    for segment in ("A段", "B段", "C段"):
        if segment in text:
            return segment
    return None
