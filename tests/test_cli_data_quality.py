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

    def test_audit_major_readiness_command_exists(self) -> None:
        func_names = [getattr(cmd.callback, "__name__", None) for cmd in app.registered_commands if cmd.callback]
        assert "audit_major_readiness" in func_names


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


class TestAuditMajorReadinessCommandExecution:
    @patch("gaokao_vault.db.connection.close_pool", new_callable=AsyncMock)
    @patch("gaokao_vault.db.queries.data_quality.fetch_major_answer_readiness_gaps", new_callable=AsyncMock)
    @patch("gaokao_vault.db.queries.data_quality.fetch_major_strength_signal_diagnostics", new_callable=AsyncMock)
    @patch(
        "gaokao_vault.db.queries.data_quality.fetch_major_answer_readiness_match_diagnostics", new_callable=AsyncMock
    )
    @patch("gaokao_vault.db.queries.data_quality.fetch_major_answer_readiness_summary", new_callable=AsyncMock)
    @patch("gaokao_vault.db.connection.create_pool", new_callable=AsyncMock)
    def test_prints_major_readiness_gaps(
        self,
        mock_create_pool,
        mock_fetch_summary,
        mock_fetch_match_diagnostics,
        mock_fetch_strength_diagnostics,
        mock_fetch_readiness,
        mock_close_pool,
    ) -> None:
        conn = MagicMock()
        mock_create_pool.return_value = _FakePool(conn)
        mock_fetch_summary.return_value = {
            "plan_major_count": 1,
            "answer_ready_count": 0,
            "gap_count": 1,
            "missing_plan_count": 0,
            "missing_major_group_code": 0,
            "missing_major_code_raw": 0,
            "missing_selection_requirement": 0,
            "missing_admission_min_score": 0,
            "missing_admission_min_rank": 1,
            "missing_admission_linkage": 1,
            "missing_strength_evidence": 1,
        }
        mock_fetch_match_diagnostics.return_value = {
            "plan_major_count": 1,
            "plan_major_with_major_id_count": 1,
            "exact_major_id_match_count": 0,
            "exact_major_id_match_with_min_score_count": 0,
            "exact_major_id_match_with_min_rank_count": 0,
            "normalized_name_match_count": 1,
            "normalized_name_match_with_min_score_count": 1,
            "normalized_name_match_with_min_rank_count": 0,
            "normalized_name_only_match_count": 1,
            "normalized_name_only_match_with_min_score_count": 1,
            "normalized_name_only_match_with_min_rank_count": 0,
            "unmatched_plan_major_count": 0,
        }
        mock_fetch_strength_diagnostics.return_value = {
            "plan_major_count": 1,
            "plan_major_with_school_major_count": 1,
            "plan_major_with_strength_signal_count": 1,
            "plan_major_with_strength_rollup_count": 0,
            "plan_major_signal_without_rollup_count": 1,
        }
        mock_fetch_readiness.return_value = [
            {
                "school_name": "长春理工大学",
                "major_name": "光电信息科学与工程",
                "readiness_flags": ["missing_admission_linkage", "missing_admission_min_rank"],
                "plan_count": 92,
                "admission_match_type": "normalized_name",
                "latest_min_score": 552,
                "latest_min_score_year": 2025,
                "latest_min_rank": None,
                "latest_min_rank_year": None,
            }
        ]

        result = runner.invoke(
            app,
            [
                "audit-major-readiness",
                "--province",
                "吉林",
                "--plan-year",
                "2026",
                "--year",
                "2023",
                "--year",
                "2024",
                "--year",
                "2025",
                "--subject-category-id",
                "3",
                "--batch",
                "本科批",
            ],
        )

        assert result.exit_code == 0
        assert "Major answer readiness scope" in result.stdout
        assert "plan_major_count=1" in result.stdout
        assert "gap_count=1" in result.stdout
        assert "Major admission match diagnostics" in result.stdout
        assert "exact_major_id_match_count=0" in result.stdout
        assert "exact_major_id_match_with_min_score_count=0" in result.stdout
        assert "normalized_name_match_count=1" in result.stdout
        assert "normalized_name_match_with_min_score_count=1" in result.stdout
        assert "normalized_name_only_match_count=1" in result.stdout
        assert "normalized_name_only_match_with_min_score_count=1" in result.stdout
        assert "Major strength signal diagnostics" in result.stdout
        assert "plan_major_with_strength_signal_count=1" in result.stdout
        assert "plan_major_signal_without_rollup_count=1" in result.stdout
        assert "Major answer readiness gaps" in result.stdout
        assert "长春理工大学" in result.stdout
        assert "missing_admission_linkage,missing_admission_min_rank" in result.stdout
        assert "admission_match_type=normalized_name" in result.stdout
        assert "latest_min_score=552" in result.stdout
        assert "latest_min_score_year=2025" in result.stdout
        assert "latest_min_rank_year=None" in result.stdout
        mock_fetch_summary.assert_awaited_once_with(
            conn,
            province="吉林",
            plan_year=2026,
            admission_years=[2023, 2024, 2025],
            subject_category_id=3,
            batch="本科批",
        )
        mock_fetch_match_diagnostics.assert_awaited_once_with(
            conn,
            province="吉林",
            plan_year=2026,
            admission_years=[2023, 2024, 2025],
            subject_category_id=3,
            batch="本科批",
        )
        mock_fetch_strength_diagnostics.assert_awaited_once_with(
            conn,
            province="吉林",
            plan_year=2026,
            subject_category_id=3,
            batch="本科批",
        )
        mock_fetch_readiness.assert_awaited_once_with(
            conn,
            province="吉林",
            plan_year=2026,
            admission_years=[2023, 2024, 2025],
            subject_category_id=3,
            batch="本科批",
            limit=50,
        )
        mock_close_pool.assert_awaited_once()

    @patch("gaokao_vault.db.connection.close_pool", new_callable=AsyncMock)
    @patch("gaokao_vault.db.queries.data_quality.fetch_major_answer_readiness_gaps", new_callable=AsyncMock)
    @patch("gaokao_vault.db.queries.data_quality.fetch_major_strength_signal_diagnostics", new_callable=AsyncMock)
    @patch(
        "gaokao_vault.db.queries.data_quality.fetch_major_answer_readiness_match_diagnostics", new_callable=AsyncMock
    )
    @patch("gaokao_vault.db.queries.data_quality.fetch_major_answer_readiness_summary", new_callable=AsyncMock)
    @patch("gaokao_vault.db.connection.create_pool", new_callable=AsyncMock)
    def test_prints_no_matching_plan_scope_when_readiness_rows_are_empty(
        self,
        mock_create_pool,
        mock_fetch_summary,
        mock_fetch_match_diagnostics,
        mock_fetch_strength_diagnostics,
        mock_fetch_readiness,
        mock_close_pool,
    ) -> None:
        conn = MagicMock()
        mock_create_pool.return_value = _FakePool(conn)
        mock_fetch_summary.return_value = {
            "plan_major_count": 0,
            "answer_ready_count": 0,
            "gap_count": 0,
            "missing_plan_count": 0,
            "missing_major_group_code": 0,
            "missing_major_code_raw": 0,
            "missing_selection_requirement": 0,
            "missing_admission_min_score": 0,
            "missing_admission_min_rank": 0,
            "missing_admission_linkage": 0,
            "missing_strength_evidence": 0,
        }
        mock_fetch_match_diagnostics.return_value = {
            "plan_major_count": 0,
            "plan_major_with_major_id_count": 0,
            "exact_major_id_match_count": 0,
            "exact_major_id_match_with_min_score_count": 0,
            "exact_major_id_match_with_min_rank_count": 0,
            "normalized_name_match_count": 0,
            "normalized_name_match_with_min_score_count": 0,
            "normalized_name_match_with_min_rank_count": 0,
            "normalized_name_only_match_count": 0,
            "normalized_name_only_match_with_min_score_count": 0,
            "normalized_name_only_match_with_min_rank_count": 0,
            "unmatched_plan_major_count": 0,
        }
        mock_fetch_strength_diagnostics.return_value = {
            "plan_major_count": 0,
            "plan_major_with_school_major_count": 0,
            "plan_major_with_strength_signal_count": 0,
            "plan_major_with_strength_rollup_count": 0,
            "plan_major_signal_without_rollup_count": 0,
        }
        mock_fetch_readiness.return_value = []

        result = runner.invoke(
            app,
            [
                "audit-major-readiness",
                "--province",
                "吉林",
                "--plan-year",
                "2026",
                "--year",
                "2023",
                "--year",
                "2024",
                "--year",
                "2025",
                "--subject-category-id",
                "3",
                "--batch",
                "本科批",
            ],
        )

        assert result.exit_code == 0
        assert "plan_major_count=0" in result.stdout
        assert "No matching enrollment plans in requested scope." in result.stdout
        assert "Major admission match diagnostics" in result.stdout
        assert "Major strength signal diagnostics" in result.stdout
        assert "None in requested scope." in result.stdout
        mock_fetch_summary.assert_awaited_once()
        mock_fetch_match_diagnostics.assert_awaited_once()
        mock_fetch_strength_diagnostics.assert_awaited_once()
        mock_fetch_readiness.assert_awaited_once()
        mock_close_pool.assert_awaited_once()
