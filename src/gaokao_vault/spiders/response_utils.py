from __future__ import annotations

import json
from typing import Any

from scrapling.spiders import Response


def response_json(response: Response) -> dict[str, Any] | None:
    text = response_text(response)
    if not text:
        return None
    try:
        result = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return result if isinstance(result, dict) else None


def response_text(response: Response) -> str:
    text = getattr(response, "text", "")
    if isinstance(text, str) and text:
        return text
    body = getattr(response, "body", b"")
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="ignore")
    return ""
