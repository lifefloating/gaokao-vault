from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from gaokao_vault.cli import app

runner = CliRunner()


class _FakeAcquire:
    def __init__(self, conn: object) -> None:
        self.conn = conn

    async def __aenter__(self) -> object:
        return self.conn

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakePool:
    def __init__(self, conn: object) -> None:
        self.conn = conn

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self.conn)


class TestAuditCompletenessCommandRegistered:
    def test_audit_completeness_command_exists(self) -> None:
        func_names = [getattr(cmd.callback, "__name__", None) for cmd in app.registered_commands if cmd.callback]
        assert "audit_completeness" in func_names


class TestAuditCompletenessCommandExecution:
    @patch("gaokao_vault.db.connection.close_pool", new_callable=AsyncMock)
    @patch("gaokao_vault.db.queries.data_quality.fetch_school_year_plan_gaps", new_callable=AsyncMock)
    @patch("gaokao_vault.db.queries.data_quality.fetch_year_data_coverage", new_callable=AsyncMock)
    @patch("gaokao_vault.db.connection.create_pool", new_callable=AsyncMock)
    def test_prints_year_coverage_and_plan_gaps(
        self,
        mock_create_pool,
        mock_fetch_coverage,
        mock_fetch_gaps,
        mock_close_pool,
    ) -> None:
        conn = MagicMock()
        mock_create_pool.return_value = _FakePool(conn)
        mock_fetch_coverage.return_value = [
            {
                "province_name": "吉林",
                "year": 2024,
                "admission_schools": 210,
                "admission_records": 1234,
                "admission_records_with_plan_count": 1100,
                "admission_records_with_major_group_code": 1190,
                "plan_schools": 198,
                "plan_records": 1100,
                "plan_records_with_plan_count": 1100,
                "plan_records_with_major_group_code": 1100,
                "plan_records_with_selection_requirement": 1100,
                "plan_count_sum": 4500,
                "missing_plan_schools": 12,
            }
        ]
        mock_fetch_gaps.return_value = [
            {
                "year": 2024,
                "school_id": 123,
                "school_name": "长春工业大学",
                "admission_records": 42,
                "admission_records_with_plan_count": 0,
                "plan_records": 0,
                "plan_count_sum": None,
            }
        ]

        result = runner.invoke(
            app,
            ["audit-completeness", "--province", "吉林", "--year", "2023", "--year", "2024", "--year", "2025"],
        )

        assert result.exit_code == 0
        assert "Coverage by year" in result.stdout
        assert "2024" in result.stdout
        assert "admission_records_with_major_group_code=1190" in result.stdout
        assert "plan_records_with_selection_requirement=1100" in result.stdout
        assert "plan_count_sum=4500" in result.stdout
        assert "Missing enrollment plans" in result.stdout
        assert "长春工业大学" in result.stdout
        mock_create_pool.assert_awaited_once()
        mock_fetch_coverage.assert_awaited_once_with(conn, province="吉林", years=[2023, 2024, 2025])
        mock_fetch_gaps.assert_awaited_once_with(conn, province="吉林", years=[2023, 2024, 2025], limit=50)
        mock_close_pool.assert_awaited_once()

    @patch("gaokao_vault.db.connection.close_pool", new_callable=AsyncMock)
    @patch("gaokao_vault.db.queries.data_quality.fetch_school_year_plan_gaps", new_callable=AsyncMock)
    @patch("gaokao_vault.db.queries.data_quality.fetch_year_data_coverage", new_callable=AsyncMock)
    @patch("gaokao_vault.db.queries.data_quality.date")
    @patch("gaokao_vault.db.connection.create_pool", new_callable=AsyncMock)
    def test_defaults_to_dynamic_recent_three_years(
        self,
        mock_create_pool,
        mock_date,
        mock_fetch_coverage,
        mock_fetch_gaps,
        mock_close_pool,
    ) -> None:
        mock_date.today.return_value = date(2026, 12, 1)
        conn = MagicMock()
        mock_create_pool.return_value = _FakePool(conn)
        mock_fetch_coverage.return_value = []
        mock_fetch_gaps.return_value = []

        result = runner.invoke(app, ["audit-completeness", "--province", "吉林"])

        assert result.exit_code == 0
        mock_fetch_coverage.assert_awaited_once_with(conn, province="吉林", years=[2024, 2025, 2026])
        mock_fetch_gaps.assert_awaited_once_with(conn, province="吉林", years=[2024, 2025, 2026], limit=50)
        mock_close_pool.assert_awaited_once()
