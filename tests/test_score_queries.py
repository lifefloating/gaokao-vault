from __future__ import annotations

import asyncio
from typing import Any, cast

from gaokao_vault.db.queries.scores import find_score_segment_rank


class _FakeConnection:
    def __init__(self) -> None:
        self.query = ""
        self.args: tuple[object, ...] = ()
        self.row: dict[str, object] | None = None

    async def fetchrow(self, query: str, *args: object):
        self.query = query
        self.args = args
        return self.row


def test_find_score_segment_rank_uses_score_floor_lookup():
    conn = _FakeConnection()
    conn.row = {"score": 500, "cumulative_count": 23145}

    row = asyncio.run(find_score_segment_rank(cast(Any, conn), 7, 2025, 3, 500))

    assert row == {"score": 500, "cumulative_count": 23145}
    assert "score <= $4" in conn.query
    assert "ORDER BY score DESC" in conn.query
    assert conn.args == (7, 2025, 3, 500)
