from __future__ import annotations

import asyncio
from typing import Any, cast

from gaokao_vault.db.queries.majors import find_school_major_id_by_name


class _FakeConnection:
    def __init__(self, responses: list[list[dict[str, int]]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, query: str, *args: object) -> list[dict[str, int]]:
        self.calls.append((query, args))
        return self.responses.pop(0)


def test_find_school_major_id_by_name_filters_by_education_level() -> None:
    conn = _FakeConnection([[{"id": 31}]])

    major_id = asyncio.run(find_school_major_id_by_name(cast(Any, conn), 102, "法学", education_level="本科"))

    assert major_id == 31
    assert conn.calls[0][1] == (102, "法学", "本科")


def test_find_school_major_id_by_name_returns_none_for_ambiguous_school_match() -> None:
    conn = _FakeConnection([[{"id": 31}, {"id": 32}]])

    major_id = asyncio.run(find_school_major_id_by_name(cast(Any, conn), 102, "法学"))

    assert major_id is None
    assert len(conn.calls) == 1


def test_find_school_major_id_by_name_can_fallback_to_unique_global_major() -> None:
    conn = _FakeConnection([[], [{"id": 88}]])

    major_id = asyncio.run(find_school_major_id_by_name(cast(Any, conn), 102, "金融学", fallback_to_unique_major=True))

    assert major_id == 88
    assert len(conn.calls) == 2
    assert "FROM majors" in conn.calls[1][0]
    assert conn.calls[1][1] == ("金融学", None)
