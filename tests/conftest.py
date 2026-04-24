from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


def make_mock_pool_and_conn() -> tuple[MagicMock, AsyncMock, AsyncMock]:
    """Return pool, conn, transaction context mocks for asyncpg-style tests."""
    pool = MagicMock()
    conn = AsyncMock()

    transaction_context = AsyncMock()
    transaction_context.__aenter__ = AsyncMock(return_value=None)
    transaction_context.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=transaction_context)

    acquire_context = AsyncMock()
    acquire_context.__aenter__ = AsyncMock(return_value=conn)
    acquire_context.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = acquire_context
    return pool, conn, transaction_context
