from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from typing import Callable
from zoneinfo import ZoneInfo

from gaokao_vault.config import AppConfig

logger = logging.getLogger(__name__)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_MONTH_NAMES = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
_WEEKDAY_NAMES = {
    "SUN": 0,
    "MON": 1,
    "TUE": 2,
    "WED": 3,
    "THU": 4,
    "FRI": 5,
    "SAT": 6,
}


@dataclass(frozen=True, slots=True)
class CronField:
    values: frozenset[int]
    is_any: bool

    def matches(self, value: int) -> bool:
        return self.is_any or value in self.values


@dataclass(frozen=True, slots=True)
class CronExpression:
    raw: str
    minute: CronField
    hour: CronField
    day_of_month: CronField
    month: CronField
    day_of_week: CronField

    @classmethod
    def parse(cls, expression: str) -> CronExpression:
        parts = expression.split()
        if len(parts) != 5:
            msg = f"Invalid cron expression '{expression}'. Expected 5 fields."
            raise ValueError(msg)

        minute, hour, day_of_month, month, day_of_week = parts
        return cls(
            raw=expression,
            minute=_parse_field(minute, 0, 59),
            hour=_parse_field(hour, 0, 23),
            day_of_month=_parse_field(day_of_month, 1, 31),
            month=_parse_field(month, 1, 12, names=_MONTH_NAMES),
            day_of_week=_parse_field(
                day_of_week,
                0,
                7,
                names=_WEEKDAY_NAMES,
                normalize=_normalize_weekday,
            ),
        )

    def matches(self, dt: datetime) -> bool:
        if not self.minute.matches(dt.minute):
            return False
        if not self.hour.matches(dt.hour):
            return False
        if not self.month.matches(dt.month):
            return False

        day_of_month_matches = self.day_of_month.matches(dt.day)
        day_of_week_matches = self.day_of_week.matches(_cron_weekday(dt))

        if self.day_of_month.is_any and self.day_of_week.is_any:
            return True
        if self.day_of_month.is_any:
            return day_of_week_matches
        if self.day_of_week.is_any:
            return day_of_month_matches
        return day_of_month_matches or day_of_week_matches


class IncrementalCronScheduler:
    def __init__(self, app_config: AppConfig):
        self._app_config = app_config
        self._cron = CronExpression.parse(app_config.schedule.cron)
        self._running_task: asyncio.Task[None] | None = None
        self._last_checked_minute: datetime | None = None

    async def run_forever(self) -> None:
        logger.info(
            "Scheduler started cron=%s timezone=%s mode=incremental",
            self._cron.raw,
            _SHANGHAI_TZ.key,
        )
        while True:
            now = self._current_minute()
            if self._last_checked_minute != now:
                self._last_checked_minute = now
                await self._maybe_trigger(now)
            await asyncio.sleep(self._seconds_until_next_minute())

    async def _maybe_trigger(self, now: datetime) -> None:
        if not self._cron.matches(now):
            return

        if self._running_task is not None and not self._running_task.done():
            logger.warning(
                "Skipping scheduled incremental crawl at %s because a previous run is still active",
                now.isoformat(),
            )
            return

        logger.info("Cron matched at %s; starting incremental crawl", now.isoformat())
        self._running_task = asyncio.create_task(self._run_incremental_crawl(now))

    async def _run_incremental_crawl(self, scheduled_at: datetime) -> None:
        from gaokao_vault.db.connection import close_pool, create_pool
        from gaokao_vault.scheduler.orchestrator import Orchestrator

        started = monotonic()
        pool = await create_pool(self._app_config.db)
        try:
            orchestrator = Orchestrator(
                db_pool=pool,
                config=self._app_config.crawl,
                mode="incremental",
                db_config=self._app_config.db,
                app_config=self._app_config,
            )
            await orchestrator.run_all()
        except Exception:
            logger.exception(
                "Scheduled incremental crawl failed scheduled_at=%s",
                scheduled_at.isoformat(),
            )
        else:
            logger.info(
                "Scheduled incremental crawl finished scheduled_at=%s duration=%.1fs",
                scheduled_at.isoformat(),
                monotonic() - started,
            )
        finally:
            await close_pool()

    @staticmethod
    def _current_minute() -> datetime:
        return datetime.now(_SHANGHAI_TZ).replace(second=0, microsecond=0)

    @staticmethod
    def _seconds_until_next_minute() -> float:
        now = datetime.now(_SHANGHAI_TZ)
        return max(1.0, 60 - now.second - now.microsecond / 1_000_000)


def _parse_field(
    field: str,
    min_value: int,
    max_value: int,
    *,
    names: dict[str, int] | None = None,
    normalize: Callable[[int], int] | None = None,
) -> CronField:
    if field == "*":
        return CronField(values=frozenset(range(min_value, max_value + 1)), is_any=True)

    values: set[int] = set()
    for segment in field.split(","):
        values.update(
            _expand_segment(
                segment,
                min_value,
                max_value,
                names=names,
                normalize=normalize,
            )
        )
    return CronField(values=frozenset(values), is_any=False)


def _expand_segment(
    segment: str,
    min_value: int,
    max_value: int,
    *,
    names: dict[str, int] | None = None,
    normalize: Callable[[int], int] | None = None,
) -> set[int]:
    base = segment
    step = 1
    if "/" in segment:
        base, step_text = segment.split("/", 1)
        step = int(step_text)
        if step <= 0:
            msg = f"Invalid cron step '{segment}'."
            raise ValueError(msg)

    if base == "*":
        start = min_value
        end = max_value
    elif "-" in base:
        start_text, end_text = base.split("-", 1)
        start = _parse_value(start_text, min_value, max_value, names=names)
        end = _parse_value(end_text, min_value, max_value, names=names)
        if start > end:
            msg = f"Invalid cron range '{segment}'."
            raise ValueError(msg)
    else:
        value = _parse_value(base, min_value, max_value, names=names)
        start = value
        end = value

    values = set(range(start, end + 1, step))
    if normalize is None:
        return values
    return {normalize(value) for value in values}


def _parse_value(
    value: str,
    min_value: int,
    max_value: int,
    *,
    names: dict[str, int] | None = None,
) -> int:
    token = value.strip().upper()
    parsed = names[token] if names is not None and token in names else int(token)

    if parsed < min_value or parsed > max_value:
        msg = f"Cron value '{value}' is outside {min_value}-{max_value}."
        raise ValueError(msg)
    return parsed


def _normalize_weekday(value: int) -> int:
    return 0 if value == 7 else value


def _cron_weekday(dt: datetime) -> int:
    return (dt.weekday() + 1) % 7
