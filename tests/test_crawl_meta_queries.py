from __future__ import annotations

import asyncio
from typing import Any, cast

from gaokao_vault.db.queries.crawl_meta import fail_stale_running_tasks


class _Acquire:
    def __init__(self, conn) -> None:
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self) -> None:
        self.conn = _FakeConnection()

    def acquire(self):
        return _Acquire(self.conn)


class _FakeConnection:
    def __init__(self) -> None:
        self.query = ""
        self.args: tuple[object, ...] = ()
        self.result = "UPDATE 2"

    async def execute(self, query: str, *args: object) -> str:
        self.query = query
        self.args = args
        return self.result


def test_fail_stale_running_tasks_marks_old_running_rows_failed() -> None:
    pool = _FakePool()

    updated = asyncio.run(fail_stale_running_tasks(cast(Any, pool), stale_after_seconds=21600))

    assert updated == 2
    assert "UPDATE crawl_tasks" in pool.conn.query
    assert "status = 'running'" in pool.conn.query
    assert "started_at < NOW() - ($1::TEXT || ' seconds')::INTERVAL" in pool.conn.query
    assert "error_message = 'Recovered stale running task after scheduler restart'" in pool.conn.query
    assert pool.conn.args == (21600,)
