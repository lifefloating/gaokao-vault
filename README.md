# gaokao-vault

[![Build status](https://img.shields.io/github/actions/workflow/status/lifefloating/gaokao-vault/main.yml?branch=main)](https://github.com/lifefloating/gaokao-vault/actions/workflows/main.yml?query=branch%3Amain)
[![License](https://img.shields.io/github/license/lifefloating/gaokao-vault)](https://github.com/lifefloating/gaokao-vault/blob/main/LICENSE)

阳光高考全量数据抓取系统 — 从 [gaokao.chsi.com.cn](https://gaokao.chsi.com.cn) 抓取 13 类高考数据（院校、专业、分数线、招生计划等），存入 PostgreSQL，支持全量/增量抓取、断点续爬、反爬对抗。

- **仓库**: <https://github.com/lifefloating/gaokao-vault>
- **文档**: <https://lifefloating.github.io/gaokao-vault/>

## 功能概览

- 13 类数据源全量覆盖（院校、专业、分数线、一分一段、招生计划、章程等）
- 三阶段任务编排，自动处理数据依赖
- content_hash (SHA-256) 增量去重 + 变更追踪
- 双 Session 反爬：HTTP 快速请求 + Stealth 浏览器自动切换
- 三层代理池：付费代理 > 免费代理 > 直连
- 断点续爬（Ctrl+C 优雅暂停，再次启动自动恢复）
- Typer CLI，操作简单

## 快速开始

### 环境要求

- Python 3.10+
- PostgreSQL 14+
- [uv](https://docs.astral.sh/uv/) 包管理器

### 安装

```bash
git clone https://github.com/lifefloating/gaokao-vault.git
cd gaokao-vault

# 安装依赖
uv sync

# 安装 Scrapling 浏览器依赖（Stealth 模式需要）
uv run scrapling install --force
```

### 配置

复制并编辑环境变量：

```bash
cp .env.example .env
```

核心配置项（通过环境变量或 `.env` 文件）：

```bash
# 数据库连接
GAOKAO_DB__DSN=postgresql://user:pass@localhost:5432/gaokao_vault
GAOKAO_DB__POOL_MIN=5
GAOKAO_DB__POOL_MAX=20

# 代理配置（可选）
GAOKAO_PROXY__STATIC_PROXIES=["http://user:pass@proxy1:8080"]
GAOKAO_PROXY__USE_FREEPROXY=true

# 爬取参数
GAOKAO_CRAWL__CONCURRENCY=5
GAOKAO_CRAWL__BASE_DELAY=1.0
GAOKAO_CRAWL__JITTER_RATIO=0.5
```

### 初始化数据库

```bash
gaokao-vault init-db
```

这会创建 18 张表并导入省份、科类种子数据。

### 运行爬虫

```bash
# 全量抓取（三阶段自动编排）
gaokao-vault crawl --mode full

# 增量抓取（仅更新有变化的数据）
gaokao-vault crawl --mode incremental

# 指定数据类型
gaokao-vault crawl --types schools majors score_lines

# 单独运行某个 Spider（调试用）
gaokao-vault run-spider schools
gaokao-vault run-spider score_segments

# 查看任务状态
gaokao-vault status
gaokao-vault status --limit 50
```

### 断点续爬

爬取过程中按 `Ctrl+C` 优雅暂停，进度自动保存。再次运行相同命令即可从断点恢复。

### 详细日志

所有命令支持 `-v` 参数输出 DEBUG 级别日志：

```bash
gaokao-vault crawl --mode full -v
```

## Docker

```bash
# 构建镜像
docker build -t gaokao-vault .

# 初始化数据库
docker run --rm --env-file .env gaokao-vault init-db

# 全量抓取
docker run --rm --env-file .env gaokao-vault crawl --mode full

# 查看状态
docker run --rm --env-file .env gaokao-vault status
```

## 三阶段编排

| 阶段 | 数据 | 说明 |
|------|------|------|
| 1 维度数据 | provinces, subject_categories | 由 `init-db` 种子数据完成 |
| 2 核心实体 | schools, majors, score_lines, timelines, announcements | 并行抓取 |
| 3 关联数据 | school_majors, score_segments, enrollment_plans, charters, special, *_satisfaction, interpretations | 依赖阶段2，并行抓取 |

## 数据类型一览

| 类型 | 说明 | 预估数据量 |
|------|------|-----------|
| schools | 院校信息 | ~2,900 |
| majors | 专业知识库 | ~3,000 |
| school_majors | 院校-专业关联 | ~100,000 |
| score_lines | 历年批次线 | ~数万 |
| score_segments | 一分一段表 | ~百万 |
| enrollment_plans | 招生计划 | ~百万 |
| charters | 招生章程 | ~数万 |
| timelines | 志愿填报时间线 | ~数百 |
| special | 特殊类型招生 | ~数千 |
| school_satisfaction | 院校满意度 | ~数千 |
| major_satisfaction | 专业满意度 | ~数千 |
| interpretations | 专业解读 | ~数千 |
| announcements | 省级招办公告 | ~数千 |

## 技术栈

- [Scrapling](https://github.com/D4Vinci/Scrapling) — 爬虫框架（Spider + FetcherSession + AsyncStealthySession）
- [asyncpg](https://github.com/MagicStack/asyncpg) — PostgreSQL 异步驱动
- [Typer](https://typer.tiangolo.com/) — CLI 框架
- [Pydantic](https://docs.pydantic.dev/) — 数据校验 + 配置管理

## 开发

```bash
# 安装开发依赖
uv sync --group dev

# 运行测试
uv run pytest tests/ -v

# 代码检查
uv run ruff check src/
uv run ruff format src/

# pre-commit hooks
uv run pre-commit run -a
```

## License

[MIT](LICENSE)
