# CLI 参考

所有命令通过 `gaokao-vault` 入口调用，支持 `-v` / `--verbose` 输出 DEBUG 日志。

## init-db

初始化数据库：创建 18 张表 + 导入省份、科类种子数据。

```bash
gaokao-vault init-db
gaokao-vault init-db -v  # 详细日志
```

!!! note
    重复执行是安全的，使用 `CREATE TABLE IF NOT EXISTS` 和 `INSERT ... ON CONFLICT DO NOTHING`。

## crawl

三阶段编排抓取。

```bash
# 全量抓取
gaokao-vault crawl --mode full

# 增量抓取（通过 content_hash 跳过未变数据）
gaokao-vault crawl --mode incremental

# 指定数据类型（跳过其他类型）
gaokao-vault crawl --types schools majors score_lines

# 组合使用
gaokao-vault crawl --mode incremental --types schools -v
```

| 参数 | 缩写 | 说明 | 默认值 |
|------|------|------|--------|
| `--mode` | `-m` | `full` 或 `incremental` | `full` |
| `--types` | `-t` | 指定 task type，可多次使用 | 全部 |
| `--verbose` | `-v` | DEBUG 日志 | 关闭 |

可用的 task type：

`schools`, `majors`, `score_lines`, `score_segments`, `enrollment_plans`,
`charters`, `timelines`, `special`, `school_majors`, `school_satisfaction`,
`major_satisfaction`, `interpretations`, `announcements`

## run-spider

单独运行一个 Spider，适合调试。

```bash
gaokao-vault run-spider schools
gaokao-vault run-spider score_segments --mode incremental -v
```

| 参数 | 说明 |
|------|------|
| `spider_name` | task type 名称（必填） |
| `--mode` / `-m` | `full` 或 `incremental` |

## status

查看最近的抓取任务状态。

```bash
gaokao-vault status
gaokao-vault status --limit 50
```

输出示例：

```
[42] schools              success    total=2876 new=2876 updated=0 unchanged=0 failed=3
[41] majors               success    total=2980 new=2980 updated=0 unchanged=0 failed=0
[40] score_lines          running    total=0 new=0 updated=0 unchanged=0 failed=0
```

## Docker Compose 用法

```bash
docker compose up -d db
docker compose run --rm crawler init-db
docker compose run --rm crawler crawl --mode full
docker compose run --rm crawler status
```
