"""Property-based and unit tests for the OpenAI health check module."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import openai
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from gaokao_vault.config import OpenAIConfig
from gaokao_vault.health import HealthResult, check_openai_health

valid_api_key_st = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
    min_size=1,
    max_size=128,
)

valid_api_base_st = st.just("https://api.openai.com/v1") | st.from_regex(
    r"https://[a-z0-9]+\.[a-z]{2,6}/v[0-9]",
    fullmatch=True,
)

_PATCH_TARGET = "gaokao_vault.health.create_openai_client"


class _FakeStream:
    """Async-iterable mock that yields a text delta event then stops."""

    def __init__(self) -> None:
        self._events = [
            MagicMock(type="response.created"),
            MagicMock(type="response.output_text.delta", delta="hi"),
        ]
        self._index = 0
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._events):
            raise StopAsyncIteration
        event = self._events[self._index]
        self._index += 1
        return event

    async def close(self):
        self.closed = True


_fake_request = MagicMock()
_fake_response = MagicMock()
_fake_response.status_code = 500


def _make_mock_client_stream() -> AsyncMock:
    mock_client = AsyncMock()
    mock_client.responses.create = AsyncMock(return_value=_FakeStream())
    return mock_client


def _make_mock_client_error(exc: Exception) -> AsyncMock:
    mock_client = AsyncMock()
    mock_client.responses.create = AsyncMock(side_effect=exc)
    return mock_client


class TestSuccessResponseMapping:
    @given(api_key=valid_api_key_st, api_base=valid_api_base_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    def test_success_always_returns_ok(self, api_key: str, api_base: str) -> None:
        config = OpenAIConfig(api_key=api_key, api_base=api_base)

        with patch(_PATCH_TARGET, return_value=_make_mock_client_stream()):
            result = asyncio.run(check_openai_health(config))

        assert result == HealthResult(ok=True, message="ok")


whitespace_only_st = st.text(
    alphabet=st.characters(whitelist_categories=("Zs",)),
    min_size=0,
    max_size=20,
)


class TestEmptyApiKeyRejection:
    @given(api_key=whitespace_only_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    def test_empty_or_whitespace_key_is_rejected(self, api_key: str) -> None:
        config = OpenAIConfig(api_key=api_key, api_base="https://api.openai.com/v1")

        with patch(_PATCH_TARGET) as mock_factory:
            result = asyncio.run(check_openai_health(config))
            mock_factory.assert_not_called()

        assert result == HealthResult(ok=False, message="OPENAI_API_KEY not configured")


error_st = st.sampled_from([
    ("auth", openai.AuthenticationError(message="invalid key", response=_fake_response, body=None)),
    ("status_500", openai.InternalServerError(message="server error", response=_fake_response, body=None)),
    ("timeout", openai.APITimeoutError(request=_fake_request)),
    ("connect", openai.APIConnectionError(request=_fake_request)),
    ("runtime", RuntimeError("boom")),
])


class TestApiExceptionMapping:
    @given(api_key=valid_api_key_st, api_base=valid_api_base_st, error=error_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    def test_any_error_maps_to_failed_result(self, api_key: str, api_base: str, error: tuple) -> None:
        config = OpenAIConfig(api_key=api_key, api_base=api_base)
        _error_kind, exc = error

        with patch(_PATCH_TARGET, return_value=_make_mock_client_error(exc)):
            result = asyncio.run(check_openai_health(config))

        assert result.ok is False
        assert len(result.message) > 0


class TestCheckOpenaiHealthUnit:
    def _run_with_exception(self, exc: Exception) -> HealthResult:
        config = OpenAIConfig(api_key="sk-test", api_base="https://api.openai.com/v1")
        with patch(_PATCH_TARGET, return_value=_make_mock_client_error(exc)):
            return asyncio.run(check_openai_health(config))

    def test_auth_error_message(self) -> None:
        exc = openai.AuthenticationError(message="bad key", response=_fake_response, body=None)
        result = self._run_with_exception(exc)
        assert result.ok is False
        assert "Authentication failed" in result.message

    def test_timeout_exception_message(self) -> None:
        exc = openai.APITimeoutError(request=_fake_request)
        result = self._run_with_exception(exc)
        assert result.ok is False
        assert "timed out" in result.message

    def test_connect_error_message(self) -> None:
        exc = openai.APIConnectionError(request=_fake_request)
        result = self._run_with_exception(exc)
        assert result.ok is False
        assert "Connection failed" in result.message

    def test_client_created_with_correct_params(self) -> None:
        config = OpenAIConfig(api_key="sk-test", api_base="https://api.openai.com/v1")
        with patch(_PATCH_TARGET, return_value=_make_mock_client_stream()) as mock_factory:
            asyncio.run(check_openai_health(config))
            mock_factory.assert_called_once_with(config, timeout=10.0, max_retries=0)

    def test_calls_responses_create_with_correct_params(self) -> None:
        config = OpenAIConfig(api_key="sk-test", api_base="https://api.openai.com/v1")
        mock_client = _make_mock_client_stream()
        with patch(_PATCH_TARGET, return_value=mock_client):
            asyncio.run(check_openai_health(config))
            mock_client.responses.create.assert_called_once_with(
                model="gpt-5.4",
                input="hi",
                max_output_tokens=5,
                stream=True,
            )

    def test_stream_closed_after_first_event(self) -> None:
        config = OpenAIConfig(api_key="sk-test", api_base="https://api.openai.com/v1")
        fake_stream = _FakeStream()
        mock_client = AsyncMock()
        mock_client.responses.create = AsyncMock(return_value=fake_stream)
        with patch(_PATCH_TARGET, return_value=mock_client):
            result = asyncio.run(check_openai_health(config))
        assert result.ok is True
        assert fake_stream.closed is True
