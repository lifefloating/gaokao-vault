from __future__ import annotations

import json

import asyncpg


async def upsert_special_enrollment(conn: asyncpg.Connection, data: dict) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO special_enrollments (enrollment_type, special_admission_type, province_code, school_id,
            school_code_raw, school_name_raw, year, title, content, content_text, publish_date, source_url,
            source_section, detail_url, application_url, registration_window, registration_start, registration_end,
            milestones, shortlist_rule, selection_rule, school_assessment, school_exam_rule, composite_score_formula,
            admission_rule, eligible_majors, quality_flags, content_hash, crawl_task_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29)
        ON CONFLICT (enrollment_type, school_id, school_code_raw, year, title, source_section, detail_url)
        DO UPDATE SET
            special_admission_type=EXCLUDED.special_admission_type,
            province_code=EXCLUDED.province_code,
            school_code_raw=EXCLUDED.school_code_raw,
            school_name_raw=EXCLUDED.school_name_raw,
            content=EXCLUDED.content,
            content_text=EXCLUDED.content_text,
            publish_date=EXCLUDED.publish_date,
            source_url=EXCLUDED.source_url,
            source_section=EXCLUDED.source_section,
            detail_url=EXCLUDED.detail_url,
            application_url=EXCLUDED.application_url,
            registration_window=EXCLUDED.registration_window,
            registration_start=EXCLUDED.registration_start,
            registration_end=EXCLUDED.registration_end,
            milestones=EXCLUDED.milestones,
            shortlist_rule=EXCLUDED.shortlist_rule,
            selection_rule=EXCLUDED.selection_rule,
            school_assessment=EXCLUDED.school_assessment,
            school_exam_rule=EXCLUDED.school_exam_rule,
            composite_score_formula=EXCLUDED.composite_score_formula,
            admission_rule=EXCLUDED.admission_rule,
            eligible_majors=EXCLUDED.eligible_majors,
            quality_flags=EXCLUDED.quality_flags,
            content_hash=EXCLUDED.content_hash,
            crawl_task_id=EXCLUDED.crawl_task_id
        RETURNING id
        """,
        data["enrollment_type"],
        data.get("special_admission_type"),
        data.get("province_code"),
        data.get("school_id"),
        data.get("school_code_raw"),
        data.get("school_name_raw"),
        data["year"],
        data.get("title"),
        data.get("content"),
        data.get("content_text"),
        data.get("publish_date"),
        data.get("source_url"),
        data.get("source_section"),
        data.get("detail_url"),
        data.get("application_url"),
        json.dumps(data.get("registration_window", {}), ensure_ascii=False),
        data.get("registration_start"),
        data.get("registration_end"),
        json.dumps(data.get("milestones", {}), ensure_ascii=False),
        data.get("shortlist_rule"),
        data.get("selection_rule"),
        data.get("school_assessment"),
        data.get("school_exam_rule"),
        data.get("composite_score_formula"),
        data.get("admission_rule"),
        json.dumps(data.get("eligible_majors", []), ensure_ascii=False),
        json.dumps(data.get("quality_flags", []), ensure_ascii=False),
        data.get("content_hash"),
        data.get("crawl_task_id"),
    )
    return row["id"]
