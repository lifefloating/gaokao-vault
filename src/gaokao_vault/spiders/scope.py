from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

_INCREMENTAL_YEAR_WINDOW = 3


@dataclass(frozen=True, slots=True)
class ProvinceTarget:
    id: int
    name: str
    url_value: str


def iter_crawl_years(*, mode: str, full_start_year: int, current_year: int) -> range:
    start_year = full_start_year
    if mode == "incremental":
        start_year = max(full_start_year, current_year - _INCREMENTAL_YEAR_WINDOW + 1)
    return range(start_year, current_year + 1)


async def load_province_targets(pool) -> list[ProvinceTarget]:
    async with pool.acquire() as conn:
        rows: Iterable = await conn.fetch("SELECT id, name, code FROM provinces ORDER BY id")

    return [
        ProvinceTarget(
            id=int(row["id"]),
            name=str(row["name"]),
            url_value=str(row["code"] or row["id"]),
        )
        for row in rows
    ]
