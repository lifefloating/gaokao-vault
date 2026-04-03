"""OpenAI API health check module."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import openai
from openai import AsyncOpenAI

from gaokao_vault.config import OpenAIConfig


@dataclass(frozen=True)
class HealthResult:
    """Result of an OpenAI API health check."""

    ok: bool
    message: str


async def _consume_first_event(stream) -> None:
    """Consume only the first SSE event, then close the stream."""
    try:
        async for _event in stream:
            break
    finally:
        await stream.close()


async def check_openai_health(
    config: OpenAIConfig,
    timeout: float = 10.0,
) -> HealthResult:
    """Verify OpenAI API connectivity.

    Sends a minimal streaming ``responses.create`` request as a probe
    using the official OpenAI Python SDK.  Streaming mode is used because
    many third-party OpenAI-compatible proxies only support the streaming
    variant of the Responses API.

    Args:
        config: OpenAI configuration with api_base and api_key.
        timeout: Request timeout in seconds.

    Returns:
        A :class:`HealthResult` indicating success or the reason for failure.
    """
    if not config.api_key or not config.api_key.strip():
        return HealthResult(ok=False, message="OPENAI_API_KEY not configured")

    client = AsyncOpenAI(
        base_url=config.api_base,
        api_key=config.api_key,
        timeout=timeout,
        max_retries=0,
    )

    try:
        stream = await client.responses.create(
            model=config.health_model,
            input="hi",
            max_output_tokens=1,
            stream=True,
        )
        await asyncio.wait_for(_consume_first_event(stream), timeout=timeout)
        return HealthResult(ok=True, message="ok")
    except openai.AuthenticationError:
        return HealthResult(ok=False, message="Authentication failed: HTTP 401")
    except openai.PermissionDeniedError:
        return HealthResult(ok=False, message="Authentication failed: HTTP 403")
    except (openai.APITimeoutError, TimeoutError, asyncio.TimeoutError):
        return HealthResult(ok=False, message=f"Request timed out after {timeout}s")
    except openai.APIConnectionError as exc:
        return HealthResult(ok=False, message=f"Connection failed: {exc}")
    except openai.APIStatusError as exc:
        return HealthResult(
            ok=False,
            message=f"Unexpected status {exc.status_code}: {str(exc)[:200]}",
        )
    except Exception as exc:
        return HealthResult(ok=False, message=f"Unexpected error: {exc}")
