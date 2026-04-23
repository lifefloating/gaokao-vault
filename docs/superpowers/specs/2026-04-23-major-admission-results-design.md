# 学校专业录取结果事实表与查询补数设计

## 背景

当前仓库已经能够抓取并入库：

- `schools`：学校基础信息
- `majors`：专业维表
- `school_majors`：学校-专业关联
- `admission_score_lines`：省份批次线
- `enrollment_plans`：学校-省份-年份招生计划
- `major_satisfaction` / `school_satisfaction`：满意度数据

但当用户提出“吉林 400 分能报考哪些江苏苏州学校和专业”这类问题时，现有数据仍然不够：

1. `admission_score_lines` 只有省控线，不是学校/专业实际录取分。
2. `enrollment_plans` 是计划数据，不是录取结果，不能直接用于“400 分能不能报”。
3. `school_majors` 只能说明学校开设过哪些专业，不能说明这些专业在吉林的历年录取门槛。
4. “输入学校后看热门专业”也缺少可同时覆盖“满意度”和“招生/录取热度”的底层事实。

用户本次要求是：先把底层数据补齐到可筛选的程度，至于问答接口和后端如何查，由后端自己决定。

## 目标与非目标

### 目标

- 新增一张“学校-专业-省份-年份”录取事实表，承载能用于真实筛选的核心录取数据。
- 让底层数据能支持后端按如下条件筛选：
  - `province = 吉林`
  - `score = 400`
  - 学校位置约束（如江苏苏州）
  - 学校-专业粒度结果
- 为“学校热门专业”提供两类原始依据：
  - `A`：满意度数据
  - `B`：招生/录取热度数据
- 保持现有抓取系统的增量、去重、快照、三阶段编排模式。

### 非目标

- 不在本次实现中构建问答接口、检索 API 或排序服务。
- 不在底层提前固化唯一的“热门专业分值”或唯一排序规则。
- 不在本地执行真实网站抓取或真实入库验证。
- 不修改现有 `enrollment_plans` 的业务含义；计划和录取结果保持分表。

## 设计概览

整体采用“新增录取事实任务 + 保留现有计划表”的方式：

- 新增任务类型：`major_admission_results`
- 新增事实表：`major_admission_results`
- 新 spider 专门抓取“学校-专业-省份-年份”的录取结果，不把这类数据混入 `enrollment_plans`
- 新任务放在现有 Phase 3 中执行，但启动前要求 `schools` 和 `majors` 已经稳定完成
- 该 spider 在抓取录取结果时自行解析 `major_id`，不要求 `school_majors` 先完成，因此无需引入新的 Phase 4

## 数据模型设计

新增事实表建议字段如下：

- `id`
- `school_id`
- `major_id`
- `province_id`
- `year`
- `subject_category_id`
- `batch`
- `min_score`
- `min_rank`
- `avg_score`
- `avg_rank`
- `max_score`
- `max_rank`
- `admitted_count`
- `major_name_raw`
- `subject_category_raw`
- `batch_raw`
- `remark`
- `source_url`
- `content_hash`
- `crawl_task_id`
- `created_at`
- `updated_at`

### 字段语义

- `school_id` / `major_id`：统一引用现有学校与专业主键，保证后端可以直接联查。
- `province_id`：表示招生省份，例如吉林。
- `subject_category_id`：尽量映射到现有 `subject_categories`，用于区分物理类/历史类/文理科等。
- `batch`：结构化批次名，用于筛选；同时保留 `batch_raw` 以便追溯原站口径。
- `min_score` / `min_rank`：后端按“400 分能否报考”时的核心筛选依据。
- `avg_*` / `max_*`：为后端做风险分层和展示留出空间。
- `admitted_count`：作为“热度”原始指标之一。
- `remark`：保留专业备注、实验班、中外合作等附加信息。

### 唯一键与更新策略

唯一键建议为：

- `school_id`
- `major_id`
- `province_id`
- `year`
- `subject_category_id`
- `batch`

这可以保证同一学校、同一专业、同一省份、同一年、同一科类、同一批次只有一条录取事实。后续官网数据变化时，继续沿用现有 `content_hash + snapshot` 增量更新模式。

## 抓取任务设计

### 任务类型

新增 `TaskType.MAJOR_ADMISSION_RESULTS = "major_admission_results"`。

### 编排位置

将该任务加入现有 Phase 3，而不是新增 Phase 4。

原因：

- 它依赖 `schools` 和 `majors` 两张核心表，但不依赖 `school_majors` 先完整生成。
- 只要抓取时能够稳定把录取页中的专业标识解析成 `major_id`，它就可以和 `school_majors` 并行执行。

### 启动门禁

与 `school_majors` 相同，`major_admission_results` 在 `start_requests()` 前必须校验最近一次：

- `schools`
- `majors`

任务都满足：

- `status = success`
- `failed_items = 0`
- `finished_at IS NOT NULL`

任一条件不满足，直接跳过本轮，不抓半成品。

## Spider 抓取策略

### 请求维度

请求粒度按：

- 学校
- 省份
- 年份
- 科类/选科

展开。Spider 的核心工作是从学校招生/录取页面中提取某省某年某科类下的专业录取结果，并规范化为事实表记录。

### 学校来源

学校来源直接读取 `schools` 表，而不是依赖 `school_majors`。这样即使学校专业关联还在补数，录取结果 spider 也能先抓出事实数据。

### 专业解析

录取结果页中的专业标识解析优先级保持与 `school_major_spider` 一致：

1. `source_id`
2. `code`
3. 专业名精确匹配

如果专业名存在歧义，则跳过该条并告警，不做猜测性绑定。

### 科类解析

科类/选科信息尽量标准化映射到 `subject_categories`：

- 能命中已有维表时，写入 `subject_category_id`
- 无法命中时，保留 `subject_category_raw`，并复用现有自动注册或保守跳过策略

### 原始文本保留

为避免后续因为口径变化丢信息，下列字段即使已结构化，也保留原文：

- `major_name_raw`
- `subject_category_raw`
- `batch_raw`
- `remark`

## 热门专业数据支持

底层不预先计算唯一“热门值”，但要让后端具备综合 `A+B` 的能力：

### A：满意度

继续复用：

- `major_satisfaction`
- `school_satisfaction`

### B：招生/录取热度

由新事实表提供：

- `admitted_count`
- 近 N 年该专业在该校该省的出现频次
- 近 N 年分数/位次稳定性

这样后端输入学校名时，就能同时结合：

- 满意度高
- 录取人数高
- 多年持续招生/录取

来定义“热门专业”。

## 与现有表的关系

### `enrollment_plans`

仍然只表示招生计划，不承载录取结果。后端若需要“计划与录取同时看”，应在查询层联表，而不是在抓取层混表。

### `school_majors`

仍然表示全国范围内“学校开设过哪些专业”的存在性关系，不按省份拆分。

### `admission_score_lines`

仍然表示省控线，不直接用于学校/专业录取事实。

## 测试策略

本次只做本地单元测试和解析测试，不做真实网站抓取。

需要覆盖：

1. schema / upsert
   - 新表唯一键正确
   - 同一自然键重复写入走更新/去重逻辑
2. spider 启动门禁
   - `schools` 不稳定时跳过
   - `majors` 不稳定时跳过
   - 两者稳定时才开始请求
3. 录取结果解析
   - 能从 fixture 中解析 `school_id + major_id + province_id + year + batch + score/rank`
   - 专业歧义时只告警，不写错数据
4. orchestrator 接入
   - 新任务被加入 Phase 3
   - 不破坏现有 Phase 2 / Phase 3 门禁

## 实现落点

- `src/gaokao_vault/constants.py`
  - 新增 `TaskType.MAJOR_ADMISSION_RESULTS`
- `src/gaokao_vault/db/schema.sql`
  - 新增 `major_admission_results` 表与索引
- `src/gaokao_vault/models/`
  - 新增录取事实模型
- `src/gaokao_vault/db/queries/`
  - 新增 upsert/query 方法
- `src/gaokao_vault/spiders/`
  - 新增录取结果 spider
- `src/gaokao_vault/scheduler/orchestrator.py`
  - 将新任务接入 Phase 3
- `tests/`
  - 增加解析、门禁、upsert、编排测试

## 验收标准

- 底层数据库中存在可按“学校-专业-省份-年份”筛选的录取事实数据表。
- 后端无需再用 `enrollment_plans + score_lines` 猜测学校/专业录取门槛。
- 输入“吉林 400 分 + 江苏苏州”时，后端至少具备按事实表筛出学校-专业候选的底层数据基础。
- 输入学校时，后端能基于满意度和招生/录取热度自行定义热门专业，而不是受限于单一字段。
- 本地只完成代码与单元测试，不执行真实抓取；真实效果由服务器定时任务验证。
