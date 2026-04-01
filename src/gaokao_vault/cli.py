from __future__ import annotations

import asyncio
import logging
from typing import Annotated

import typer

app = typer.Typer(name="gaokao-vault", help="阳光高考全量数据抓取系统")
logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


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
    _setup_logging(verbose)

    async def _run():
        from gaokao_vault.config import AppConfig
        from gaokao_vault.db.connection import close_pool, create_pool
        from gaokao_vault.scheduler.orchestrator import Orchestrator

        config = AppConfig()
        pool = await create_pool()
        try:
            orchestrator = Orchestrator(db_pool=pool, config=config.crawl, mode=mode)
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
    _setup_logging(verbose)

    async def _run():
        from gaokao_vault.config import AppConfig
        from gaokao_vault.db.connection import close_pool, create_pool
        from gaokao_vault.scheduler.orchestrator import Orchestrator

        config = AppConfig()
        pool = await create_pool()
        try:
            orchestrator = Orchestrator(db_pool=pool, config=config.crawl, mode=mode)
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


if __name__ == "__main__":
    app()
