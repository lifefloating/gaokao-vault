from __future__ import annotations

import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Annotated

import typer

app = typer.Typer(name="gaokao-vault", help="阳光高考全量数据抓取系统")
logger = logging.getLogger(__name__)

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _setup_logging(verbose: bool = False, log_dir: str | None = None) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    # stdout handler
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    # file handler
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "crawl.log"),
            maxBytes=50 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


@app.command()
def init_db(
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Initialize database: create tables and seed data."""
    _setup_logging(verbose)

    async def _run():
        from gaokao_vault.db.connection import close_pool, create_pool
        from gaokao_vault.db.migrate import run_migrations

        pool = await create_pool()
        try:
            await run_migrations(pool)
            typer.echo("Database initialized successfully.")
        finally:
            await close_pool()

    asyncio.run(_run())


@app.command()
def crawl(
    mode: Annotated[str, typer.Option("--mode", "-m", help="full or incremental")] = "full",
    types: Annotated[list[str] | None, typer.Option("--types", "-t", help="Specific task types")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Run crawl with three-phase orchestration."""
    if mode not in ("full", "incremental"):
        typer.echo(f"Invalid mode '{mode}'. Must be 'full' or 'incremental'.", err=True)
        raise typer.Exit(code=1)

    from gaokao_vault.config import CrawlConfig

    crawl_cfg = CrawlConfig()
    _setup_logging(verbose, log_dir=crawl_cfg.log_dir)

    async def _run():
        from gaokao_vault.config import AppConfig
        from gaokao_vault.db.connection import close_pool, create_pool
        from gaokao_vault.scheduler.orchestrator import Orchestrator

        config = AppConfig()
        pool = await create_pool()
        try:
            orchestrator = Orchestrator(
                db_pool=pool, config=config.crawl, mode=mode, db_config=config.db, app_config=config
            )
            if types:
                await orchestrator.run_types(types)
            else:
                await orchestrator.run_all()
        finally:
            await close_pool()

    asyncio.run(_run())


@app.command()
def run_spider(
    spider_name: Annotated[str, typer.Argument(help="Spider task type name")],
    mode: Annotated[str, typer.Option("--mode", "-m")] = "full",
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Run a single spider by task type name."""
    from gaokao_vault.config import CrawlConfig

    crawl_cfg = CrawlConfig()
    _setup_logging(verbose, log_dir=crawl_cfg.log_dir)

    async def _run():
        from gaokao_vault.config import AppConfig
        from gaokao_vault.db.connection import close_pool, create_pool
        from gaokao_vault.scheduler.orchestrator import Orchestrator

        config = AppConfig()
        pool = await create_pool()
        try:
            orchestrator = Orchestrator(
                db_pool=pool, config=config.crawl, mode=mode, db_config=config.db, app_config=config
            )
            stats = await orchestrator.run_single(spider_name)
            typer.echo(f"Spider {spider_name} finished: {stats}")
        finally:
            await close_pool()

    asyncio.run(_run())


@app.command()
def status(
    limit: Annotated[int, typer.Option("--limit", "-n")] = 20,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Show recent crawl task status."""
    _setup_logging(verbose)

    async def _run():
        from gaokao_vault.db.connection import close_pool, create_pool
        from gaokao_vault.scheduler.task_manager import TaskManager

        pool = await create_pool()
        try:
            manager = TaskManager(pool)
            tasks = await manager.list_recent_tasks(limit)
            if not tasks:
                typer.echo("No crawl tasks found.")
                return
            for t in tasks:
                typer.echo(
                    f"[{t['id']}] {t['task_type']:20s} {t['status']:10s} "
                    f"total={t.get('total_items', 0)} new={t.get('new_items', 0)} "
                    f"updated={t.get('updated_items', 0)} unchanged={t.get('unchanged_items', 0)} "
                    f"failed={t.get('failed_items', 0)}"
                )
        finally:
            await close_pool()

    asyncio.run(_run())


@app.command()
def healthcheck() -> None:
    """Check OpenAI API connectivity."""
    from gaokao_vault.config import OpenAIConfig
    from gaokao_vault.health import check_openai_health

    config = OpenAIConfig()
    result = asyncio.run(check_openai_health(config))

    if result.ok:
        typer.echo(result.message)
        raise typer.Exit(code=0)
    else:
        typer.echo(result.message, err=True)
        raise typer.Exit(code=1)


@app.command()
def audit_completeness(
    province: Annotated[str, typer.Option("--province", "-p", help="Province code or name")] = "吉林",
    years: Annotated[list[int] | None, typer.Option("--year", "-y", help="Admission years to audit")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum missing school-year rows to print")] = 50,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Audit recent three-year admission-result and enrollment-plan coverage."""
    _setup_logging(verbose)

    from gaokao_vault.db.queries.data_quality import normalize_completeness_years

    audit_years = normalize_completeness_years(years)

    async def _run():
        from gaokao_vault.db.connection import close_pool, create_pool
        from gaokao_vault.db.queries.data_quality import fetch_school_year_plan_gaps, fetch_year_data_coverage

        pool = await create_pool()
        try:
            async with pool.acquire() as conn:
                coverage_rows = await fetch_year_data_coverage(conn, province=province, years=audit_years)
                gap_rows = await fetch_school_year_plan_gaps(conn, province=province, years=audit_years, limit=limit)
        finally:
            await close_pool()

        _print_completeness_coverage(coverage_rows)
        _print_completeness_gaps(gap_rows)

    asyncio.run(_run())


def _print_completeness_coverage(rows: list[dict]) -> None:
    typer.echo("Coverage by year")
    if not rows:
        typer.echo("  No rows. Check province code/name and source tables.")
        return

    for row in rows:
        typer.echo(
            "  "
            f"{row['year']} {row['province_name']}: "
            f"admission_schools={row.get('admission_schools', 0)} "
            f"admission_records={row.get('admission_records', 0)} "
            f"admission_records_with_plan_count={row.get('admission_records_with_plan_count', 0)} "
            f"admission_records_with_major_group_code={row.get('admission_records_with_major_group_code', 0)} "
            f"plan_schools={row.get('plan_schools', 0)} "
            f"plan_records={row.get('plan_records', 0)} "
            f"plan_records_with_plan_count={row.get('plan_records_with_plan_count', 0)} "
            f"plan_records_with_major_group_code={row.get('plan_records_with_major_group_code', 0)} "
            f"plan_records_with_selection_requirement={row.get('plan_records_with_selection_requirement', 0)} "
            f"plan_count_sum={row.get('plan_count_sum', 0)} "
            f"missing_plan_schools={row.get('missing_plan_schools', 0)}"
        )


def _print_completeness_gaps(rows: list[dict]) -> None:
    typer.echo("Missing enrollment plans")
    if not rows:
        typer.echo("  None in requested window.")
        return

    for row in rows:
        typer.echo(
            "  "
            f"{row['year']} {row['school_name']} "
            f"(school_id={row['school_id']}): "
            f"admission_records={row.get('admission_records', 0)} "
            f"admission_records_with_plan_count={row.get('admission_records_with_plan_count', 0)} "
            f"plan_records={row.get('plan_records', 0)} "
            f"plan_count_sum={row.get('plan_count_sum', 0)}"
        )


@app.command()
def audit_major_readiness(
    province: Annotated[str, typer.Option("--province", "-p", help="Province code or name")] = "吉林",
    plan_year: Annotated[int, typer.Option("--plan-year", help="Enrollment plan year to audit")] = 2026,
    years: Annotated[list[int] | None, typer.Option("--year", "-y", help="Admission years to require")] = None,
    subject_category_id: Annotated[int | None, typer.Option("--subject-category-id")] = None,
    batch: Annotated[str | None, typer.Option("--batch", help="Batch name/category to audit")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum major gaps to print")] = 50,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Audit whether major-level answers have scores, plans, selection requirements, and strength evidence."""
    _setup_logging(verbose)

    from gaokao_vault.db.queries.data_quality import normalize_completeness_years

    admission_years = normalize_completeness_years(years)

    async def _run():
        from gaokao_vault.db.connection import close_pool, create_pool
        from gaokao_vault.db.queries.data_quality import (
            fetch_major_answer_readiness_gaps,
            fetch_major_answer_readiness_match_diagnostics,
            fetch_major_answer_readiness_summary,
            fetch_major_strength_signal_diagnostics,
        )

        pool = await create_pool()
        try:
            async with pool.acquire() as conn:
                summary = await fetch_major_answer_readiness_summary(
                    conn,
                    province=province,
                    plan_year=plan_year,
                    admission_years=admission_years,
                    subject_category_id=subject_category_id,
                    batch=batch,
                )
                match_diagnostics = await fetch_major_answer_readiness_match_diagnostics(
                    conn,
                    province=province,
                    plan_year=plan_year,
                    admission_years=admission_years,
                    subject_category_id=subject_category_id,
                    batch=batch,
                )
                strength_diagnostics = await fetch_major_strength_signal_diagnostics(
                    conn,
                    province=province,
                    plan_year=plan_year,
                    subject_category_id=subject_category_id,
                    batch=batch,
                )
                rows = await fetch_major_answer_readiness_gaps(
                    conn,
                    province=province,
                    plan_year=plan_year,
                    admission_years=admission_years,
                    subject_category_id=subject_category_id,
                    batch=batch,
                    limit=limit,
                )
        finally:
            await close_pool()

        _print_major_readiness_summary(
            summary,
            province=province,
            plan_year=plan_year,
            admission_years=admission_years,
            subject_category_id=subject_category_id,
            batch=batch,
        )
        _print_major_readiness_match_diagnostics(match_diagnostics)
        _print_major_strength_signal_diagnostics(strength_diagnostics)
        _print_major_readiness_gaps(rows, summary)

    asyncio.run(_run())


def _print_major_readiness_summary(
    summary: dict[str, object],
    *,
    province: str,
    plan_year: int,
    admission_years: list[int],
    subject_category_id: int | None,
    batch: str | None,
) -> None:
    typer.echo("Major answer readiness scope")
    typer.echo(
        "  "
        f"province={province} "
        f"plan_year={plan_year} "
        f"admission_years={','.join(str(year) for year in admission_years)} "
        f"subject_category_id={subject_category_id} "
        f"batch={batch}"
    )
    typer.echo(
        "  "
        f"plan_major_count={summary.get('plan_major_count', 0)} "
        f"answer_ready_count={summary.get('answer_ready_count', 0)} "
        f"gap_count={summary.get('gap_count', 0)} "
        f"missing_plan_count={summary.get('missing_plan_count', 0)} "
        f"missing_major_group_code={summary.get('missing_major_group_code', 0)} "
        f"missing_major_code_raw={summary.get('missing_major_code_raw', 0)} "
        f"missing_selection_requirement={summary.get('missing_selection_requirement', 0)} "
        f"missing_admission_min_score={summary.get('missing_admission_min_score', 0)} "
        f"missing_admission_min_rank={summary.get('missing_admission_min_rank', 0)} "
        f"missing_admission_linkage={summary.get('missing_admission_linkage', 0)} "
        f"missing_strength_evidence={summary.get('missing_strength_evidence', 0)}"
    )
    if summary.get("plan_major_count", 0) == 0:
        typer.echo("  No matching enrollment plans in requested scope. Check province/year/subject/batch.")


def _print_major_readiness_match_diagnostics(diagnostics: dict[str, object]) -> None:
    typer.echo("Major admission match diagnostics")
    typer.echo(
        "  "
        f"plan_major_count={diagnostics.get('plan_major_count', 0)} "
        f"plan_major_with_major_id_count={diagnostics.get('plan_major_with_major_id_count', 0)} "
        f"exact_major_id_match_count={diagnostics.get('exact_major_id_match_count', 0)} "
        f"exact_major_id_match_with_min_score_count={diagnostics.get('exact_major_id_match_with_min_score_count', 0)} "
        f"exact_major_id_match_with_min_rank_count={diagnostics.get('exact_major_id_match_with_min_rank_count', 0)} "
        f"normalized_name_match_count={diagnostics.get('normalized_name_match_count', 0)} "
        f"normalized_name_match_with_min_score_count={diagnostics.get('normalized_name_match_with_min_score_count', 0)} "
        f"normalized_name_match_with_min_rank_count={diagnostics.get('normalized_name_match_with_min_rank_count', 0)} "
        f"normalized_name_only_match_count={diagnostics.get('normalized_name_only_match_count', 0)} "
        "normalized_name_only_match_with_min_score_count="
        f"{diagnostics.get('normalized_name_only_match_with_min_score_count', 0)} "
        "normalized_name_only_match_with_min_rank_count="
        f"{diagnostics.get('normalized_name_only_match_with_min_rank_count', 0)} "
        f"unmatched_plan_major_count={diagnostics.get('unmatched_plan_major_count', 0)}"
    )


def _print_major_strength_signal_diagnostics(diagnostics: dict[str, object]) -> None:
    typer.echo("Major strength signal diagnostics")
    typer.echo(
        "  "
        f"plan_major_count={diagnostics.get('plan_major_count', 0)} "
        f"plan_major_with_school_major_count={diagnostics.get('plan_major_with_school_major_count', 0)} "
        f"plan_major_with_strength_signal_count={diagnostics.get('plan_major_with_strength_signal_count', 0)} "
        f"plan_major_with_strength_rollup_count={diagnostics.get('plan_major_with_strength_rollup_count', 0)} "
        f"plan_major_signal_without_rollup_count={diagnostics.get('plan_major_signal_without_rollup_count', 0)}"
    )


def _print_major_readiness_gaps(rows: list[dict], summary: dict[str, object]) -> None:
    typer.echo("Major answer readiness gaps")
    if not rows:
        if summary.get("plan_major_count", 0) == 0:
            typer.echo("  None in requested scope.")
        else:
            typer.echo("  None in requested scope; all matched plan rows are answer-ready.")
        return

    for row in rows:
        flags = ",".join(row.get("readiness_flags") or [])
        typer.echo(
            "  "
            f"{row.get('school_name')} {row.get('major_name')}: "
            f"flags={flags} "
            f"plan_count={row.get('plan_count')} "
            f"admission_match_type={row.get('admission_match_type')} "
            f"latest_min_score_year={row.get('latest_min_score_year')} "
            f"latest_min_score={row.get('latest_min_score')} "
            f"latest_min_rank_year={row.get('latest_min_rank_year')} "
            f"latest_min_rank={row.get('latest_min_rank')}"
        )


@app.command()
def schedule(
    mode: Annotated[str | None, typer.Option("--mode", "-m", help="full or incremental")] = None,
    types: Annotated[list[str] | None, typer.Option("--types", "-t", help="Specific task types")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Run the cron scheduler."""
    if mode is not None and mode not in ("full", "incremental"):
        typer.echo(f"Invalid mode '{mode}'. Must be 'full' or 'incremental'.", err=True)
        raise typer.Exit(code=1)

    from gaokao_vault.config import AppConfig

    config = AppConfig()
    _setup_logging(verbose, log_dir=config.crawl.log_dir)

    async def _run():
        from gaokao_vault.scheduler.cron_runner import IncrementalCronScheduler

        scheduler = IncrementalCronScheduler(config, mode=mode, types=types)
        await scheduler.run_forever()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
