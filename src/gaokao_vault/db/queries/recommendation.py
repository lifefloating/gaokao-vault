from __future__ import annotations

import asyncpg

from gaokao_vault.models.recommendation import CandidateProfile


async def find_candidate_admission_chain(
    conn: asyncpg.Connection,
    profile: CandidateProfile,
    *,
    years_back: int = 3,
) -> list[dict]:
    lower_rank = max(1, profile.rank - profile.rank_window)
    upper_rank = profile.rank + profile.rank_window
    rows = await conn.fetch(
        """
        WITH recent_admissions AS (
            SELECT
                mar.school_id,
                mar.major_id,
                mar.year,
                mar.batch,
                mar.min_score,
                mar.min_rank,
                mar.admitted_count,
                mar.school_code_raw,
                mar.major_group_code,
                mar.major_code_raw,
                mar.campus,
                s.name AS school_name,
                s.city AS school_city,
                m.code AS major_code,
                m.name AS major_name,
                ep.plan_count AS current_plan_count,
                ep.selection_requirement,
                ep.physical_exam_limit,
                ep.single_subject_limit,
                ep.adjustment_rule,
                ep.tuition,
                ep.education_location
            FROM major_admission_results mar
            JOIN schools s ON s.id = mar.school_id
            JOIN majors m ON m.id = mar.major_id
            LEFT JOIN enrollment_plans ep
              ON ep.school_id = mar.school_id
             AND ep.province_id = mar.province_id
             AND ep.year = $2
             AND ep.subject_category_id IS NOT DISTINCT FROM mar.subject_category_id
             AND ep.batch IS NOT DISTINCT FROM mar.batch
             AND ep.major_id IS NOT DISTINCT FROM mar.major_id
            WHERE mar.province_id = $1
              AND mar.year BETWEEN ($2 - $8) AND ($2 - 1)
              AND mar.subject_category_id IS NOT DISTINCT FROM $3
              AND mar.batch = $4
              AND mar.min_rank BETWEEN $5 AND $6
        )
        SELECT
            school_id,
            school_code_raw,
            school_name,
            school_city,
            major_id,
            major_code,
            major_name,
            major_group_code,
            major_code_raw,
            campus,
            batch,
            MAX(current_plan_count) AS current_plan_count,
            MAX(selection_requirement) AS selection_requirement,
            MAX(physical_exam_limit) AS physical_exam_limit,
            MAX(single_subject_limit) AS single_subject_limit,
            MAX(adjustment_rule) AS adjustment_rule,
            MAX(tuition) AS tuition,
            MAX(education_location) AS education_location,
            JSONB_AGG(
                JSONB_BUILD_OBJECT(
                    'year', year,
                    'min_score', min_score,
                    'min_rank', min_rank,
                    'admitted_count', admitted_count
                )
                ORDER BY year DESC
            ) AS admission_history,
            MIN(ABS(min_rank - $7)) AS rank_distance
        FROM recent_admissions
        GROUP BY
            school_id, school_code_raw, school_name, school_city, major_id,
            major_code, major_name, major_group_code, major_code_raw, campus, batch
        ORDER BY rank_distance, school_name, major_name
        """,
        profile.province_id,
        profile.year,
        profile.subject_category_id,
        profile.batch,
        lower_rank,
        upper_rank,
        profile.rank,
        years_back,
    )
    return [dict(row) for row in rows]
