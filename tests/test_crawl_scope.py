from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from gaokao_vault.spiders.scope import iter_crawl_years, load_province_targets


class _Acquire:
    def __init__(self, conn) -> None:
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, conn) -> None:
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


def test_iter_crawl_years_uses_full_historical_window() -> None:
    assert list(iter_crawl_years(mode="full", full_start_year=2020, current_year=2026)) == [
        2020,
        2021,
        2022,
        2023,
        2024,
        2025,
        2026,
    ]


def test_iter_crawl_years_limits_incremental_to_recent_three_years() -> None:
    assert list(iter_crawl_years(mode="incremental", full_start_year=2020, current_year=2026)) == [
        2024,
        2025,
        2026,
    ]


def test_iter_crawl_years_keeps_incremental_inside_full_window() -> None:
    assert list(iter_crawl_years(mode="incremental", full_start_year=2025, current_year=2026)) == [2025, 2026]


def test_load_province_targets_uses_seeded_province_codes_for_remote_urls() -> None:
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[
            {"id": 7, "name": "吉林", "code": "22"},
            {"id": 10, "name": "江苏", "code": "32"},
        ]
    )

    targets = asyncio.run(load_province_targets(_FakePool(conn)))

    assert [(p.id, p.name, p.url_value) for p in targets] == [(7, "吉林", "22"), (10, "江苏", "32")]
    conn.fetch.assert_awaited_once()
