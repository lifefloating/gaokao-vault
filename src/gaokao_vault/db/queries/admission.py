from __future__ import annotations

import json

import asyncpg


async def upsert_major_admission_result(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO major_admission_results (
            school_id, major_id, province_id, year, subject_category_id, batch,
            batch_code, batch_category, batch_segment,
            min_score, min_rank, avg_score, avg_rank, max_score, max_rank,
            admitted_count, plan_count, school_code_raw, school_name_raw, major_group_code,
            major_code_raw, campus, program_type, eligibility_requirements,
            physical_exam_or_political_review, political_review_requirement, service_obligation,
            major_name_raw, subject_category_raw, batch_raw,
            remark, source_url, data_source, source_updated_at, quality_flags,
            content_hash, crawl_task_id
        )
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32,$33,$34,$35,$36,$37)
        ON CONFLICT (school_id, major_id, province_id, year, subject_category_id, batch) DO UPDATE SET
            batch_code=EXCLUDED.batch_code,
            batch_category=EXCLUDED.batch_category,
            batch_segment=EXCLUDED.batch_segment,
            min_score=EXCLUDED.min_score,
            min_rank=EXCLUDED.min_rank,
            avg_score=EXCLUDED.avg_score,
            avg_rank=EXCLUDED.avg_rank,
            max_score=EXCLUDED.max_score,
            max_rank=EXCLUDED.max_rank,
            admitted_count=EXCLUDED.admitted_count,
            plan_count=EXCLUDED.plan_count,
            school_code_raw=EXCLUDED.school_code_raw,
            school_name_raw=EXCLUDED.school_name_raw,
            major_group_code=EXCLUDED.major_group_code,
            major_code_raw=EXCLUDED.major_code_raw,
            campus=EXCLUDED.campus,
            program_type=EXCLUDED.program_type,
            eligibility_requirements=EXCLUDED.eligibility_requirements,
            physical_exam_or_political_review=EXCLUDED.physical_exam_or_political_review,
            political_review_requirement=EXCLUDED.political_review_requirement,
            service_obligation=EXCLUDED.service_obligation,
            major_name_raw=EXCLUDED.major_name_raw,
            subject_category_raw=EXCLUDED.subject_category_raw,
            batch_raw=EXCLUDED.batch_raw,
            remark=EXCLUDED.remark,
            source_url=EXCLUDED.source_url,
            data_source=EXCLUDED.data_source,
            source_updated_at=EXCLUDED.source_updated_at,
            quality_flags=EXCLUDED.quality_flags,
            content_hash=EXCLUDED.content_hash,
            crawl_task_id=EXCLUDED.crawl_task_id
        RETURNING id
        """,
        data["school_id"],
        data["major_id"],
        data["province_id"],
        data["year"],
        data.get("subject_category_id"),
        data["batch"],
        data.get("batch_code"),
        data.get("batch_category"),
        data.get("batch_segment"),
        data.get("min_score"),
        data.get("min_rank"),
        data.get("avg_score"),
        data.get("avg_rank"),
        data.get("max_score"),
        data.get("max_rank"),
        data.get("admitted_count"),
        data.get("plan_count"),
        data.get("school_code_raw"),
        data.get("school_name_raw"),
        data.get("major_group_code"),
        data.get("major_code_raw"),
        data.get("campus"),
        data.get("program_type"),
        data.get("eligibility_requirements"),
        data.get("physical_exam_or_political_review"),
        data.get("political_review_requirement"),
        data.get("service_obligation"),
        data.get("major_name_raw"),
        data.get("subject_category_raw"),
        data.get("batch_raw"),
        data.get("remark"),
        data.get("source_url"),
        data.get("data_source"),
        data.get("source_updated_at"),
        json.dumps(data.get("quality_flags", []), ensure_ascii=False),
        data.get("content_hash"),
        data.get("crawl_task_id"),
    )
    return row["id"]
