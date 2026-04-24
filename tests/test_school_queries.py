from __future__ import annotations

import asyncio
from typing import Any, cast

from gaokao_vault.db.queries.schools import find_schools_by_city, upsert_school


class _FakeConnection:
    def __init__(self) -> None:
        self.query = ""
        self.args: tuple[object, ...] = ()
        self.rows: list[dict[str, object]] = []

    async def fetchrow(self, query: str, *args: object) -> dict[str, int]:
        self.query = query
        self.args = args
        return {"id": 99}

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        self.query = query
        self.args = args
        return self.rows


def test_upsert_school_preserves_existing_province_id_when_new_value_is_null():
    conn = _FakeConnection()

    school_id = asyncio.run(
        upsert_school(
            cast(Any, conn),
            {
                "sch_id": 1,
                "name": "Ce Shi University",
                "province_id": None,
            },
        )
    )

    assert school_id == 99
    assert conn.args[2] is None
    assert "province_id=COALESCE(EXCLUDED.province_id, schools.province_id)" in conn.query


def test_upsert_school_still_passes_non_null_province_id():
    conn = _FakeConnection()

    asyncio.run(
        upsert_school(
            cast(Any, conn),
            {
                "sch_id": 2,
                "name": "Second Test University",
                "province_id": 3,
            },
        )
    )

    assert conn.args[2] == 3


def test_find_schools_by_city_uses_exact_city_filter():
    conn = _FakeConnection()
    conn.rows = [{"id": 1, "sch_id": 34, "name": "苏州大学", "city": "苏州"}]

    rows = asyncio.run(find_schools_by_city(cast(Any, conn), "苏州"))

    assert rows == [{"id": 1, "sch_id": 34, "name": "苏州大学", "city": "苏州"}]
    assert "WHERE city = $1" in conn.query
    assert conn.args == ("苏州",)
