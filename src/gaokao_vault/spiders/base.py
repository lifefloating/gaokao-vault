from __future__ import annotations

import logging
from typing import Any, ClassVar, cast

import asyncpg
from scrapling.fetchers import AsyncStealthySession
from scrapling.spiders import Request, Response, Spider

from gaokao_vault.anti_detect.proxy_pool import get_proxy_rotator
from gaokao_vault.anti_detect.ua_pool import IMPERSONATE_LIST
from gaokao_vault.config import CrawlConfig, DatabaseConfig
from gaokao_vault.db.connection import create_local_pool
from gaokao_vault.pipeline.dedup import deduplicate_and_persist
from gaokao_vault.pipeline.hasher import compute_content_hash

logger = logging.getLogger(__name__)

# HTTP status codes that indicate the request was blocked
BLOCKED_STATUS_CODES = {401, 403, 407, 412, 429, 444, 500, 502, 503, 504}
# Content patterns that indicate anti-bot blocking on gaokao.chsi.com.cn
BLOCKED_CONTENT_PATTERNS = [
    "访问过于频繁",
    "请输入验证码",
    "access denied",
    "rate limit",
    "请稍后再试",
    "系统繁忙",
]


class BaseGaokaoSpider(Spider):
    name: str = "base"
    task_type: str = ""
    start_urls: list[str] = []  # noqa: RUF012

    # Scrapling concurrency settings
    concurrent_requests = 2
    concurrent_requests_per_domain = 1
    download_delay = 2.0
    max_blocked_retries = 3

    # Restrict crawling to the target domain
    allowed_domains: ClassVar[set[str]] = {"gaokao.chsi.com.cn"}

    def __init__(
        self,
        db_config: DatabaseConfig,
        crawl_task_id: int,
        mode: str = "full",
        config: CrawlConfig | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._db_config = db_config
        self._local_pool: asyncpg.Pool | None = None
        self.crawl_task_id = crawl_task_id
        self.mode = mode
        self._stats: dict[str, int] = {"new": 0, "updated": 0, "unchanged": 0, "failed": 0}

        if config:
            self.concurrent_requests = config.concurrency
            self.concurrent_requests_per_domain = config.concurrency_per_domain
            self.download_delay = config.base_delay

    async def _get_pool(self) -> asyncpg.Pool:
        """Lazily create a local asyncpg pool bound to the current event loop."""
        if self._local_pool is None:
            self._local_pool = await create_local_pool(self._db_config)
        return self._local_pool

    def configure_sessions(self, manager) -> None:
        rotator = get_proxy_rotator()
        manager.add(
            "http",
            AsyncStealthySession(
                headless=True,
                google_search=False,
                block_webrtc=True,
                hide_canvas=True,
                extra_headers={"Referer": "https://gaokao.chsi.com.cn/"},
                additional_args={"viewport": {"width": 1366, "height": 768}},
                impersonate=cast(Any, IMPERSONATE_LIST),
                proxy_rotator=rotator,
            ),
        )
        manager.add(
            "stealth",
            AsyncStealthySession(
                headless=True,
                google_search=False,
                block_webrtc=True,
                hide_canvas=True,
                extra_headers={"Referer": "https://gaokao.chsi.com.cn/"},
                additional_args={"viewport": {"width": 1366, "height": 768}},
                impersonate=cast(Any, IMPERSONATE_LIST),
                proxy_rotator=rotator,
            ),
            lazy=True,
        )

    async def is_blocked(self, response: Response) -> bool:
        """Detect anti-bot blocking from gaokao.chsi.com.cn."""
        if response.status in BLOCKED_STATUS_CODES:
            return True

        body = response.body.decode("utf-8", errors="ignore").lower()
        return any(pattern in body for pattern in BLOCKED_CONTENT_PATTERNS)

    async def retry_blocked_request(self, request: Request, response: Response) -> Request:
        """Switch to stealth session on block detection."""
        request.sid = "stealth"
        logger.warning("Blocked on %s (status=%s), switching to stealth", request.url, response.status)
        return request

    async def on_error(self, request: Request, error: Exception) -> None:
        """Log request-level errors for debugging."""
        logger.error("Request failed: %s — %s: %s", request.url, type(error).__name__, error)

    async def process_item(self, item: dict[str, Any], entity_type: str, unique_keys: dict, upsert_fn=None) -> str:
        content_hash = compute_content_hash(item)
        try:
            change_type = await deduplicate_and_persist(
                db_pool=await self._get_pool(),
                entity_type=entity_type,
                item=item,
                content_hash=content_hash,
                unique_keys=unique_keys,
                crawl_task_id=self.crawl_task_id,
                upsert_fn=upsert_fn,
            )
        except Exception:
            logger.exception("Failed to persist item for %s: keys=%s", entity_type, unique_keys)
            self._stats["failed"] += 1
            return "failed"
        else:
            self._stats[change_type] += 1
            return change_type

    async def on_close(self) -> None:
        from gaokao_vault.db.queries.crawl_meta import update_task_stats

        await update_task_stats(await self._get_pool(), self.crawl_task_id, self._stats)
        logger.info(
            "Spider %s finished: new=%d updated=%d unchanged=%d failed=%d",
            self.name,
            self._stats["new"],
            self._stats["updated"],
            self._stats["unchanged"],
            self._stats["failed"],
        )
        if self._local_pool is not None:
            await self._local_pool.close()

    async def parse(self, response: Response):
        raise NotImplementedError
        yield
