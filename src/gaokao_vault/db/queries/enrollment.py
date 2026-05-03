from __future__ import annotations

import json

import asyncpg


async def upsert_enrollment_plan(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO enrollment_plans (school_id, province_id, year, subject_category_id,
            batch, batch_code, batch_category, batch_segment, major_name, major_id, plan_count, duration, tuition, note,
            major_group_code, major_code_raw, campus, education_location,
            selection_requirement, physical_exam_limit, single_subject_limit,
            adjustment_rule, program_type, eligibility_requirements,
            physical_exam_or_political_review, political_review_requirement, service_obligation,
            data_source, source_url, source_updated_at, quality_flags,
            content_hash, crawl_task_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32,$33)
        ON CONFLICT (school_id, province_id, year, subject_category_id, batch, major_name) DO UPDATE SET
            batch_code = EXCLUDED.batch_code,
            batch_category = EXCLUDED.batch_category,
            batch_segment = EXCLUDED.batch_segment,
            major_id = EXCLUDED.major_id,
            plan_count = EXCLUDED.plan_count,
            duration = EXCLUDED.duration,
            tuition = EXCLUDED.tuition,
            note = EXCLUDED.note,
            major_group_code = EXCLUDED.major_group_code,
            major_code_raw = EXCLUDED.major_code_raw,
            campus = EXCLUDED.campus,
            education_location = EXCLUDED.education_location,
            selection_requirement = EXCLUDED.selection_requirement,
            physical_exam_limit = EXCLUDED.physical_exam_limit,
            single_subject_limit = EXCLUDED.single_subject_limit,
            adjustment_rule = EXCLUDED.adjustment_rule,
            program_type = EXCLUDED.program_type,
            eligibility_requirements = EXCLUDED.eligibility_requirements,
            physical_exam_or_political_review = EXCLUDED.physical_exam_or_political_review,
            political_review_requirement = EXCLUDED.political_review_requirement,
            service_obligation = EXCLUDED.service_obligation,
            data_source = EXCLUDED.data_source,
            source_url = EXCLUDED.source_url,
            source_updated_at = EXCLUDED.source_updated_at,
            quality_flags = EXCLUDED.quality_flags,
            content_hash = EXCLUDED.content_hash,
            crawl_task_id = EXCLUDED.crawl_task_id
        RETURNING id
        """,
        data["school_id"],
        data["province_id"],
        data["year"],
        data.get("subject_category_id"),
        data.get("batch"),
        data.get("batch_code"),
        data.get("batch_category"),
        data.get("batch_segment"),
        data.get("major_name"),
        data.get("major_id"),
        data.get("plan_count"),
        data.get("duration"),
        data.get("tuition"),
        data.get("note"),
        data.get("major_group_code"),
        data.get("major_code_raw"),
        data.get("campus"),
        data.get("education_location"),
        data.get("selection_requirement"),
        data.get("physical_exam_limit"),
        data.get("single_subject_limit"),
        data.get("adjustment_rule"),
        data.get("program_type"),
        data.get("eligibility_requirements"),
        data.get("physical_exam_or_political_review"),
        data.get("political_review_requirement"),
        data.get("service_obligation"),
        data.get("data_source"),
        data.get("source_url"),
        data.get("source_updated_at"),
        json.dumps(data.get("quality_flags", []), ensure_ascii=False),
        data.get("content_hash"),
        data.get("crawl_task_id"),
    )
    return row["id"]


async def upsert_charter(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO admission_charters (school_id, year, title, content, publish_date,
            source_url, content_hash, crawl_task_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        ON CONFLICT (school_id, year) DO UPDATE SET
            title=EXCLUDED.title, content=EXCLUDED.content,
            publish_date=EXCLUDED.publish_date, source_url=EXCLUDED.source_url,
            content_hash=EXCLUDED.content_hash, crawl_task_id=EXCLUDED.crawl_task_id
        RETURNING id
        """,
        data["school_id"],
        data["year"],
        data.get("title"),
        data["content"],
        data.get("publish_date"),
        data.get("source_url"),
        data.get("content_hash"),
        data.get("crawl_task_id"),
    )
    return row["id"]


async def upsert_timeline(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO volunteer_timelines (province_id, year, batch, start_time, end_time, note,
            content_hash, crawl_task_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        ON CONFLICT (province_id, year, batch) DO UPDATE SET
            start_time=EXCLUDED.start_time, end_time=EXCLUDED.end_time, note=EXCLUDED.note,
            content_hash=EXCLUDED.content_hash, crawl_task_id=EXCLUDED.crawl_task_id
        RETURNING id
        """,
        data["province_id"],
        data["year"],
        data["batch"],
        data.get("start_time"),
        data.get("end_time"),
        data.get("note"),
        data.get("content_hash"),
        data.get("crawl_task_id"),
    )
    return row["id"]
