from __future__ import annotations

import pytest


def test_sanitize_vector_text_removes_scripts_and_tokens() -> None:
    from gaokao_vault.pipeline.security import sanitize_vector_text

    raw = "<script>alert(1)</script>招生计划 token=abc123 身份证号 220102199901011234"
    text, flags = sanitize_vector_text(raw)

    assert "script" not in text.lower()
    assert "abc123" not in text
    assert "220102199901011234" not in text
    assert "redacted_sensitive_identifier" in flags


def test_sanitize_vector_text_removes_html_and_contact_data() -> None:
    from gaokao_vault.pipeline.security import sanitize_vector_text

    raw = (
        "<style>body{display:none}</style><!-- hidden -->"
        "<div>请联系 test@example.com 或 13800138000, 准考证 123456789012。</div>"
    )
    text, flags = sanitize_vector_text(raw)

    assert "display:none" not in text
    assert "hidden" not in text
    assert "test@example.com" not in text
    assert "13800138000" not in text
    assert "123456789012" not in text
    assert "removed_active_content" in flags
    assert "redacted_sensitive_identifier" in flags


def test_public_source_url_rejects_private_targets() -> None:
    from gaokao_vault.pipeline.security import is_public_source_url

    assert is_public_source_url("https://www.jleea.com.cn/site1/xiangqingye/201719/")
    assert not is_public_source_url("http://127.0.0.1/admin")
    assert not is_public_source_url("file:///etc/passwd")


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "http://internal.localhost/admin",
        "http://10.0.0.1/admin",
        "http://192.168.1.2/admin",
        "http://172.16.0.1/admin",
        "http://[::1]/admin",
    ],
)
def test_public_source_url_rejects_localhost_and_private_ips(url: str) -> None:
    from gaokao_vault.pipeline.security import is_public_source_url

    assert not is_public_source_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://2130706433/admin",
        "http://0x7f000001/admin",
        "http://0177.0.0.1/admin",
        "http://127.1/admin",
    ],
)
def test_public_source_url_rejects_noncanonical_ip_hosts(url: str) -> None:
    from gaokao_vault.pipeline.security import is_public_source_url

    assert not is_public_source_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1.nip.io/admin",
        "http://10.0.0.1.sslip.io/admin",
        "http://localtest.me/admin",
    ],
)
def test_public_source_url_rejects_loopback_mapping_domains(url: str) -> None:
    from gaokao_vault.pipeline.security import is_public_source_url

    assert not is_public_source_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://user@example.com/path",
        "https://user:pass@example.com/path",
    ],
)
def test_public_source_url_rejects_credentials(url: str) -> None:
    from gaokao_vault.pipeline.security import is_public_source_url

    assert not is_public_source_url(url)


def test_sanitize_metadata_drops_unsafe_keys_case_insensitively() -> None:
    from gaokao_vault.pipeline.security import sanitize_metadata

    metadata = {
        "Cookie": "sessionid=abc",
        "authorization": "Bearer token",
        "headers": {"X-Test": "1"},
        "request_headers": {"X-Test": "2"},
        "token": "abc123",
        "password": "pw",
        "secret": "shh",
        "crawl_params": {"page": 1},
        "params": {"size": 10},
        "safe_key": "招生计划",
    }

    sanitized = sanitize_metadata(metadata)

    assert sanitized == {"safe_key": "招生计划"}


def test_sanitize_metadata_recurses_and_redacts_sensitive_strings() -> None:
    from gaokao_vault.pipeline.security import sanitize_metadata

    metadata = {
        "title": "<b>招生计划</b>",
        "nested": {
            "contact": "电话 13800138000",
            "items": ["token=abc123", {"email": "test@example.com"}],
        },
        "tuple_value": ("cookie=abcdef", 42, None),
        "enabled": True,
    }

    sanitized = sanitize_metadata(metadata)

    assert sanitized["title"] == "招生计划"
    assert sanitized["nested"] == {
        "contact": "电话 [REDACTED]",
        "items": ["[REDACTED]", {"email": "[REDACTED]"}],
    }
    assert sanitized["tuple_value"] == ("[REDACTED]", 42, None)
    assert sanitized["enabled"] is True


def test_sanitize_metadata_drops_secret_key_variants() -> None:
    from gaokao_vault.pipeline.security import sanitize_metadata

    metadata = {
        "nested": {
            "set_cookie": "session=abc",
            "x_api_key": "secret123",
            "accessToken": "abc123",
            "proxy_url": "http://user:pass@proxy.example",
            "public": "招生计划",
        }
    }

    assert sanitize_metadata(metadata) == {"nested": {"public": "招生计划"}}


def test_sanitize_vector_text_redacts_bearer_jwt_and_camelcase_secrets() -> None:
    from gaokao_vault.pipeline.security import sanitize_vector_text

    raw = (
        "Authorization: Bearer abc.def.ghi "
        "accessToken: secret-token "
        "apiKey=key-123 "
        "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature"
    )

    text, flags = sanitize_vector_text(raw)

    assert "Bearer" not in text
    assert "abc.def.ghi" not in text
    assert "secret-token" not in text
    assert "key-123" not in text
    assert "eyJhbGciOiJIUzI1NiJ9" not in text
    assert "redacted_sensitive_identifier" in flags


def test_assert_allowed_source_url_raises_for_non_public_url() -> None:
    from gaokao_vault.pipeline.security import assert_allowed_source_url

    with pytest.raises(ValueError):
        assert_allowed_source_url("http://127.0.0.1/admin")


def test_assert_allowed_source_url_error_message_does_not_echo_url() -> None:
    from gaokao_vault.pipeline.security import assert_allowed_source_url

    with pytest.raises(ValueError) as exc_info:
        assert_allowed_source_url("https://user:pass@example.com/?token=abc123")

    message = str(exc_info.value)
    assert "user:pass" not in message
    assert "token=abc123" not in message


def test_assert_allowed_source_url_returns_public_url() -> None:
    from gaokao_vault.pipeline.security import assert_allowed_source_url

    url = "https://gaokao.chsi.com.cn/gkxx/index.shtml"

    assert assert_allowed_source_url(url) == url
