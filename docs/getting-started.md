# 快速开始

## 环境要求

- Python 3.10+
- PostgreSQL 18+
- [uv](https://docs.astral.sh/uv/) 包管理器

## 方式一：Docker Compose（推荐）

最简单的方式，一键启动 PostgreSQL + 爬虫：

```bash
git clone https://github.com/lifefloating/gaokao-vault.git
cd gaokao-vault

# 启动 PostgreSQL
docker compose up -d db

# 初始化数据库（建表 + 种子数据）
docker compose run --rm crawler init-db

# 全量抓取
docker compose run --rm crawler crawl --mode full

# 查看任务状态
docker compose run --rm crawler status
```

数据持久化在 Docker volume 中，`docker compose down` 不会丢数据。彻底清理用 `docker compose down -v`。

## 方式二：本地安装

### 安装依赖

```bash
git clone https://github.com/lifefloating/gaokao-vault.git
cd gaokao-vault

uv sync
uv run scrapling install --force
```

### 配置

```bash
cp .env.example .env
# 编辑 .env，填入你的 PostgreSQL 连接信息
```

核心配置项：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `GAOKAO_DB__DSN` | PostgreSQL 连接串 | `postgresql://gaokao:gaokao@localhost:5432/gaokao_vault` |
| `GAOKAO_DB__POOL_MIN` | 连接池最小连接数 | `5` |
| `GAOKAO_DB__POOL_MAX` | 连接池最大连接数 | `20` |
| `GAOKAO_PROXY__STATIC_PROXIES` | 付费代理列表 (JSON) | `[]` |
| `GAOKAO_PROXY__USE_FREEPROXY` | 是否启用免费代理 | `false` |
| `GAOKAO_CRAWL__CONCURRENCY` | 并发请求数 | `5` |
| `GAOKAO_CRAWL__BASE_DELAY` | 请求基础延迟(秒) | `1.0` |

### 初始化数据库

确保 PostgreSQL 已运行并创建了 `gaokao_vault` 数据库：

```bash
createdb gaokao_vault  # 或通过 psql 创建
gaokao-vault init-db
```

### 运行爬虫

```bash
# 全量抓取
gaokao-vault crawl --mode full

# 增量抓取
gaokao-vault crawl --mode incremental

# 指定类型
gaokao-vault crawl --types schools majors score_lines

# 单独调试
gaokao-vault run-spider schools -v
```

## 方式三：DevContainer

项目包含 `.devcontainer` 配置，在 VS Code / Kiro 中打开项目后选择 "Reopen in Container"，会自动：

1. 启动 Python 3.12 + PostgreSQL 18 环境
2. 安装所有依赖和 Scrapling 浏览器
3. 创建 `gaokao_vault` 数据库

之后直接运行 `gaokao-vault init-db` 即可开始。

## 断点续爬

爬取过程中按 `Ctrl+C` 优雅暂停，进度自动保存到 `crawl_data/` 目录。再次运行相同命令即可从断点恢复。

按两次 `Ctrl+C` 强制停止（不保存断点）。
