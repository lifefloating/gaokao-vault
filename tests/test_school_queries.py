from __future__ import annotations

import asyncio
from typing import Any, cast

from gaokao_vault.db.queries.schools import upsert_school


class _FakeConnection:
    def __init__(self) -> None:
        self.query = ""
        self.args: tuple[object, ...] = ()

    async def fetchrow(self, query: str, *args: object) -> dict[str, int]:
        self.query = query
        self.args = args
        return {"id": 99}


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
