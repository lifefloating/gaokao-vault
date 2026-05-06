# 强基计划数据设计

强基计划按官方口径建模为独立特殊招生链路，仅进入 `special_enrollments` 与
`gaokao_source.vector_documents_v`，不并入普通批/提前批筛选草表。普通批与提前批仍使用
`major_admission_results`、`enrollment_plans` 和批次归一化字段完成推荐筛选。

## 官方依据

强基计划数据优先使用官方页面和高校简章：

- 阳光高考强基专题：<https://gaokao.chsi.com.cn/gkzt/jcxkzs>
- 阳光高考强基高校列表：<https://gaokao.chsi.com.cn/gkzt/jcxkzs#jcxkzs-sch>
- 强基报名平台学校入口：<https://bm.chsi.com.cn/jcxkzs/sch/>
- 教育部强基录取方式说明：<https://www.moe.gov.cn/>

设计依据是：强基计划需要看高校招生简章、报名入口、入围规则、高校考核、综合成绩折算和
录取方式。它不是按普通批投档线或提前批计划数直接筛选的志愿批次。

## 数据链路

`special_spider` 对强基计划抓取两类官方数据：

| 来源 | 内容 | 入库字段 |
|------|------|----------|
| 阳光高考强基专题 | 流程说明、高校入口、专题公告 | `enrollment_type`, `special_admission_type`, `source_section` |
| 报名平台学校页 | 高校简章、报名入口、公告、录取标准 | `application_url`, `detail_url`, `content_text` |

强基记录写入 `special_enrollments`，关键字段如下：

| 字段 | 含义 |
|------|------|
| `special_admission_type` | 固定为 `strong_foundation` |
| `application_url` | 报名平台入口 |
| `registration_window` / `registration_start` / `registration_end` | 报名时间 |
| `shortlist_rule` / `selection_rule` | 入围与选拔规则 |
| `school_assessment` / `school_exam_rule` | 高校考核、校测或体育测试要求 |
| `composite_score_formula` | 综合成绩折算规则 |
| `admission_rule` | 录取方式 |
| `eligible_majors` | 简章中可识别的招生专业 |
| `quality_flags` | 关键字段缺失标记 |

同一学校可能存在简章、公告、录取标准等多条强基记录。唯一键包含
`enrollment_type`、`school_id`、`school_code_raw`、`year`、`title`、`source_section` 和
`detail_url`，避免 `school_id` 暂缺时跨学校覆盖。

## 推荐与向量边界

强基计划不参与普通批/提前批候选链路：

- 批次归一化遇到 `强基` 时返回空批次分类，不标记为 `regular` 或 `early`。
- 普通推荐查询继续使用 `major_admission_results` 和 `enrollment_plans`。
- 强基筛选应从 `special_enrollments` 或 `gaokao_source.special_enrollments_v` 读取。

向量库入口是 `gaokao_source.vector_documents_v`。强基文档的 `text` 由标题和 `content_text`
组成，`metadata` 保留报名入口、入围规则、高校考核、综合成绩折算、录取方式、招生专业和来源 URL，
便于后续按学校、年份、招生类型和官方来源过滤检索。
