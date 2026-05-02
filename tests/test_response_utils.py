from __future__ import annotations

from unittest.mock import MagicMock

from gaokao_vault.spiders.response_utils import response_json, response_text


def test_response_text_prefers_text_attribute() -> None:
    response = MagicMock()
    response.text = '{"ok": true}'
    response.body = b'{"ok": false}'

    assert response_text(response) == '{"ok": true}'


def test_response_json_decodes_body_when_text_is_empty() -> None:
    response = MagicMock()
    response.text = ""
    response.body = b'{"ok": true}'

    assert response_json(response) == {"ok": True}


def test_response_json_rejects_invalid_or_non_object_payloads() -> None:
    response = MagicMock()
    response.text = "[1, 2, 3]"
    response.body = b""

    assert response_json(response) is None

    response.text = "{"
    assert response_json(response) is None
