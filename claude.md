# Claude Code Instructions

## 项目概述

gaokao-vault — 阳光高考全量数据抓取系统，从 gaokao.chsi.com.cn 抓取 13 类高考数据，存入 PostgreSQL。

## 技术栈

- Python 3.10+，包管理用 **uv**
- Web 抓取：scrapling（Spider 框架 + AsyncStealthySession）
- 数据库：PostgreSQL + asyncpg
- CLI：Typer
- 数据校验：Pydantic / Pydantic Settings
- 测试：pytest + hypothesis
- Lint/Format：ruff（line-length=120）
- 类型检查：ty
- 文档：mkdocs-material

## 常用命令

```bash
uv sync                          # 安装依赖
uv run pre-commit install        # 安装 pre-commit hooks
make check                       # lint + type check + deptry
make test                        # pytest with coverage
make docs                        # 本地文档服务
```

## 代码规范

- 所有模块使用 `from __future__ import annotations`
- Ruff 规则集：YTT, S, B, A, C4, T10, SIM, I, C90, E, W, F, PGH, UP, RUF, TRY
- 测试文件允许 `assert`（`S101` 已豁免）
- 配置通过 pydantic-settings 管理，环境变量前缀 `GAOKAO_DB__`、`GAOKAO_CRAWL__`、`GAOKAO_PROXY__`

## 项目结构

- `src/gaokao_vault/spiders/` — 各类数据 Spider，继承 `BaseGaokaoSpider`（基于 scrapling Spider）
- `src/gaokao_vault/pipeline/` — 数据处理：去重(content_hash SHA-256)、校验、入库
- `src/gaokao_vault/anti_detect/` — 反爬对抗：代理池、UA 池、限速器
- `src/gaokao_vault/db/` — 数据库连接、迁移、SQL 查询
- `src/gaokao_vault/scheduler/` — 三阶段任务编排
- `src/gaokao_vault/models/` — Pydantic 数据模型
- `src/gaokao_vault/storage/` — S3/MinIO 存储
- `src/gaokao_vault/vision/` — OpenAI 视觉分析
- `tests/` — 测试目录

## 注意事项

- Spider 新增需继承 `BaseGaokaoSpider`，设置 `name`、`task_type`、`start_urls`
- 数据库 Schema 定义在 `src/gaokao_vault/db/schema.sql`
- Docker Compose 支持一键启动（`docker compose up -d db`）
