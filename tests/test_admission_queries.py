from __future__ import annotations

import asyncio
from typing import Any, cast

from gaokao_vault.db.queries.admission import upsert_major_admission_result


class _FakeConnection:
    def __init__(self) -> None:
        self.query = ""
        self.args: tuple[object, ...] = ()

    async def fetchrow(self, query: str, *args: object) -> dict[str, int]:
        self.query = query
        self.args = args
        return {"id": 88}


def test_upsert_major_admission_result_uses_natural_key() -> None:
    conn = _FakeConnection()

    admission_id = asyncio.run(
        upsert_major_admission_result(
            cast(Any, conn),
            {
                "school_id": 1,
                "major_id": 2,
                "province_id": 7,
                "year": 2025,
                "subject_category_id": 3,
                "batch": "本科批",
            },
        )
    )

    assert admission_id == 88
    assert "major_admission_results" in conn.query
    assert "ON CONFLICT (school_id, major_id, province_id, year, subject_category_id, batch)" in conn.query
