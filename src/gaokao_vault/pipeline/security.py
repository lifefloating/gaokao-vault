from __future__ import annotations

import html
import ipaddress
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

_ALLOWED_SCHEMES = {"http", "https"}
_LOCAL_HOSTNAME = "localhost"
_UNSAFE_METADATA_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "cookie",
    "cookies",
    "crawl_params",
    "headers",
    "params",
    "password",
    "request_headers",
    "secret",
    "token",
}
_UNSAFE_METADATA_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "header",
    "password",
    "proxy",
    "secret",
    "token",
)
_LOOPBACK_MAPPING_SUFFIXES = (
    ".nip.io",
    ".sslip.io",
    ".localtest.me",
)
REDACTION_MARKER = "[REDACTED]"

_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>")
_COMMENT_RE = re.compile(r"(?s)<!--.*?-->")
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+[A-Za-z0-9._~+/-]+=*"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*"),
    re.compile(r"(?i)\bjwt\s+[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)?"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)?\b"),
    re.compile(
        r"(?i)\b(?:token|access[_-]?token|accessToken|cookie|cookies|password|secret|api[_-]?key|apiKey|authorization)\b"
        r"\s*[:=]\s*[^\s;,]+"
    ),
    re.compile(r"\b\d{17}[\dXx]\b"),
    re.compile(r"\b\d{10,}\b"),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)"),
)


def is_public_source_url(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return False

    if parsed.username is not None or parsed.password is not None:
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    normalized_hostname = hostname.rstrip(".").lower()
    if normalized_hostname == _LOCAL_HOSTNAME or normalized_hostname.endswith(f".{_LOCAL_HOSTNAME}"):
        return False

    if _is_loopback_mapping_hostname(normalized_hostname):
        return False

    if _looks_like_noncanonical_ip(normalized_hostname):
        return False

    try:
        address = ipaddress.ip_address(normalized_hostname)
    except ValueError:
        return True

    return not (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    )


def assert_allowed_source_url(url: str) -> str:
    if not is_public_source_url(url):
        msg = "Source URL is not public"
        raise ValueError(msg)
    return url


def sanitize_vector_text(raw: str | None) -> tuple[str, list[str]]:
    if raw is None:
        return "", []

    flags: list[str] = []
    text = html.unescape(raw)

    text, active_content_removed = _substitute_with_count(_SCRIPT_STYLE_RE, " ", text)
    text, comments_removed = _substitute_with_count(_COMMENT_RE, " ", text)
    text, tags_removed = _substitute_with_count(_TAG_RE, " ", text)
    if active_content_removed or comments_removed or tags_removed:
        flags.append("removed_active_content")

    sensitive_redacted = False
    for pattern in _SENSITIVE_PATTERNS:
        text, count = _substitute_with_count(pattern, REDACTION_MARKER, text)
        sensitive_redacted = sensitive_redacted or count > 0

    if sensitive_redacted:
        flags.append("redacted_sensitive_identifier")

    cleaned = _WHITESPACE_RE.sub(" ", text).strip()
    return cleaned, flags


def sanitize_metadata(metadata: Mapping[str, Any] | None) -> dict[str, object]:
    if metadata is None:
        return {}

    sanitized: dict[str, object] = {}
    for key, value in metadata.items():
        if _is_unsafe_metadata_key(key):
            continue
        sanitized[key] = _sanitize_metadata_value(value)
    return sanitized


def _sanitize_metadata_value(value: Any) -> object:
    if isinstance(value, str):
        sanitized_text, _ = sanitize_vector_text(value)
        return sanitized_text

    if isinstance(value, Mapping):
        nested: dict[str, object] = {}
        for key, nested_value in value.items():
            string_key = str(key)
            if _is_unsafe_metadata_key(string_key):
                continue
            nested[string_key] = _sanitize_metadata_value(nested_value)
        return nested

    if isinstance(value, list):
        return [_sanitize_metadata_value(item) for item in value]

    if isinstance(value, tuple):
        return tuple(_sanitize_metadata_value(item) for item in value)

    if value is None or isinstance(value, bool | int | float):
        return value

    sanitized_text, _ = sanitize_vector_text(str(value))
    return sanitized_text


def _substitute_with_count(pattern: re.Pattern[str], replacement: str, text: str) -> tuple[str, int]:
    return pattern.subn(replacement, text)


def _is_unsafe_metadata_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower())
    compact = normalized.replace("_", "")
    if normalized in _UNSAFE_METADATA_KEYS or compact in _UNSAFE_METADATA_KEYS:
        return True
    return any(part in normalized or part in compact for part in _UNSAFE_METADATA_KEY_PARTS)


def _is_loopback_mapping_hostname(hostname: str) -> bool:
    return any(hostname == suffix[1:] or hostname.endswith(suffix) for suffix in _LOOPBACK_MAPPING_SUFFIXES)


def _looks_like_noncanonical_ip(hostname: str) -> bool:
    if hostname.startswith("0x"):
        return True

    labels = hostname.split(".")
    if not labels or len(labels) > 4:
        return False

    if all(label.isdigit() for label in labels):
        return True

    return any(label.startswith(("0x", "0X")) for label in labels)
