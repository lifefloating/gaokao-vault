"""Unit tests for the CLI schedule command."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from gaokao_vault.cli import app

runner = CliRunner()


class TestScheduleCommandRegistered:
    def test_schedule_command_exists(self) -> None:
        command_names = list(app.registered_commands)
        func_names = [getattr(cmd.callback, "__name__", None) for cmd in command_names if cmd.callback]
        assert "schedule" in func_names


class TestScheduleCommandExecution:
    @patch("gaokao_vault.scheduler.cron_runner.IncrementalCronScheduler")
    @patch("gaokao_vault.config.AppConfig")
    def test_schedule_command_loads_config_and_runs_scheduler(
        self,
        mock_config_cls,
        mock_scheduler_cls,
    ) -> None:
        config = MagicMock()
        config.crawl.log_dir = None
        scheduler = MagicMock()
        scheduler.run_forever = AsyncMock()
        mock_config_cls.return_value = config
        mock_scheduler_cls.return_value = scheduler

        result = runner.invoke(app, ["schedule"])

        assert result.exit_code == 0
        mock_config_cls.assert_called_once()
        mock_scheduler_cls.assert_called_once_with(config)
        scheduler.run_forever.assert_awaited_once()
