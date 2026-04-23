# 吉林分数择校择专业底层数据补齐设计

## 背景

当前仓库已经能够抓取并入库多类高考数据，包括：

- `schools`：院校基础信息
- `majors`：专业维表
- `school_majors`：学校-专业关联
- `admission_score_lines`：省控线/批次线
- `score_segments`：一分一段
- `enrollment_plans`：学校-省份-年份招生计划
- `major_satisfaction` / `school_satisfaction`：满意度数据

但当后端要回答类似“吉林 500 分能考到苏州什么学校和专业”时，现有底层数据链仍然不完整，主要断点有：

1. 缺稳定的吉林一分一段换算能力，分数无法换成位次。
2. `schools` 中学校地域信息仍可能不完整，后端难以稳定筛出“江苏苏州学校集合”。
3. `school_majors` 覆盖仍可能不足，无法完整得到学校开设专业全集。
4. `enrollment_plans` 即使存在，也只说明“计划招生”，不能直接说明录取门槛。
5. 缺少“学校-专业-省份-年份”的真实录取事实，无法对“500 分/某位次能不能报”做相对准确判断。

用户明确要求：

- 先把底层数据补齐到“可筛选、可判断”的程度。
- 问答/检索接口如何实现，交由后端自己决定。
- “热门专业”需要综合满意度与招生/录取热度，而不是只看单一指标。
- 本地不执行真实爬取，只做设计、代码和本地单元测试；真实抓取由服务器定时任务完成。

## 目标与非目标

### 目标

- 补齐一条完整的择校择专业判断链路：
  - `吉林分数 -> 吉林位次 -> 苏州学校 -> 吉林招生计划 -> 学校专业集合 -> 专业历年录取事实`
- 提升以下现有表的覆盖率和稳定性：
  - `score_segments`
  - `schools`
  - `school_majors`
  - `enrollment_plans`
- 新增一张“学校-专业-省份-年份”录取事实表，承载后端最终判断所需的关键数据。
- 为后端提供可综合 `A + B` 计算“热门专业”的底层原始依据：
  - `A`：满意度
  - `B`：招生/录取热度
- 继续保持现有增量抓取、去重、快照、三阶段编排模式。

### 非目标

- 不在本次实现中开发问答 API、查询接口或推荐排序服务。
- 不在底层提前计算唯一的“热门专业分值”。
- 不在本地执行真实网站抓取或真实入库验证。
- 不改变 `enrollment_plans` 的业务语义；招生计划与录取结果继续分表。
- 不引入“运行前清表”的策略。

## 设计概览

整体设计分成两部分：

1. **补齐现有四类基础数据**
   - `score_segments`：解决分数到位次的换算
   - `schools`：解决地域筛选
   - `school_majors`：解决学校专业全集
   - `enrollment_plans`：解决学校/专业在吉林是否招生、计划数多少
2. **新增录取事实表**
   - `major_admission_results`：承载学校-专业-省份-年份的录取结果事实

最终后端要回答“吉林 500 分能考到哪些苏州学校和专业”，不能单靠一张表，而是联用以上五类数据完成判断。

## 判定链路

后端最终应基于以下顺序判断：

1. 用 `score_segments` 将“吉林 500 分”换算成吉林当年对应位次。
2. 用 `schools` 筛出江苏苏州学校。
3. 用 `enrollment_plans` 判断这些学校在吉林是否招生、招哪些专业、计划数多少。
4. 用 `school_majors` 补齐学校开设专业全集，避免只靠计划页漏掉学校专业关系。
5. 用 `major_admission_results` 判断“该学校该专业在吉林往年的最低位次/最低分是否覆盖当前位次”。
6. 若需要展示“热门专业”，由后端综合：
   - `major_satisfaction` / `school_satisfaction`
   - `enrollment_plans` 与 `major_admission_results` 中的热度字段

也就是说，系统的核心判断链不再是：

`分数 -> 直接猜学校/专业`

而是：

`分数 -> 位次 -> 学校集合 -> 招生计划 -> 学校专业 -> 历年录取事实`

## 五类数据的职责边界

### 1. `score_segments`

职责：

- 解决“吉林 500 分对应什么位次”

补齐要求：

- `province_id = 吉林` 的历年一分一段数据可用
- `subject_category_id` 映射稳定
- 至少能提供用于位次换算的累计人数/累计排名

注意：

- `score_segments` 只负责分数与位次关系，不负责学校或专业维度判断

### 2. `schools`

职责：

- 解决“哪些学校属于江苏苏州”

补齐要求：

- `province_id` 不能长期为空
- `city` 字段需足够稳定地识别“苏州”
- 学校基础信息抓取要尽可能保证地域字段准确

注意：

- `schools` 只负责学校地域和基础属性，不负责招生或录取结论

### 3. `school_majors`

职责：

- 解决“这所学校有哪些专业”

补齐要求：

- 学校-专业关联覆盖率提升
- 专业代码 / 名称 fallback 持续补强
- 上游不稳定时宁可跳过，不接受半成品

注意：

- `school_majors` 仍然是全国范围的学校-专业存在性关系
- 不按招生省份拆表

### 4. `enrollment_plans`

职责：

- 解决“这所学校这个专业在吉林是否招生、招多少”

补齐要求：

- 在 `school_id + province_id + year + subject_category_id + major_name/major_id` 粒度上有稳定记录
- 吉林维度必须有足够覆盖
- `plan_count`、`batch`、`note` 等字段可用

注意：

- `enrollment_plans` 只表示“计划”，不能替代真实录取结果

### 5. `major_admission_results`

职责：

- 解决“该学校该专业在吉林往年录取到什么分/位次”

补齐要求：

- 至少有 `min_score` 或 `min_rank`
- 最好同时有 `avg_score` / `avg_rank` / `admitted_count`
- 能稳定映射到 `major_id`

注意：

- 这是新表，专门承载录取事实，不与 `enrollment_plans` 混表

## 新增录取事实表设计

### 表名

- `major_admission_results`

### 建议字段

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

- `school_id` / `major_id`：统一引用现有学校与专业主键
- `province_id`：表示招生省份，例如吉林
- `subject_category_id`：尽量映射到现有科类/选科维表
- `batch`：结构化批次，便于筛选
- `*_raw`：保留原站口径，便于后续纠错或规则调整
- `min_rank`：后端按位次判断时的核心依据
- `min_score`：作为兜底展示和分数维度辅助
- `admitted_count`：录取热度原始指标之一

### 唯一键与更新策略

唯一键建议为：

- `school_id`
- `major_id`
- `province_id`
- `year`
- `subject_category_id`
- `batch`

后续仍然沿用：

- `content_hash`
- `crawl_task_id`
- `crawl_snapshots`

来完成增量更新与历史追溯。

## 抓取任务与编排设计

### 新任务类型

新增：

- `TaskType.MAJOR_ADMISSION_RESULTS = "major_admission_results"`

### 编排位置

该任务加入现有 `Phase 3`，不新增 `Phase 4`。

原因：

- 它依赖 `schools` 和 `majors` 两张核心实体表
- 但不要求 `school_majors` 先完整完成
- 它可以在抓取时自己解析 `major_id`

### 启动门禁

与现在的 `school_majors` 一样，新任务启动前必须校验最近一次：

- `schools`
- `majors`

任务都满足：

- `status = success`
- `failed_items = 0`
- `finished_at IS NOT NULL`

任一条件不满足则跳过，不抓半成品。

## Spider 设计

### 学校来源

学校来源直接读取 `schools` 表，而不是依赖 `school_majors`。

这样即使学校专业关联仍在补数，录取事实 spider 也能独立推进。

### 请求维度

请求维度按：

- 学校
- 省份
- 年份
- 科类/选科

展开。

Spider 负责从学校招生/录取相关页面中提取：

- 该省该年该科类下的专业录取结果
- 最低分 / 最低位次 / 平均分 / 平均位次 / 录取人数等事实

### 专业解析

录取页中的专业标识解析优先级与 `school_major_spider` 保持一致：

1. `source_id`
2. `code`
3. 专业名精确匹配

若专业名歧义，则跳过并记录 warning，不做猜测性绑定。

### 科类解析

科类/选科信息尽量映射到 `subject_categories`：

- 命中已有维表：写 `subject_category_id`
- 无法命中：保留 `subject_category_raw`

### 原始文本保留

为避免后续因为口径变化丢失信息，保留：

- `major_name_raw`
- `subject_category_raw`
- `batch_raw`
- `remark`

## 热门专业数据支持

底层不提前计算唯一“热门值”，但要为后端提供综合 `A + B` 的原始依据。

### A：满意度

继续复用：

- `major_satisfaction`
- `school_satisfaction`

### B：招生/录取热度

由现有和新增表提供：

- `enrollment_plans.plan_count`
- `major_admission_results.admitted_count`
- 近 N 年某专业在某校某省出现次数
- 近 N 年录取分/位次稳定性

这样后端输入学校名时，可自行定义：

- 满意度优先
- 招生热度优先
- 综合满意度与热度

## 与现有表的关系

### `enrollment_plans`

仍然只表示招生计划，不承载录取结果。

### `school_majors`

仍然表示学校开设过哪些专业，不按省份拆分。

### `admission_score_lines`

仍然表示省控线，不直接用作学校/专业录取事实。

### `score_segments`

负责位次换算，是后端按位次判断的第一步。

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
- `src/gaokao_vault/spiders/`
  - 继续加强 `schools` / `school_majors` / `enrollment_plans` / `score_segments` 对吉林+苏州判断链的覆盖支撑
- `tests/`
  - 补充 schema、upsert、门禁、解析、编排测试

## 测试策略

本次只做本地单元测试和解析测试，不做真实网站抓取。

需要覆盖：

1. `score_segments`
   - 吉林分数到位次换算依赖的数据字段完整
2. `schools`
   - 苏州学校的地域字段可被正确识别
3. `school_majors`
   - 学校专业关系覆盖与 fallback 不退化
4. `enrollment_plans`
   - 吉林招生计划的专业维度记录可落到结构化字段
5. `major_admission_results`
   - 录取结果事实表唯一键和 upsert 正确
   - 录取页解析能落成 `school_id + major_id + province_id + year + batch + score/rank`
6. orchestrator
   - 新任务接入 Phase 3
   - 不破坏现有 Phase 2 / Phase 3 门禁

## 验收标准

- 后端拥有一条完整可用的数据链来判断：
  - 吉林某分数对应位次
  - 苏州学校集合
  - 吉林招生计划
  - 学校专业集合
  - 专业历年录取事实
- 不再因为缺 `score_segments` / `enrollment_plans` / `schools` / `school_majors` / 录取事实中的任一环，而无法做基础判断。
- 输入学校时，后端可以基于满意度和招生/录取热度自行决定“热门专业”。
- 本地只完成代码与单元测试，不执行真实爬取；真实补数效果由服务器定时任务验证。
