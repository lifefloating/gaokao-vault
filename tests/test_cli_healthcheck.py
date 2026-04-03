"""Unit tests for the CLI healthcheck command.

**Validates: Requirements 1.1, 1.2, 1.5, 1.6, 1.7, 1.8**
"""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from gaokao_vault.cli import app
from gaokao_vault.health import HealthResult

runner = CliRunner()


class TestHealthcheckCommandRegistered:
    def test_healthcheck_command_exists(self) -> None:
        command_names = list(app.registered_commands)
        func_names = [getattr(cmd.callback, "__name__", None) for cmd in command_names if cmd.callback]
        assert "healthcheck" in func_names


class TestHealthcheckSuccess:
    @patch("gaokao_vault.health.check_openai_health")
    @patch("gaokao_vault.config.OpenAIConfig")
    def test_success_prints_ok_to_stdout(self, mock_config_cls, mock_check) -> None:
        mock_check.return_value = HealthResult(ok=True, message="ok")
        result = runner.invoke(app, ["healthcheck"])
        assert result.exit_code == 0
        assert "ok" in result.stdout


class TestHealthcheckFailure:
    @patch("gaokao_vault.health.check_openai_health")
    @patch("gaokao_vault.config.OpenAIConfig")
    def test_failure_exits_1(self, mock_config_cls, mock_check) -> None:
        mock_check.return_value = HealthResult(ok=False, message="Authentication failed: invalid key")
        result = runner.invoke(app, ["healthcheck"])
        assert result.exit_code == 1
        assert "Authentication failed" in result.output


class TestHealthcheckLoadsConfig:
    @patch("gaokao_vault.health.check_openai_health")
    @patch("gaokao_vault.config.OpenAIConfig")
    def test_config_loaded_from_env(self, mock_config_cls, mock_check) -> None:
        mock_check.return_value = HealthResult(ok=True, message="ok")
        runner.invoke(app, ["healthcheck"])
        mock_config_cls.assert_called_once()
        mock_check.assert_called_once_with(mock_config_cls.return_value)
