from __future__ import annotations

from typing import Any


def missing_field_flags(data: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
    flags: list[str] = []
    for field in fields:
        value = data.get(field)
        if value is None or value == "":
            flags.append(f"missing_{field}")
    return flags
