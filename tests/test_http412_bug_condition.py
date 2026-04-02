"""Bug Condition Exploration Test — Anti-Detect Configuration Defects Cause HTTP 412.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7**

This test encodes the EXPECTED post-fix behavior:
  - configure_sessions() uses AsyncStealthySession as default session
  - 412 is in BLOCKED_STATUS_CODES
  - CrawlConfig defaults are conservative (concurrency=2, per_domain=1, delay=2.0)
  - Default session has site-internal referer and google_search=False
  - SchoolSpider.start_requests() yields a warmup request first
  - Stealth session has viewport 1366x768

Strategy: Since AsyncStealthySession does NOT store constructor kwargs as
instance attributes, we mock the constructor to capture the kwargs passed
by configure_sessions().
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from gaokao_vault.config import CrawlConfig
from gaokao_vault.spiders.base import BLOCKED_STATUS_CODES, BaseGaokaoSpider
from gaokao_vault.spiders.school_spider import SchoolSpider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spider() -> BaseGaokaoSpider:
    from gaokao_vault.config import DatabaseConfig

    db_config = DatabaseConfig(
        dsn="postgresql://test:test@localhost:5432/test_db",
        pool_min=1,
        pool_max=2,
    )
    return BaseGaokaoSpider(db_config=db_config, crawl_task_id=1)


def _make_school_spider() -> SchoolSpider:
    from gaokao_vault.config import DatabaseConfig

    db_config = DatabaseConfig(
        dsn="postgresql://test:test@localhost:5432/test_db",
        pool_min=1,
        pool_max=2,
    )
    return SchoolSpider(db_config=db_config, crawl_task_id=1)


class _FakeSessionManager:
    """Captures sessions registered via configure_sessions()."""

    def __init__(self):
        self.sessions: dict[str, tuple] = {}

    def add(self, name: str, session, lazy: bool = False, **kwargs):
        self.sessions[name] = (session, lazy, kwargs)


def _capture_stealthy_kwargs():
    """Mock AsyncStealthySession to capture constructor kwargs.

    Returns (mock_cls, calls) where calls is a list of kwargs dicts
    passed to each AsyncStealthySession() call.
    """
    calls: list[dict] = []

    def _fake_init(**kwargs):
        calls.append(kwargs)
        mock_instance = MagicMock()
        mock_instance._captured_kwargs = kwargs
        return mock_instance

    mock_cls = MagicMock(side_effect=_fake_init)
    return mock_cls, calls


# ---------------------------------------------------------------------------
# Property 1: Bug Condition — Anti-Detect Configuration Defects
# ---------------------------------------------------------------------------


class TestAntiDetectBugCondition:
    """Property 1: Bug Condition - Anti-Detect Configuration Defects.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7**
    """

    def test_configure_sessions_uses_stealthy_as_default(self):
        """Default session must be AsyncStealthySession, not FetcherSession.

        **Validates: Requirements 1.5, 1.6**
        """
        from scrapling.fetchers import AsyncStealthySession, FetcherSession

        spider = _make_spider()
        manager = _FakeSessionManager()

        with patch("gaokao_vault.spiders.base.get_proxy_rotator", return_value=None):
            spider.configure_sessions(manager)

        assert "http" in manager.sessions, "No 'http' session registered"
        http_session, _lazy, _kwargs = manager.sessions["http"]
        assert isinstance(http_session, AsyncStealthySession), (
            f"Default 'http' session is {type(http_session).__name__}, expected AsyncStealthySession."
        )
        assert not isinstance(http_session, FetcherSession), "Default session must NOT be FetcherSession"

    def test_configure_sessions_stealthy_kwargs(self):
        """Default session must be created with headless=True, google_search=False,
        block_webrtc=True, hide_canvas=True.

        **Validates: Requirements 1.1, 1.5, 1.7**

        Uses mock to capture constructor kwargs since AsyncStealthySession
        doesn't store them as instance attributes.
        """
        mock_cls, calls = _capture_stealthy_kwargs()
        spider = _make_spider()
        manager = _FakeSessionManager()

        with (
            patch("gaokao_vault.spiders.base.get_proxy_rotator", return_value=None),
            patch("gaokao_vault.spiders.base.AsyncStealthySession", mock_cls),
        ):
            spider.configure_sessions(manager)

        # At least one call for the "http" session
        assert len(calls) >= 1, "AsyncStealthySession was never constructed"
        http_kwargs = calls[0]  # first call = "http" session

        assert http_kwargs.get("headless") is True, f"headless={http_kwargs.get('headless')}, expected True"
        assert http_kwargs.get("google_search") is False, (
            f"google_search={http_kwargs.get('google_search')}, expected False"
        )
        assert http_kwargs.get("block_webrtc") is True, f"block_webrtc={http_kwargs.get('block_webrtc')}, expected True"
        assert http_kwargs.get("hide_canvas") is True, f"hide_canvas={http_kwargs.get('hide_canvas')}, expected True"

    def test_412_in_blocked_status_codes(self):
        """412 must be in BLOCKED_STATUS_CODES.

        **Validates: Requirements 1.2**
        """
        assert 412 in BLOCKED_STATUS_CODES, f"412 not in BLOCKED_STATUS_CODES ({BLOCKED_STATUS_CODES})"

    @given(concurrency=st.just(None))
    @settings(max_examples=1, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_crawl_config_conservative_defaults(self, concurrency):
        """CrawlConfig defaults must be concurrency=2, per_domain=1, delay=2.0.

        **Validates: Requirements 1.3**
        """
        config = CrawlConfig()
        assert config.concurrency == 2, f"concurrency={config.concurrency}, expected 2"
        assert config.concurrency_per_domain == 1, f"concurrency_per_domain={config.concurrency_per_domain}, expected 1"
        assert config.base_delay == 2.0, f"base_delay={config.base_delay}, expected 2.0"

    def test_default_session_referer_and_google_search(self):
        """Default session must have site-internal referer and google_search=False.

        **Validates: Requirements 1.1, 1.4**
        """
        mock_cls, calls = _capture_stealthy_kwargs()
        spider = _make_spider()
        manager = _FakeSessionManager()

        with (
            patch("gaokao_vault.spiders.base.get_proxy_rotator", return_value=None),
            patch("gaokao_vault.spiders.base.AsyncStealthySession", mock_cls),
        ):
            spider.configure_sessions(manager)

        assert len(calls) >= 1
        http_kwargs = calls[0]

        assert http_kwargs.get("google_search") is False, (
            f"google_search={http_kwargs.get('google_search')}, expected False"
        )

        extra_headers = http_kwargs.get("extra_headers", {})
        referer = extra_headers.get("Referer", "")
        assert "gaokao.chsi.com.cn" in referer, f"Referer='{referer}', expected site-internal referer"

    def test_school_spider_warmup_request(self):
        """start_requests() must yield a warmup request to the list page FIRST.

        **Validates: Requirements 1.4**
        """
        spider = _make_school_spider()

        loop = asyncio.new_event_loop()
        try:

            async def _get_first():
                async for req in spider.start_requests():
                    return req
                return None

            first_req = loop.run_until_complete(_get_first())
        finally:
            loop.close()

        assert first_req is not None, "start_requests() yielded no requests"
        assert "/sch/search--" in first_req.url, f"First URL='{first_req.url}', expected warmup to list page"

    def test_stealthy_session_viewport(self):
        """Stealth session must have viewport 1366x768.

        **Validates: Requirements 1.6, 1.7**
        """
        mock_cls, calls = _capture_stealthy_kwargs()
        spider = _make_spider()
        manager = _FakeSessionManager()

        with (
            patch("gaokao_vault.spiders.base.get_proxy_rotator", return_value=None),
            patch("gaokao_vault.spiders.base.AsyncStealthySession", mock_cls),
        ):
            spider.configure_sessions(manager)

        assert len(calls) >= 1
        http_kwargs = calls[0]

        additional_args = http_kwargs.get("additional_args", {})
        viewport = additional_args.get("viewport", {})
        assert viewport.get("width") == 1366, f"viewport width={viewport.get('width')}, expected 1366"
        assert viewport.get("height") == 768, f"viewport height={viewport.get('height')}, expected 768"
