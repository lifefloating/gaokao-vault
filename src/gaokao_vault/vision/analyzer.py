"""VisionAnalyzer: Analyze score line screenshots using OpenAI Vision API."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

from openai import AsyncOpenAI

from gaokao_vault.config import OpenAIConfig

logger = logging.getLogger(__name__)

__all__ = ["VisionAnalyzer"]

_API_TIMEOUT = 60  # seconds


class VisionAnalyzer:
    """Extract structured score-line data from a screenshot via OpenAI Vision API."""

    def __init__(self, config: OpenAIConfig) -> None:
        self.client = AsyncOpenAI(base_url=config.api_base, api_key=config.api_key)

    async def analyze(
        self,
        image_path: Path,
        province_name: str,
        year: int,
    ) -> list[dict]:
        """Read a local screenshot, send it to the Vision API, and return parsed records.

        Returns an empty list on any failure (timeout, non-JSON response, etc.).
        """
        try:
            image_b64 = self._encode_image(image_path)
        except Exception:
            logger.exception("Failed to read image %s", image_path)
            return []

        prompt = self._build_prompt(province_name, year)

        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_b64}",
                                },
                            },
                        ],
                    },
                ],
                timeout=_API_TIMEOUT,
            )
        except Exception:
            logger.exception("Vision API call failed for %s %d", province_name, year)
            return []

        content = (response.choices[0].message.content or "").strip()
        return self._parse_response(content, province_name, year)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, province_name: str, year: int) -> str:
        """Construct the extraction prompt by loading the template from prompts/ directory."""
        template_path = Path(__file__).parent / "prompts" / "score_line_extract.txt"
        template = template_path.read_text(encoding="utf-8")
        return template.format(province_name=province_name, year=year)

    def _encode_image(self, image_path: Path) -> str:
        """Read an image file and return its base64-encoded string."""
        return base64.b64encode(image_path.read_bytes()).decode("utf-8")

    def _parse_response(self, content: str, province_name: str, year: int) -> list[dict]:
        """Try to parse the AI response as a JSON list of score-line records."""
        # Strip possible markdown code fences
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content.rsplit("```", 1)[0]
        content = content.strip()

        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            logger.exception(
                "Non-JSON response from Vision API for %s %d: %.200s",
                province_name,
                year,
                content,
            )
            return []

        if not isinstance(data, list):
            logger.error(
                "Vision API returned non-list JSON for %s %d",
                province_name,
                year,
            )
            return []

        return data
