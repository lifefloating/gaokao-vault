# Agents Instructions

## Project Overview

gaokao-vault — 阳光高考全量数据抓取系统，从 gaokao.chsi.com.cn 抓取 13 类高考数据，存入 PostgreSQL。

## Tech Stack

- Python 3.10+, package manager: **uv**
- Web scraping: scrapling (Spider framework + AsyncStealthySession)
- Database: PostgreSQL + asyncpg
- CLI: Typer
- Validation: Pydantic / Pydantic Settings
- Testing: pytest + hypothesis
- Lint/Format: ruff (line-length=120)
- Type check: ty
- Docs: mkdocs-material

## Common Commands

```bash
uv sync                          # install dependencies
uv run pre-commit install        # install pre-commit hooks
make check                       # lint + type check + deptry
make test                        # pytest with coverage
make docs                        # local docs server
```

## Code Conventions

- All modules must use `from __future__ import annotations`
- Ruff rule sets: YTT, S, B, A, C4, T10, SIM, I, C90, E, W, F, PGH, UP, RUF, TRY
- `assert` is allowed in test files (`S101` exempted)
- Config managed via pydantic-settings, env prefix: `GAOKAO_DB__`, `GAOKAO_CRAWL__`, `GAOKAO_PROXY__`

## Project Structure

- `src/gaokao_vault/spiders/` — Data spiders, inherit `BaseGaokaoSpider` (scrapling Spider)
- `src/gaokao_vault/pipeline/` — Data processing: dedup (content_hash SHA-256), validation, DB insert
- `src/gaokao_vault/anti_detect/` — Anti-detection: proxy pool, UA pool, rate limiter
- `src/gaokao_vault/db/` — DB connection, migrations, SQL queries
- `src/gaokao_vault/scheduler/` — Three-phase task orchestration
- `src/gaokao_vault/models/` — Pydantic data models
- `src/gaokao_vault/storage/` — S3/MinIO storage
- `src/gaokao_vault/vision/` — OpenAI vision analysis
- `tests/` — Test directory

## Spider Development

- New spiders must inherit `BaseGaokaoSpider` with `name`, `task_type`, `start_urls`
- Existing spiders (13 types):
  - `school_spider` — 院校信息
  - `major_spider` — 专业信息
  - `score_line_spider` — 分数线
  - `score_segment_spider` — 一分一段表
  - `enrollment_plan_spider` — 招生计划
  - `school_major_spider` — 院校专业
  - `special_spider` — 特殊类招生
  - `charter_spider` — 招生章程
  - `announcement_spider` — 公告
  - `interpretation_spider` — 政策解读
  - `timeline_spider` — 时间线
  - `school_satisfaction_spider` — 院校满意度
  - `major_satisfaction_spider` — 专业满意度

## Database

- Schema defined in `src/gaokao_vault/db/schema.sql`
- Docker Compose for local dev: `docker compose up -d db`

## Key Rules

- Run `make check` before committing to ensure lint and type checks pass
- Run `make test` to verify no regressions
- Keep Chinese comments/docstrings where domain context requires it
