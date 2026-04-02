# 架构设计

## 系统架构

```
CLI (Typer)
  └─ Orchestrator (三阶段编排)
       └─ TaskManager (crawl_tasks 生命周期)
            └─ Spider × 13 (继承 BaseGaokaoSpider)
                 ├─ AntiDetect (代理池 / UA / 限速)
                 ├─ Pipeline (hash → 去重 → 校验 → 入库)
                 └─ DB Layer (asyncpg 连接池 + 查询层)
```

## 三阶段编排

| 阶段 | 数据 | 依赖 |
|------|------|------|
| 1 维度数据 | provinces, subject_categories, major_categories, major_subcategories | seed SQL（init-db 完成） |
| 2 核心实体 | schools, majors, score_lines, timelines, announcements | 维度表 |

score_lines 使用全页截图 + OpenAI Vision API 分析模式（详见 VisionAnalyzer）。
| 3 关联+批量 | school_majors, score_segments, enrollment_plans, charters, special, *_satisfaction, interpretations | schools / majors |

每阶段内的 Spider 并行执行，阶段间串行保证依赖。

## 模块结构

```
src/gaokao_vault/
├── cli.py                  # Typer CLI 入口
├── config.py               # Pydantic Settings 配置 (DB/Proxy/Crawl/OpenAI)
├── constants.py            # BASE_URL, TaskType 枚举
├── db/
│   ├── connection.py       # asyncpg 连接池
│   ├── migrate.py          # schema 初始化 + seed
│   ├── schema.sql          # 18 张表 DDL
│   ├── seed_*.sql          # 种子数据
│   └── queries/            # 各表 CRUD
├── anti_detect/
│   ├── proxy_pool.py       # 三层代理池
│   ├── ua_pool.py          # UA + impersonate
│   └── rate_limiter.py     # 随机延迟
├── pipeline/
│   ├── hasher.py           # SHA-256 content_hash
│   ├── dedup.py            # new/updated/unchanged 去重
│   ├── validator.py        # Pydantic 校验
│   └── sink.py             # BatchSink 批量入库
├── vision/
│   ├── analyzer.py         # VisionAnalyzer (OpenAI Vision API)
│   └── prompts/            # AI 提取指令模板
├── models/                 # Pydantic 数据模型
├── spiders/
│   ├── base.py             # BaseGaokaoSpider 基类
│   └── *_spider.py         # 13 个 Spider 实现
└── scheduler/
    ├── orchestrator.py     # 三阶段编排
    └── task_manager.py     # crawl_tasks 生命周期
```

## Spider 基类

所有 Spider 继承 `BaseGaokaoSpider`，提供：

- 双 Session 配置：`http`（FetcherSession，快速）+ `stealth`（AsyncStealthySession，反反爬，lazy 启动）
- 自定义 `is_blocked()` 检测阳光高考网反爬特征
- 被封自动切换到 stealth session（`retry_blocked_request()`）
- 统一 `process_item()` 管道：校验 → hash → 去重 → 入库
- `on_close()` 自动更新 crawl_tasks 统计
- `allowed_domains` 限制爬取范围

## 增量去重

基于 `content_hash` (SHA-256) 的三态去重：

```
抓取数据 → compute_content_hash → 查业务表当前 hash
  ├─ 无记录 → INSERT 业务表 + snapshot(new)
  ├─ hash 相同 → snapshot(unchanged)
  └─ hash 不同 → UPDATE 业务表 + snapshot(updated, 保存旧数据)
```

`crawl_snapshots` 表记录完整变更历史，支持数据回溯。

## 反爬策略

| 层级 | 机制 |
|------|------|
| TLS 指纹 | Scrapling impersonate（chrome/firefox/safari/edge 随机） |
| 代理 | 三层：付费代理 > pyfreeproxy 免费代理 > 直连 |
| 封禁检测 | 自定义 `is_blocked()` 检测 403/429/验证码等 |
| 封禁恢复 | 自动切换到 stealth 浏览器 session 重试 |
| 请求延迟 | Scrapling `download_delay` + 并发限制 |

## 数据库

18 张表，分四层：

- 抓取元数据层：`crawl_tasks`, `crawl_snapshots`
- 维度层：`provinces`, `subject_categories`
- 业务数据层：13 张表（schools, majors, score_lines 等）
- 扩展层：`special_enrollments`, `provincial_announcements`
