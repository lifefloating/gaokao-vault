from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class BatchSink:
    def __init__(
        self,
        pool: asyncpg.Pool,
        flush_fn: Callable[[asyncpg.Connection, list[dict[str, Any]]], Coroutine[Any, Any, int]],
        batch_size: int = 500,
    ):
        self._pool = pool
        self._flush_fn = flush_fn
        self._batch_size = batch_size
        self._buffer: list[dict[str, Any]] = []
        self._total_flushed = 0

    async def add(self, item: dict[str, Any]) -> None:
        self._buffer.append(item)
        if len(self._buffer) >= self._batch_size:
            await self.flush()

    async def flush(self) -> int:
        if not self._buffer:
            return 0
        batch = self._buffer[:]
        self._buffer.clear()
        async with self._pool.acquire() as conn:
            count = await self._flush_fn(conn, batch)
        self._total_flushed += count
        logger.debug("Flushed %d items (total: %d)", count, self._total_flushed)
        return count

    @property
    def total_flushed(self) -> int:
        return self._total_flushed

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)
