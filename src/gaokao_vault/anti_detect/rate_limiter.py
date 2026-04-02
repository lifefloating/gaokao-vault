from __future__ import annotations

import asyncio
import random

from gaokao_vault.config import CrawlConfig


async def jittered_delay(config: CrawlConfig | None = None) -> None:
    if config is None:
        config = CrawlConfig()
    base = config.base_delay
    jitter = base * config.jitter_ratio
    delay = base + random.uniform(-jitter, jitter)  # noqa: S311
    await asyncio.sleep(max(0.1, delay))
