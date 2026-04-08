"""OpenAI API health check module."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import openai

from gaokao_vault.config import OpenAIConfig, create_openai_client


@dataclass(frozen=True)
class HealthResult:
    """Result of an OpenAI API health check."""

    ok: bool
    message: str


async def _consume_first_text_delta(stream) -> bool:
    """Consume events until a text delta arrives (or stream ends), then close."""
    got_content = False
    try:
        async for event in stream:
            if event.type == "response.output_text.delta" and event.delta:
                got_content = True
                break
    finally:
        await stream.close()
    return got_content


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

    client = create_openai_client(config, timeout=timeout, max_retries=0)

    try:
        stream = await client.responses.create(
            model=config.health_model,
            input="hi",
            max_output_tokens=5,
            stream=True,
        )
        got_content = await asyncio.wait_for(_consume_first_text_delta(stream), timeout=timeout)
        if not got_content:
            return HealthResult(ok=False, message="API connected but no text content generated")
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
