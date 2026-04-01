from __future__ import annotations

import random

from fake_useragent import UserAgent

IMPERSONATE_LIST: list[str] = [
    "chrome",
    "firefox",
    "safari",
    "edge",
]

BROWSER_TYPES: list[str] = ["chrome", "firefox", "safari", "edge"]


class UAPool:
    """User-Agent pool combining fake-useragent for realistic UA strings
    and Scrapling impersonate list for TLS fingerprint selection."""

    def __init__(self) -> None:
        self._ua = UserAgent(browsers=BROWSER_TYPES)

    def get_random_ua(self) -> str:
        """Get a random realistic User-Agent string."""
        return self._ua.random

    def get_random_impersonate(self) -> str:
        """Get a random browser name for Scrapling impersonate parameter."""
        return random.choice(IMPERSONATE_LIST)  # noqa: S311

    def get_ua_for_browser(self, browser: str) -> str:
        """Get a User-Agent string for a specific browser type."""
        browser = browser.lower()
        if browser not in BROWSER_TYPES:
            msg = f"Unsupported browser: {browser}. Choose from {BROWSER_TYPES}"
            raise ValueError(msg)
        return getattr(self._ua, browser)


ua_pool = UAPool()
