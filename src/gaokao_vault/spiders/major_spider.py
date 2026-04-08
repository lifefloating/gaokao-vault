from __future__ import annotations

import json
import logging

from scrapling.spiders import Request, Response

from gaokao_vault.constants import BASE_URL, TaskType
from gaokao_vault.db.queries.majors import (
    upsert_major,
    upsert_major_category,
    upsert_major_subcategory,
)
from gaokao_vault.models.major import MajorCategoryItem, MajorItem, MajorSubcategoryItem
from gaokao_vault.pipeline.validator import validate_item
from gaokao_vault.spiders.base import BLOCKED_STATUS_CODES, BaseGaokaoSpider

logger = logging.getLogger(__name__)

# Education level code → label mapping
# ccCategory API returns keys like "1050" (本科普通教育), "1051" (本科职业教育), "1060" (专科)
CC_LEVELS = {
    "本科": "1050",
    "专科": "1060",
}

_ZYK_API = f"{BASE_URL}/zyk/zybk"


class MajorSpider(BaseGaokaoSpider):
    """Crawl majors via the Vue SPA JSON API endpoints.

    API chain: ccCategory → mlCategory → xkCategory → specialityesByCategory
    All endpoints return ``{"msg": [...], "flag": true}`` JSON.
    """

    name: str = "major_spider"
    task_type: str = TaskType.MAJORS

    # Kwargs forwarded to the stealth session for every API request so the
    # browser presents a Google-search referer and waits for any JS challenge.
    _STEALTH_KWARGS: dict = {"google_search": False, "network_idle": True}  # noqa: RUF012

    async def start_requests(self):
        # Warmup: visit the SPA page to establish cookies/session
        yield Request(
            f"{_ZYK_API}/",
            callback=self.parse_warmup,
            sid="stealth",
            **self._STEALTH_KWARGS,
        )

    async def parse_warmup(self, response: Response):
        """After warmup, request mlCategory for each education level."""
        logger.info("Major spider warmup completed: status=%s", response.status)
        for level_label, cc_key in CC_LEVELS.items():
            url = f"{_ZYK_API}/mlCategory/{cc_key}"
            yield Request(
                url,
                callback=self.parse_ml_categories,
                sid="stealth",
                meta={"education_level": level_label, "cc_key": cc_key},
                **self._STEALTH_KWARGS,
            )

    async def parse_ml_categories(self, response: Response):
        """Parse door-category (门类) list and request xkCategory for each."""
        if response.request is None:
            return
        meta = response.request.meta
        education_level = meta.get("education_level", "本科")

        items = _parse_api_response(response)
        if items is None:
            logger.warning(
                "Failed to parse mlCategory response for %s (HTTP %s, url=%s)",
                education_level,
                response.status,
                response.url,
            )
            return

        for ml in items:
            ml_key = ml.get("key", "")
            ml_name = ml.get("name", "")
            if not ml_key or not ml_name:
                continue

            # Persist the major category (门类)
            cat_data = validate_item(
                MajorCategoryItem,
                {"name": ml_name, "education_level": education_level, "code": ml_key},
            )
            cat_id = None
            if cat_data:
                async with (await self._get_pool()).acquire() as conn:
                    cat_id = await upsert_major_category(conn, cat_data)
                    self._stats["new"] += 1
                    self._maybe_heartbeat()

            # Request subcategories (专业类)
            url = f"{_ZYK_API}/xkCategory/{ml_key}"
            yield Request(
                url,
                callback=self.parse_xk_categories,
                sid="stealth",
                meta={
                    "education_level": education_level,
                    "category_id": cat_id,
                    "ml_name": ml_name,
                },
                **self._STEALTH_KWARGS,
            )

    async def parse_xk_categories(self, response: Response):
        """Parse subcategory (专业类) list and request specialities for each."""
        if response.request is None:
            return
        meta = response.request.meta
        education_level = meta.get("education_level", "本科")
        category_id = meta.get("category_id")

        items = _parse_api_response(response)
        if items is None:
            logger.warning("Failed to parse xkCategory response (HTTP %s, url=%s)", response.status, response.url)
            return

        for xk in items:
            xk_key = xk.get("key", "")
            xk_name = xk.get("name", "")
            if not xk_key or not xk_name:
                continue

            # Persist the subcategory (专业类)
            sub_data = validate_item(
                MajorSubcategoryItem,
                {"category_id": category_id, "name": xk_name, "code": xk_key},
            )
            sub_id = None
            if sub_data:
                async with (await self._get_pool()).acquire() as conn:
                    sub_id = await upsert_major_subcategory(conn, sub_data)
                    self._stats["new"] += 1
                    self._maybe_heartbeat()

            # Request individual majors (专业列表)
            url = f"{_ZYK_API}/specialityesByCategory/{xk_key}"
            yield Request(
                url,
                callback=self.parse_specialities,
                sid="stealth",
                meta={
                    "education_level": education_level,
                    "subcategory_id": sub_id,
                },
                **self._STEALTH_KWARGS,
            )

    async def parse_specialities(self, response: Response):
        """Parse speciality (专业) list from JSON API."""
        if response.request is None:
            return
        meta = response.request.meta
        education_level = meta.get("education_level", "本科")
        subcategory_id = meta.get("subcategory_id")

        items = _parse_api_response(response)
        if items is None:
            logger.warning("Failed to parse specialities response (HTTP %s, url=%s)", response.status, response.url)
            return

        for spec in items:
            code = spec.get("zydm", "")
            name = spec.get("zymc", "")
            spec_id = spec.get("specId", "")
            satisfaction = spec.get("zymyd", "")

            if not name:
                continue

            data = {
                "source_id": spec_id,
                "subcategory_id": subcategory_id,
                "name": name,
                "code": code,
                "education_level": education_level,
            }
            if satisfaction and satisfaction != "0.0":
                data["satisfaction_score"] = satisfaction

            item = validate_item(MajorItem, data)
            if item:
                yield item
                await self.process_item(
                    item,
                    entity_type="majors",
                    unique_keys={"code": code, "education_level": education_level},
                    upsert_fn=upsert_major,
                )


def _parse_api_response(response: Response) -> list[dict] | None:
    """Parse the standard API response format: {"msg": [...], "flag": true}.

    Uses ``response.body`` instead of ``response.text`` because the stealth
    browser session returns an empty ``text`` for JSON API endpoints (the DOM
    has no meaningful text nodes), while ``body`` contains the raw bytes.
    """
    if response.status in BLOCKED_STATUS_CODES:
        logger.warning("API blocked (HTTP %s) for %s", response.status, response.url)
        return None

    raw = response.body
    if not raw:
        logger.warning("API response body is empty (HTTP %s) for %s", response.status, response.url)
        return None

    try:
        result = json.loads(raw)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        logger.warning(
            "API response is not valid JSON (HTTP %s) for %s: %.200s",
            response.status,
            response.url,
            raw.decode("utf-8", errors="replace")[:200],
        )
        return None

    if not isinstance(result, dict) or not result.get("flag"):
        logger.warning(
            "API response missing flag or not dict (HTTP %s) for %s: %.200s",
            response.status,
            response.url,
            raw.decode("utf-8", errors="replace")[:200],
        )
        return None

    msg = result.get("msg")
    if not isinstance(msg, list):
        logger.warning(
            "API msg is not a list: type=%s (HTTP %s) for %s", type(msg).__name__, response.status, response.url
        )
        return None
    return msg
