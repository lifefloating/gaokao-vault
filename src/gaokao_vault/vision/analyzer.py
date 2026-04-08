"""VisionAnalyzer: Analyze score line screenshots using OpenAI Vision API."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from openai.types.responses import EasyInputMessageParam, ResponseInputImageParam, ResponseInputTextParam

from gaokao_vault.config import OpenAIConfig, create_openai_client

if TYPE_CHECKING:
    from gaokao_vault.storage.s3 import S3Storage

logger = logging.getLogger(__name__)

__all__ = ["VisionAnalyzer"]

_API_TIMEOUT = 60  # seconds


class VisionAnalyzer:
    """Extract structured score-line data from a screenshot via OpenAI Responses API."""

    def __init__(self, config: OpenAIConfig, s3: S3Storage | None = None) -> None:
        self._model = config.vision_model
        self._s3 = s3
        self.client = create_openai_client(config, timeout=180, max_retries=3)

    async def analyze(
        self,
        image_path: Path,
        province_name: str,
        year: int,
    ) -> list[dict]:
        """Read a local screenshot, send it to the Vision API, and return parsed records.

        Returns an empty list on any failure (timeout, non-JSON response, etc.).
        """
        image_url = await asyncio.to_thread(self._resolve_image_url, image_path, province_name, year)
        if image_url is None:
            return []

        prompt = self._build_prompt(province_name, year)

        try:
            input_msg: EasyInputMessageParam = {
                "role": "user",
                "content": [
                    ResponseInputTextParam(type="input_text", text=prompt),
                    ResponseInputImageParam(
                        type="input_image",
                        detail="auto",
                        image_url=image_url,
                    ),
                ],
            }
            # Use streaming to work around proxies that don't populate the
            # non-streaming ``output`` field but do send text via SSE deltas.
            stream = await self.client.responses.create(
                model=self._model,
                input=[input_msg],
                stream=True,
            )
            content = ""
            async for event in stream:
                if event.type == "response.output_text.delta":
                    content += event.delta
            await stream.close()
            content = content.strip()
        except Exception:
            logger.exception("Vision API call failed for %s %d", province_name, year)
            return []

        if not content:
            logger.warning("Vision API returned empty content for %s %d", province_name, year)
            return []
        return self._parse_response(content, province_name, year)

    def _resolve_image_url(self, image_path: Path, province_name: str, year: int) -> str | None:
        """Upload to S3 and return presigned URL, or fall back to base64 data URL."""
        if self._s3:
            try:
                key = f"screenshots/{province_name}/{year}/{image_path.name}"
                self._s3.upload_image(image_path, key)
                url = self._s3.presigned_url(key)
                logger.debug("Using S3 presigned URL for %s", image_path.name)
            except Exception:
                logger.exception("S3 upload failed for %s, falling back to base64", image_path)
            else:
                return url

        try:
            image_b64 = self._encode_image(image_path)
        except Exception:
            logger.exception("Failed to read image %s", image_path)
            return None
        else:
            return f"data:image/png;base64,{image_b64}"

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
