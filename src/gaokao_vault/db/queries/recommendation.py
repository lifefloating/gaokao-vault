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
        WITH matched_candidates AS (
            SELECT DISTINCT
                mar.school_id,
                mar.major_id,
                m.name AS major_name
            FROM major_admission_results mar
            JOIN majors m ON m.id = mar.major_id
            WHERE mar.province_id = $1
              AND mar.year BETWEEN ($2 - $8) AND ($2 - 1)
              AND mar.subject_category_id IS NOT DISTINCT FROM $3
              AND mar.batch = $4
              AND mar.min_rank BETWEEN $5 AND $6
        ),
        current_plans AS (
            SELECT
                ep.school_id,
                mc.major_id,
                SUM(ep.plan_count)::INTEGER AS current_plan_count,
                MIN(ep.major_group_code) AS primary_major_group_code,
                MIN(ep.major_code_raw) AS primary_major_code_raw,
                MIN(ep.campus) AS primary_campus,
                MAX(ep.batch) AS batch,
                MAX(ep.batch_code) AS batch_code,
                MAX(ep.selection_requirement) AS selection_requirement,
                MAX(ep.physical_exam_limit) AS physical_exam_limit,
                MAX(ep.single_subject_limit) AS single_subject_limit,
                MAX(ep.adjustment_rule) AS adjustment_rule,
                MAX(ep.program_type) AS program_type,
                MAX(ep.eligibility_requirements) AS eligibility_requirements,
                MAX(ep.physical_exam_or_political_review) AS physical_exam_or_political_review,
                MAX(ep.political_review_requirement) AS political_review_requirement,
                MAX(ep.service_obligation) AS service_obligation,
                MAX(ep.tuition) AS tuition,
                MAX(ep.education_location) AS education_location,
                JSONB_AGG(
                    JSONB_BUILD_OBJECT(
                        'year', ep.year,
                        'batch', ep.batch,
                        'batch_code', ep.batch_code,
                        'batch_category', ep.batch_category,
                        'batch_segment', ep.batch_segment,
                        'major_group_code', ep.major_group_code,
                        'major_code_raw', ep.major_code_raw,
                        'major_name', ep.major_name,
                        'plan_count', ep.plan_count,
                        'selection_requirement', ep.selection_requirement,
                        'physical_exam_limit', ep.physical_exam_limit,
                        'single_subject_limit', ep.single_subject_limit,
                        'adjustment_rule', ep.adjustment_rule,
                        'program_type', ep.program_type,
                        'eligibility_requirements', ep.eligibility_requirements,
                        'physical_exam_or_political_review', ep.physical_exam_or_political_review,
                        'political_review_requirement', ep.political_review_requirement,
                        'service_obligation', ep.service_obligation,
                        'tuition', ep.tuition,
                        'campus', ep.campus,
                        'education_location', ep.education_location
                    )
                    ORDER BY ep.major_group_code NULLS LAST, ep.major_code_raw NULLS LAST, ep.major_name NULLS LAST
                ) AS current_plan_options
            FROM enrollment_plans ep
            JOIN matched_candidates mc
              ON mc.school_id = ep.school_id
             AND (ep.major_id = mc.major_id OR ep.major_name = mc.major_name)
            WHERE ep.province_id = $1
              AND ep.year = $2
              AND ep.subject_category_id IS NOT DISTINCT FROM $3
              AND ep.batch = $4
            GROUP BY ep.school_id, mc.major_id
        ),
        admission_history AS (
            SELECT
                mar.school_id,
                mar.major_id,
                MAX(mar.school_code_raw) AS school_code_raw,
                MIN(mar.major_group_code) AS primary_major_group_code,
                MIN(mar.major_code_raw) AS primary_major_code_raw,
                MIN(mar.campus) AS primary_campus,
                MAX(mar.batch) AS batch,
                MAX(mar.batch_code) AS batch_code,
                MAX(mar.plan_count) AS historical_plan_count,
                MAX(mar.program_type) AS program_type,
                MAX(mar.eligibility_requirements) AS eligibility_requirements,
                MAX(mar.physical_exam_or_political_review) AS physical_exam_or_political_review,
                MAX(mar.political_review_requirement) AS political_review_requirement,
                MAX(mar.service_obligation) AS service_obligation,
                JSONB_AGG(
                    JSONB_BUILD_OBJECT(
                        'year', mar.year,
                        'batch', mar.batch,
                        'batch_code', mar.batch_code,
                        'major_group_code', mar.major_group_code,
                        'major_code_raw', mar.major_code_raw,
                        'campus', mar.campus,
                        'min_score', mar.min_score,
                        'min_rank', mar.min_rank,
                        'admitted_count', mar.admitted_count,
                        'plan_count', mar.plan_count
                    )
                    ORDER BY mar.year DESC
                ) AS admission_history,
                MIN(ABS(mar.min_rank - $7)) AS rank_distance
            FROM major_admission_results mar
            JOIN matched_candidates mc
              ON mc.school_id = mar.school_id
             AND mc.major_id = mar.major_id
            WHERE mar.province_id = $1
              AND mar.year BETWEEN ($2 - $8) AND ($2 - 1)
              AND mar.subject_category_id IS NOT DISTINCT FROM $3
              AND mar.batch = $4
            GROUP BY mar.school_id, mar.major_id
        )
        SELECT
            mc.school_id,
            history.school_code_raw,
            s.name AS school_name,
            s.city AS school_city,
            mc.major_id,
            m.code AS major_code,
            m.name AS major_name,
            COALESCE(plans.primary_major_group_code, history.primary_major_group_code) AS major_group_code,
            COALESCE(plans.primary_major_code_raw, history.primary_major_code_raw) AS major_code_raw,
            COALESCE(plans.primary_campus, history.primary_campus) AS campus,
            COALESCE(plans.batch, history.batch, $4) AS batch,
            COALESCE(plans.batch_code, history.batch_code) AS batch_code,
            plans.current_plan_count,
            plans.current_plan_options,
            history.historical_plan_count,
            plans.selection_requirement,
            plans.physical_exam_limit,
            plans.single_subject_limit,
            plans.adjustment_rule,
            COALESCE(plans.program_type, history.program_type) AS program_type,
            COALESCE(plans.eligibility_requirements, history.eligibility_requirements) AS eligibility_requirements,
            COALESCE(plans.physical_exam_or_political_review, history.physical_exam_or_political_review)
                AS physical_exam_or_political_review,
            COALESCE(plans.political_review_requirement, history.political_review_requirement)
                AS political_review_requirement,
            COALESCE(plans.service_obligation, history.service_obligation) AS service_obligation,
            plans.tuition,
            plans.education_location,
            history.admission_history,
            history.rank_distance
        FROM matched_candidates mc
        JOIN schools s ON s.id = mc.school_id
        JOIN majors m ON m.id = mc.major_id
        LEFT JOIN current_plans plans
          ON plans.school_id = mc.school_id
         AND plans.major_id = mc.major_id
        LEFT JOIN admission_history history
          ON history.school_id = mc.school_id
         AND history.major_id = mc.major_id
        ORDER BY history.rank_distance NULLS LAST, s.name, m.name
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
