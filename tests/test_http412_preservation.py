"""Preservation Property Tests — Existing Blocking Detection, Parsing, and Config Override Behavior Unchanged.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

These tests verify that existing behaviour is preserved BEFORE the fix is applied.
They run against the UNFIXED code and must ALL PASS, confirming baseline behaviour
that must remain unchanged after the fix.

EXPECTED OUTCOME: All tests PASS on unfixed code.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from gaokao_vault.config import CrawlConfig
from gaokao_vault.spiders.base import (
    BLOCKED_CONTENT_PATTERNS,
    BaseGaokaoSpider,
)
from gaokao_vault.spiders.school_spider import SchoolSpider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_base_spider() -> BaseGaokaoSpider:
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


def _make_response(status: int, body: str = "", url: str = "https://gaokao.chsi.com.cn/test") -> MagicMock:
    """Create a mock Response with given status and body."""
    resp = MagicMock()
    resp.status = status
    resp.body = body.encode("utf-8")
    resp.url = url
    return resp


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# The exact set of blocked status codes in the current unfixed code
_CURRENT_BLOCKED = frozenset({401, 403, 407, 412, 429, 444, 500, 502, 503, 504})

blocked_status_st = st.sampled_from(sorted(_CURRENT_BLOCKED))

# Status codes that are NOT blocked and have no content-based trigger
# Exclude 412 intentionally — it's the bug; we only test existing behavior here
_NON_BLOCKED_CODES = [c for c in range(100, 600) if c not in _CURRENT_BLOCKED]
non_blocked_status_st = st.sampled_from(_NON_BLOCKED_CODES)

# Content patterns that trigger blocking
content_pattern_st = st.sampled_from(BLOCKED_CONTENT_PATTERNS)

# Clean body text that does NOT contain any blocked pattern
clean_body_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z"), blacklist_characters="访请验证码"),
    min_size=0,
    max_size=200,
).filter(lambda b: not any(p in b.lower() for p in BLOCKED_CONTENT_PATTERNS))

# Positive integers for CrawlConfig overrides
positive_int_st = st.integers(min_value=1, max_value=100)
positive_float_st = st.floats(min_value=0.1, max_value=30.0, allow_nan=False, allow_infinity=False)


# ---------------------------------------------------------------------------
# Property 2.1: Status Code Blocking Preservation (property-based)
# **Validates: Requirements 3.1**
# ---------------------------------------------------------------------------


class TestStatusCodeBlockingPreservation:
    """For all HTTP status codes in BLOCKED_STATUS_CODES, is_blocked() returns True.
    For all status codes NOT in BLOCKED_STATUS_CODES with clean body, is_blocked() returns False.
    """

    @given(status=blocked_status_st)
    @settings(
        max_examples=30,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_blocked_status_codes_detected(self, status: int):
        """**Validates: Requirements 3.1**

        is_blocked() must return True for all status codes in BLOCKED_STATUS_CODES.
        """
        spider = _make_base_spider()
        response = _make_response(status=status, body="some clean body")
        result = asyncio.run(spider.is_blocked(response))
        assert result is True, f"is_blocked() returned False for status {status}, which is in BLOCKED_STATUS_CODES"

    @given(status=non_blocked_status_st, body=clean_body_st)
    @settings(
        max_examples=50,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_non_blocked_status_codes_not_detected(self, status: int, body: str):
        """**Validates: Requirements 3.1**

        is_blocked() must return False for status codes NOT in BLOCKED_STATUS_CODES
        when the body does not contain any blocked content patterns.
        """
        spider = _make_base_spider()
        response = _make_response(status=status, body=body)
        result = asyncio.run(spider.is_blocked(response))
        assert result is False, (
            f"is_blocked() returned True for status {status} with clean body, "
            f"but {status} is not in BLOCKED_STATUS_CODES"
        )


# ---------------------------------------------------------------------------
# Property 2.2: Content-Based Blocking Preservation (property-based)
# **Validates: Requirements 3.4**
# ---------------------------------------------------------------------------


class TestContentBlockingPreservation:
    """For all response bodies containing any BLOCKED_CONTENT_PATTERNS,
    is_blocked() returns True regardless of status code.
    """

    @given(status=st.integers(min_value=200, max_value=299), pattern=content_pattern_st)
    @settings(
        max_examples=30,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_content_patterns_detected_on_success_status(self, status: int, pattern: str):
        """**Validates: Requirements 3.4**

        is_blocked() must return True when body contains a blocked content pattern,
        even when the HTTP status code indicates success (2xx).
        """
        spider = _make_base_spider()
        body = f"<html><body>Some text {pattern} more text</body></html>"
        response = _make_response(status=status, body=body)
        result = asyncio.run(spider.is_blocked(response))
        assert result is True, (
            f"is_blocked() returned False for status {status} with body containing blocked pattern '{pattern}'"
        )

    @given(pattern=content_pattern_st)
    @settings(
        max_examples=20,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_content_patterns_detected_on_any_status(self, pattern: str):
        """**Validates: Requirements 3.4**

        is_blocked() must return True when body contains a blocked content pattern
        for non-blocked status codes like 200.
        """
        spider = _make_base_spider()
        body = f"Response: {pattern}"
        response = _make_response(status=200, body=body)
        result = asyncio.run(spider.is_blocked(response))
        assert result is True, f"is_blocked() returned False for body containing '{pattern}'"


# ---------------------------------------------------------------------------
# Property 2.3: CrawlConfig Env Var Override Preservation (property-based)
# **Validates: Requirements 3.5**
# ---------------------------------------------------------------------------


class TestCrawlConfigOverridePreservation:
    """For all CrawlConfig instances created with env var overrides,
    the overridden values take precedence over defaults.
    """

    @given(concurrency=positive_int_st)
    @settings(
        max_examples=20,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_concurrency_env_override(self, concurrency: int):
        """**Validates: Requirements 3.5**

        GAOKAO_CRAWL__CONCURRENCY env var must override the default concurrency.
        """
        env_patch = {"GAOKAO_CRAWL__CONCURRENCY": str(concurrency)}
        with patch.dict(os.environ, env_patch, clear=False):
            config = CrawlConfig()
        assert config.concurrency == concurrency, (
            f"CrawlConfig.concurrency is {config.concurrency}, expected {concurrency} from env override"
        )

    @given(per_domain=positive_int_st)
    @settings(
        max_examples=20,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_concurrency_per_domain_env_override(self, per_domain: int):
        """**Validates: Requirements 3.5**

        GAOKAO_CRAWL__CONCURRENCY_PER_DOMAIN env var must override the default.
        """
        env_patch = {"GAOKAO_CRAWL__CONCURRENCY_PER_DOMAIN": str(per_domain)}
        with patch.dict(os.environ, env_patch, clear=False):
            config = CrawlConfig()
        assert config.concurrency_per_domain == per_domain, (
            f"CrawlConfig.concurrency_per_domain is {config.concurrency_per_domain}, "
            f"expected {per_domain} from env override"
        )

    @given(delay=positive_float_st)
    @settings(
        max_examples=20,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    def test_base_delay_env_override(self, delay: float):
        """**Validates: Requirements 3.5**

        GAOKAO_CRAWL__BASE_DELAY env var must override the default base_delay.
        """
        env_patch = {"GAOKAO_CRAWL__BASE_DELAY": str(delay)}
        with patch.dict(os.environ, env_patch, clear=False):
            config = CrawlConfig()
        assert abs(config.base_delay - delay) < 1e-6, (
            f"CrawlConfig.base_delay is {config.base_delay}, expected {delay} from env override"
        )


# ---------------------------------------------------------------------------
# Unit Test 2.4: Parse 404 Skip Preservation
# **Validates: Requirements 3.3**
# ---------------------------------------------------------------------------


class TestParse404SkipPreservation:
    """parse() returns early for 404 responses without yielding items."""

    def test_parse_404_yields_nothing(self):
        """**Validates: Requirements 3.3**

        SchoolSpider.parse() must return early for 404 responses
        without yielding any items.
        """
        spider = _make_school_spider()
        response = _make_response(status=404, body="Not Found")
        response.request = MagicMock()
        response.request.meta = {"sch_id": 999}

        items = []
        loop = asyncio.new_event_loop()
        try:

            async def _collect():
                async for item in spider.parse(response):
                    items.append(item)

            loop.run_until_complete(_collect())
        finally:
            loop.close()

        assert len(items) == 0, f"parse() yielded {len(items)} items for 404 response, expected 0"


# ---------------------------------------------------------------------------
# Unit Test 2.5: Parse 200 Extraction Preservation
# **Validates: Requirements 3.2**
# ---------------------------------------------------------------------------

_VALID_SCHOOL_HTML = """
<html>
<body>
<div class="yxxx-header-wrapper">
  <div class="yxxx-header">
    <div class="yxxx-header-img"><img src="https://example.com/logo.png" /></div>
    <div class="yxxx-header-content">
      <div class="content-header">北京大学 <span>28191人关注</span></div>
      <div class="content-introduction">
        <span>教育部</span>
        <span>"双一流"建设高校</span>
      </div>
      <div class="content-info">
        <div class="content-info-item">
          所在地: <span class="yxszd">北京</span>
          详细地址: <span class="txdz" title="北京市海淀区颐和园路5号">北京市海淀区颐和园路5号</span>
        </div>
        <div class="content-info-item">
          官方网址: <a class="gfwz" href="https://www.pku.edu.cn">https://www.pku.edu.cn</a>
          招生网址: <a class="zswz" href="https://www.gotopku.cn/">https://www.gotopku.cn/</a>
        </div>
        <div class="content-info-item">
          官方电话: <span class="gfdh" title="010-62751407">010-62751407</span>
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""


class TestParse200ExtractionPreservation:
    """parse() with valid school HTML extracts school name, tags, detail fields correctly."""

    def test_parse_200_extracts_school_data(self):
        """**Validates: Requirements 3.2**

        SchoolSpider.parse() must extract school name, tags, and detail fields
        from a valid 200 response with school HTML.
        """
        from scrapling.parser import Adaptor

        spider = _make_school_spider()

        # Build a mock response that uses real CSS selector parsing via Adaptor
        adaptor = Adaptor(
            content=_VALID_SCHOOL_HTML,
            url="https://gaokao.chsi.com.cn/sch/schoolInfo--schId-40.dhtml",
        )

        # Create a response mock that delegates css() to the real Adaptor
        response = MagicMock()
        response.status = 200
        response.css = adaptor.css
        response.request = MagicMock()
        response.request.meta = {"sch_id": 40}

        items = []
        loop = asyncio.new_event_loop()
        try:

            async def _collect():
                # Mock process_item to avoid DB calls
                with (
                    patch.object(spider, "_resolve_province_id", new=AsyncMock(return_value=1)),
                    patch.object(spider, "process_item", new=AsyncMock(return_value="new")),
                ):
                    async for item in spider.parse(response):
                        items.append(item)

            loop.run_until_complete(_collect())
        finally:
            loop.close()

        assert len(items) == 1, f"Expected 1 item, got {len(items)}"
        item = items[0]

        # Verify school name
        assert item["name"] == "北京大学", f"School name is '{item.get('name')}', expected '北京大学'"
        assert item["sch_id"] == 40

        # Verify tags
        assert item["is_double_first"] is True, "is_double_first should be True"

        # Verify detail fields
        assert item["city"] == "北京", f"city is '{item.get('city')}', expected '北京'"
        assert item["address"] == "北京市海淀区颐和园路5号"
        assert item["website"] == "https://www.pku.edu.cn"
        assert item["phone"] == "010-62751407"


# ---------------------------------------------------------------------------
# Unit Test 2.6: retry_blocked_request Stealth Switch
# **Validates: Requirements 3.6**
# ---------------------------------------------------------------------------


class TestRetryBlockedRequestPreservation:
    """retry_blocked_request() sets request.sid = "stealth" on block detection."""

    def test_retry_sets_stealth_sid(self):
        """**Validates: Requirements 3.6**

        retry_blocked_request() must set request.sid to "stealth"
        when a blocked response is detected.
        """
        spider = _make_base_spider()
        request = MagicMock()
        request.url = "https://gaokao.chsi.com.cn/sch/schoolInfo--schId-40.dhtml"
        request.sid = "http"

        response = _make_response(status=403, body="Forbidden")

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(spider.retry_blocked_request(request, response))
        finally:
            loop.close()

        assert result.sid == "stealth", (
            f"request.sid is '{result.sid}', expected 'stealth' after retry_blocked_request()"
        )

    def test_retry_returns_same_request(self):
        """**Validates: Requirements 3.6**

        retry_blocked_request() must return the same request object
        (modified in place).
        """
        spider = _make_base_spider()
        request = MagicMock()
        request.url = "https://gaokao.chsi.com.cn/test"
        request.sid = "http"

        response = _make_response(status=500, body="Server Error")

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(spider.retry_blocked_request(request, response))
        finally:
            loop.close()

        assert result is request, "retry_blocked_request() must return the same request object"
