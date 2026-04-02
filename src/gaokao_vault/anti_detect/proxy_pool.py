from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING, Any, cast

from gaokao_vault.config import ProxyConfig

if TYPE_CHECKING:
    from scrapling.fetchers import ProxyRotator

logger = logging.getLogger(__name__)

_manager: ProxyPoolManager | None = None


class ProxyPoolManager:
    def __init__(self, config: ProxyConfig | None = None):
        if config is None:
            config = ProxyConfig()
        self._paid_proxies: list[str] = list(config.static_proxies)
        self._free_proxies: list[str] = []
        self._use_freeproxy: bool = config.use_freeproxy

    def refresh_free_proxies(self) -> None:
        if not self._use_freeproxy:
            return
        try:
            from freeproxy.freeproxy import ProxiedSessionClient

            client = ProxiedSessionClient(
                init_proxied_session_cfg={
                    "max_pages": 1,
                    "filter_rule": {"country_code": ["CN"]},
                },
                disable_print=True,
            )
            for _ in range(10):
                try:
                    p = client.getrandomproxy(proxy_format="str")
                    if p and isinstance(p, str) and p not in self._free_proxies:
                        self._free_proxies.append(p)
                except Exception:  # noqa: S112
                    continue
            logger.info("Refreshed free proxies, total: %d", len(self._free_proxies))
        except ImportError:
            logger.warning("pyfreeproxy not installed, skipping free proxy refresh")

    def get_rotator(self) -> ProxyRotator | None:
        from scrapling.fetchers import ProxyRotator

        all_proxies = self._paid_proxies + self._free_proxies
        if not all_proxies:
            return None

        def random_strategy(proxies, current_index):
            idx = random.randint(0, len(proxies) - 1)  # noqa: S311
            return proxies[idx], idx

        return ProxyRotator(cast(Any, all_proxies), strategy=random_strategy)


def get_proxy_rotator(config: ProxyConfig | None = None) -> ProxyRotator | None:
    global _manager
    if _manager is None:
        _manager = ProxyPoolManager(config)
        _manager.refresh_free_proxies()
    return _manager.get_rotator()
