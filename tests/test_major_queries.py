from __future__ import annotations

import asyncio
from typing import Any, cast

from gaokao_vault.db.queries.majors import (
    find_school_major_id_by_name,
    refresh_school_major_strength_rollup,
    upsert_school_major,
    upsert_school_major_strength_signal,
)


class _FakeConnection:
    def __init__(self, responses: list[list[dict[str, int]]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, query: str, *args: object) -> list[dict[str, int]]:
        self.calls.append((query, args))
        return self.responses.pop(0)


class _FakeUpsertConnection:
    def __init__(self) -> None:
        self.query = ""
        self.args: tuple[object, ...] = ()

    async def fetchrow(self, query: str, *args: object) -> dict[str, int]:
        self.query = query
        self.args = args
        return {"id": 123}


class _FakeExecuteConnection:
    def __init__(self) -> None:
        self.query = ""

    async def execute(self, query: str) -> str:
        self.query = query
        return "UPDATE 3"


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


def test_upsert_school_major_persists_strength_fields_without_using_display_order_as_featured() -> None:
    conn = _FakeUpsertConnection()

    entity_id = asyncio.run(
        upsert_school_major(
            cast(Any, conn),
            {
                "school_id": 7,
                "major_id": 31,
                "school_major_display_order": 2,
                "major_strength_rank": 1,
                "major_strength_score": 92.5,
                "major_strength_tier": "national_first_class",
                "is_featured_major": True,
                "strength_evidence": [{"signal_type": "national_first_class"}],
                "content_hash": "abc",
                "crawl_task_id": 99,
            },
        )
    )

    assert entity_id == 123
    assert "school_major_display_order" in conn.query
    assert "major_strength_rank" in conn.query
    assert "major_strength_score" in conn.query
    assert "major_strength_tier" in conn.query
    assert "is_featured_major" in conn.query
    assert "strength_evidence" in conn.query
    assert "school_major_display_order=EXCLUDED.school_major_display_order" in conn.query
    assert "major_strength_rank=CASE WHEN $11 THEN EXCLUDED.major_strength_rank" in conn.query
    assert "major_strength_score=CASE WHEN $11 THEN EXCLUDED.major_strength_score" in conn.query
    assert "major_strength_tier=CASE WHEN $11 THEN EXCLUDED.major_strength_tier" in conn.query
    assert "is_featured_major=CASE WHEN $11 THEN EXCLUDED.is_featured_major" in conn.query
    assert "strength_evidence=CASE WHEN $11 THEN EXCLUDED.strength_evidence" in conn.query
    assert conn.args == (
        7,
        31,
        2,
        1,
        92.5,
        "national_first_class",
        True,
        '[{"signal_type": "national_first_class"}]',
        "abc",
        99,
        True,
    )


def test_upsert_school_major_preserves_existing_strength_when_spider_only_knows_display_order() -> None:
    conn = _FakeUpsertConnection()

    asyncio.run(
        upsert_school_major(
            cast(Any, conn),
            {
                "school_id": 7,
                "major_id": 31,
                "school_major_display_order": 2,
                "content_hash": "abc",
                "crawl_task_id": 99,
            },
        )
    )

    assert "major_strength_rank=CASE WHEN $11 THEN EXCLUDED.major_strength_rank" in conn.query
    assert "major_strength_score=CASE WHEN $11 THEN EXCLUDED.major_strength_score" in conn.query
    assert "major_strength_tier=CASE WHEN $11 THEN EXCLUDED.major_strength_tier" in conn.query
    assert "is_featured_major=CASE WHEN $11 THEN EXCLUDED.is_featured_major" in conn.query
    assert "strength_evidence=CASE WHEN $11 THEN EXCLUDED.strength_evidence" in conn.query
    assert conn.args == (
        7,
        31,
        2,
        None,
        None,
        None,
        False,
        None,
        "abc",
        99,
        False,
    )


def test_upsert_school_major_strength_signal_persists_authoritative_evidence() -> None:
    conn = _FakeUpsertConnection()

    entity_id = asyncio.run(
        upsert_school_major_strength_signal(
            cast(Any, conn),
            {
                "school_id": 7,
                "major_id": 31,
                "signal_type": "national_first_class",
                "signal_level": "national",
                "strength_score": 100,
                "source_url": "https://gaokao.chsi.com.cn/example",
                "evidence_title": "国家级一流本科专业建设点",
                "evidence_year": 2025,
                "content_hash": "signal-hash",
                "crawl_task_id": 99,
            },
        )
    )

    assert entity_id == 123
    assert "INSERT INTO school_major_strength_signals" in conn.query
    assert "ON CONFLICT (school_id, major_id, signal_type, signal_level, evidence_year) DO UPDATE SET" in conn.query
    assert "strength_score=EXCLUDED.strength_score" in conn.query
    assert conn.args == (
        7,
        31,
        "national_first_class",
        "national",
        100,
        "https://gaokao.chsi.com.cn/example",
        "国家级一流本科专业建设点",
        2025,
        "signal-hash",
        99,
    )


def test_refresh_school_major_strength_rollup_ranks_only_authoritative_signals() -> None:
    conn = _FakeExecuteConnection()

    status = asyncio.run(refresh_school_major_strength_rollup(cast(Any, conn)))

    assert status == "UPDATE 3"
    assert "FROM school_major_strength_signals" in conn.query
    assert "ROW_NUMBER() OVER" in conn.query
    assert "SUM(strength_score)" in conn.query
    assert "major_strength_rank" in conn.query
    assert "is_featured_major" in conn.query
    assert "strength_evidence" in conn.query
    assert "school_major_display_order" not in conn.query


def test_refresh_school_major_strength_rollup_clears_stale_featured_flags_without_signals() -> None:
    conn = _FakeExecuteConnection()

    asyncio.run(refresh_school_major_strength_rollup(cast(Any, conn)))

    assert "WITH ranked AS" in conn.query
    assert "LEFT JOIN ranked" in conn.query
    assert "major_strength_rank = ranked.major_strength_rank" in conn.query
    assert "major_strength_score = ranked.major_strength_score" in conn.query
    assert "major_strength_tier = CASE" in conn.query
    assert "is_featured_major = COALESCE(ranked.major_strength_rank <= 3, FALSE)" in conn.query
    assert "strength_evidence = COALESCE(ranked.strength_evidence, '[]'::jsonb)" in conn.query
