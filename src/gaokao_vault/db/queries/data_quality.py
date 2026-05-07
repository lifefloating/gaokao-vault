from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import asyncpg

COMPLETENESS_YEAR_WINDOW = 3
CURRENT_YEAR_READY_MONTH = 12

_MAJOR_ANSWER_READINESS_CTE_SQL = """
        WITH target_province AS (
            SELECT id, code, name
            FROM provinces
            WHERE code = $1 OR name = $1
            ORDER BY CASE WHEN name = $1 THEN 0 ELSE 1 END
            LIMIT 1
        ),
        target_plans AS (
            SELECT
                ep.school_id,
                ep.major_id,
                ep.major_name,
                SUM(ep.plan_count) AS plan_count,
                ARRAY_AGG(DISTINCT ep.major_group_code) FILTER (WHERE ep.major_group_code IS NOT NULL)
                    AS major_group_codes,
                ARRAY_AGG(DISTINCT ep.major_code_raw) FILTER (WHERE ep.major_code_raw IS NOT NULL)
                    AS major_code_raws,
                ARRAY_AGG(DISTINCT ep.selection_requirement) FILTER (WHERE ep.selection_requirement IS NOT NULL)
                    AS selection_requirements,
                BOOL_OR(ep.plan_count IS NOT NULL) AS has_plan_count,
                BOOL_OR(ep.major_group_code IS NOT NULL) AS has_major_group_code,
                BOOL_OR(ep.major_code_raw IS NOT NULL) AS has_major_code_raw,
                BOOL_OR(ep.selection_requirement IS NOT NULL) AS has_selection_requirement
            FROM enrollment_plans ep
            JOIN target_province tp ON tp.id = ep.province_id
            WHERE ep.year = $2
              AND ($4::INTEGER IS NULL OR ep.subject_category_id IS NOT DISTINCT FROM $4)
              AND ($5::TEXT IS NULL OR ep.batch = $5 OR ep.batch_category = $5)
            GROUP BY ep.school_id, ep.major_id, ep.major_name
        ),
        admission_summary AS (
            SELECT
                mar.school_id,
                mar.major_id,
                COUNT(DISTINCT mar.year) FILTER (WHERE mar.min_score IS NOT NULL) AS years_with_min_score,
                COUNT(DISTINCT mar.year) FILTER (WHERE mar.min_rank IS NOT NULL) AS years_with_min_rank,
                MAX(mar.year) FILTER (WHERE mar.min_score IS NOT NULL OR mar.min_rank IS NOT NULL)
                    AS latest_admission_year,
                (ARRAY_AGG(mar.min_score ORDER BY mar.year DESC)
                    FILTER (WHERE mar.min_score IS NOT NULL))[1] AS latest_min_score,
                (ARRAY_AGG(mar.min_rank ORDER BY mar.year DESC)
                    FILTER (WHERE mar.min_rank IS NOT NULL))[1] AS latest_min_rank,
                BOOL_OR(mar.max_score IS NOT NULL) AS has_max_score,
                BOOL_OR(mar.avg_score IS NOT NULL) AS has_avg_score,
                BOOL_OR(mar.admitted_count IS NOT NULL) AS has_admitted_count
            FROM major_admission_results mar
            JOIN target_province tp ON tp.id = mar.province_id
            WHERE mar.year = ANY($3::INTEGER[])
              AND ($4::INTEGER IS NULL OR mar.subject_category_id IS NOT DISTINCT FROM $4)
              AND ($5::TEXT IS NULL OR mar.batch = $5 OR mar.batch_category = $5)
            GROUP BY mar.school_id, mar.major_id
        ),
        strength_summary AS (
            SELECT
                sm.school_id,
                sm.major_id,
                COALESCE(sm.is_featured_major, FALSE)
                    OR sm.major_strength_rank IS NOT NULL
                    OR sm.major_strength_score IS NOT NULL
                    OR COUNT(sms.id) > 0 AS has_strength_evidence
            FROM school_majors sm
            LEFT JOIN school_major_strength_signals sms
              ON sms.school_id = sm.school_id
             AND sms.major_id = sm.major_id
            GROUP BY sm.school_id, sm.major_id, sm.is_featured_major, sm.major_strength_rank, sm.major_strength_score
        ),
        readiness AS (
            SELECT
                tp.code AS province_code,
                tp.name AS province_name,
                $2::INTEGER AS plan_year,
                s.id AS school_id,
                s.name AS school_name,
                tpl.major_id,
                COALESCE(m.name, tpl.major_name) AS major_name,
                tpl.plan_count,
                tpl.major_group_codes,
                tpl.major_code_raws,
                tpl.selection_requirements,
                ads.latest_admission_year,
                ads.latest_min_score,
                ads.latest_min_rank,
                COALESCE(ads.years_with_min_score, 0)::INTEGER AS years_with_min_score,
                COALESCE(ads.years_with_min_rank, 0)::INTEGER AS years_with_min_rank,
                COALESCE(ads.has_max_score, FALSE) AS has_max_score,
                COALESCE(ads.has_avg_score, FALSE) AS has_avg_score,
                COALESCE(ads.has_admitted_count, FALSE) AS has_admitted_count,
                COALESCE(strength.has_strength_evidence, FALSE) AS has_strength_evidence,
                ARRAY_REMOVE(ARRAY[
                    CASE WHEN NOT COALESCE(tpl.has_plan_count, FALSE) THEN 'missing_plan_count' END,
                    CASE WHEN NOT COALESCE(tpl.has_major_group_code, FALSE) THEN 'missing_major_group_code' END,
                    CASE WHEN NOT COALESCE(tpl.has_major_code_raw, FALSE) THEN 'missing_major_code_raw' END,
                    CASE WHEN NOT COALESCE(tpl.has_selection_requirement, FALSE)
                        THEN 'missing_selection_requirement' END,
                    CASE WHEN COALESCE(ads.years_with_min_score, 0) < CARDINALITY($3::INTEGER[])
                        THEN 'missing_admission_min_score' END,
                    CASE WHEN COALESCE(ads.years_with_min_rank, 0) < CARDINALITY($3::INTEGER[])
                        THEN 'missing_admission_min_rank' END,
                    CASE WHEN NOT COALESCE(strength.has_strength_evidence, FALSE)
                        THEN 'missing_strength_evidence' END
                ], NULL) AS readiness_flags
            FROM target_plans tpl
            CROSS JOIN target_province tp
            JOIN schools s ON s.id = tpl.school_id
            LEFT JOIN majors m ON m.id = tpl.major_id
            LEFT JOIN admission_summary ads
              ON ads.school_id = tpl.school_id
             AND ads.major_id IS NOT DISTINCT FROM tpl.major_id
            LEFT JOIN strength_summary strength
              ON strength.school_id = tpl.school_id
             AND strength.major_id IS NOT DISTINCT FROM tpl.major_id
        )
"""

# Static SQL fragments only; user input stays in asyncpg bind parameters.
_MAJOR_ANSWER_READINESS_GAPS_SQL = "".join((
    _MAJOR_ANSWER_READINESS_CTE_SQL,
    """
        SELECT *
        FROM (
            SELECT
                *,
                CARDINALITY(readiness_flags) = 0 AS answer_ready
            FROM readiness
        ) scored_readiness
        WHERE NOT answer_ready
        ORDER BY CARDINALITY(readiness_flags) DESC, school_name, major_name
        LIMIT $6
        """,
))

_MAJOR_ANSWER_READINESS_SUMMARY_SQL = "".join((
    _MAJOR_ANSWER_READINESS_CTE_SQL,
    """
        SELECT
            COUNT(*)::INTEGER AS plan_major_count,
            COUNT(*) FILTER (WHERE CARDINALITY(readiness_flags) = 0)::INTEGER AS answer_ready_count,
            COUNT(*) FILTER (WHERE CARDINALITY(readiness_flags) > 0)::INTEGER AS gap_count,
            COUNT(*) FILTER (WHERE 'missing_plan_count' = ANY(readiness_flags))::INTEGER AS missing_plan_count,
            COUNT(*) FILTER (WHERE 'missing_major_group_code' = ANY(readiness_flags))::INTEGER
                AS missing_major_group_code,
            COUNT(*) FILTER (WHERE 'missing_major_code_raw' = ANY(readiness_flags))::INTEGER
                AS missing_major_code_raw,
            COUNT(*) FILTER (WHERE 'missing_selection_requirement' = ANY(readiness_flags))::INTEGER
                AS missing_selection_requirement,
            COUNT(*) FILTER (WHERE 'missing_admission_min_score' = ANY(readiness_flags))::INTEGER
                AS missing_admission_min_score,
            COUNT(*) FILTER (WHERE 'missing_admission_min_rank' = ANY(readiness_flags))::INTEGER
                AS missing_admission_min_rank,
            COUNT(*) FILTER (WHERE 'missing_strength_evidence' = ANY(readiness_flags))::INTEGER
                AS missing_strength_evidence
        FROM readiness
        """,
))


def normalize_completeness_years(years: Sequence[int] | None, *, today: date | None = None) -> list[int]:
    if not years:
        return default_completeness_years(today=today)

    normalized = sorted({int(year) for year in years})
    if not normalized:
        msg = "At least one year is required."
        raise ValueError(msg)
    return normalized


def default_completeness_years(*, today: date | None = None) -> list[int]:
    anchor = today or date.today()
    latest_year = anchor.year if anchor.month >= CURRENT_YEAR_READY_MONTH else anchor.year - 1
    first_year = latest_year - COMPLETENESS_YEAR_WINDOW + 1
    return list(range(first_year, latest_year + 1))


async def fetch_year_data_coverage(
    conn: asyncpg.Connection,
    *,
    province: str,
    years: Sequence[int],
) -> list[dict]:
    rows = await conn.fetch(
        """
        WITH target_province AS (
            SELECT id, code, name
            FROM provinces
            WHERE code = $1 OR name = $1
            ORDER BY CASE WHEN name = $1 THEN 0 ELSE 1 END
            LIMIT 1
        ),
        target_years AS (
            SELECT UNNEST($2::INTEGER[]) AS year
        ),
        admission_years AS (
            SELECT
                mar.year,
                COUNT(DISTINCT mar.school_id)::INTEGER AS admission_schools,
                COUNT(*)::INTEGER AS admission_records,
                COUNT(*) FILTER (WHERE mar.plan_count IS NOT NULL)::INTEGER
                    AS admission_records_with_plan_count,
                COUNT(*) FILTER (WHERE mar.major_group_code IS NOT NULL)::INTEGER
                    AS admission_records_with_major_group_code,
                COUNT(DISTINCT mar.major_id)::INTEGER AS admission_majors
            FROM major_admission_results mar
            JOIN target_province tp ON tp.id = mar.province_id
            WHERE mar.year = ANY($2::INTEGER[])
            GROUP BY mar.year
        ),
        plan_years AS (
            SELECT
                ep.year,
                COUNT(DISTINCT ep.school_id)::INTEGER AS plan_schools,
                COUNT(*)::INTEGER AS plan_records,
                COUNT(*) FILTER (WHERE ep.plan_count IS NOT NULL)::INTEGER AS plan_records_with_plan_count,
                COUNT(*) FILTER (WHERE ep.major_group_code IS NOT NULL)::INTEGER
                    AS plan_records_with_major_group_code,
                COUNT(*) FILTER (WHERE ep.selection_requirement IS NOT NULL)::INTEGER
                    AS plan_records_with_selection_requirement,
                COALESCE(SUM(ep.plan_count), 0)::INTEGER AS plan_count_sum,
                COUNT(DISTINCT ep.major_id) FILTER (WHERE ep.major_id IS NOT NULL)::INTEGER AS plan_majors
            FROM enrollment_plans ep
            JOIN target_province tp ON tp.id = ep.province_id
            WHERE ep.year = ANY($2::INTEGER[])
            GROUP BY ep.year
        )
        SELECT
            tp.code AS province_code,
            tp.name AS province_name,
            ty.year,
            COALESCE(ay.admission_schools, 0)::INTEGER AS admission_schools,
            COALESCE(ay.admission_records, 0)::INTEGER AS admission_records,
            COALESCE(ay.admission_records_with_plan_count, 0)::INTEGER AS admission_records_with_plan_count,
            COALESCE(ay.admission_records_with_major_group_code, 0)::INTEGER
                AS admission_records_with_major_group_code,
            COALESCE(ay.admission_majors, 0)::INTEGER AS admission_majors,
            COALESCE(py.plan_schools, 0)::INTEGER AS plan_schools,
            COALESCE(py.plan_records, 0)::INTEGER AS plan_records,
            COALESCE(py.plan_records_with_plan_count, 0)::INTEGER AS plan_records_with_plan_count,
            COALESCE(py.plan_records_with_major_group_code, 0)::INTEGER
                AS plan_records_with_major_group_code,
            COALESCE(py.plan_records_with_selection_requirement, 0)::INTEGER
                AS plan_records_with_selection_requirement,
            COALESCE(py.plan_count_sum, 0)::INTEGER AS plan_count_sum,
            COALESCE(py.plan_majors, 0)::INTEGER AS plan_majors,
            GREATEST(COALESCE(ay.admission_schools, 0) - COALESCE(py.plan_schools, 0), 0)::INTEGER
                AS missing_plan_schools
        FROM target_province tp
        CROSS JOIN target_years ty
        LEFT JOIN admission_years ay ON ay.year = ty.year
        LEFT JOIN plan_years py ON py.year = ty.year
        ORDER BY ty.year
        """,
        province,
        list(years),
    )
    return [dict(row) for row in rows]


async def fetch_school_year_plan_gaps(
    conn: asyncpg.Connection,
    *,
    province: str,
    years: Sequence[int],
    limit: int = 50,
) -> list[dict]:
    rows = await conn.fetch(
        """
        WITH target_province AS (
            SELECT id, code, name
            FROM provinces
            WHERE code = $1 OR name = $1
            ORDER BY CASE WHEN name = $1 THEN 0 ELSE 1 END
            LIMIT 1
        ),
        admission_school_years AS (
            SELECT
                mar.school_id,
                mar.year,
                COUNT(*)::INTEGER AS admission_records,
                COUNT(*) FILTER (WHERE mar.plan_count IS NOT NULL)::INTEGER
                    AS admission_records_with_plan_count,
                COUNT(*) FILTER (WHERE mar.major_group_code IS NOT NULL)::INTEGER
                    AS admission_records_with_major_group_code,
                COUNT(DISTINCT mar.major_id)::INTEGER AS admission_majors
            FROM major_admission_results mar
            JOIN target_province tp ON tp.id = mar.province_id
            WHERE mar.year = ANY($2::INTEGER[])
            GROUP BY mar.school_id, mar.year
        ),
        plan_school_years AS (
            SELECT
                ep.school_id,
                ep.year,
                COUNT(*)::INTEGER AS plan_records,
                COUNT(*) FILTER (WHERE ep.plan_count IS NOT NULL)::INTEGER AS plan_records_with_plan_count,
                COUNT(*) FILTER (WHERE ep.major_group_code IS NOT NULL)::INTEGER
                    AS plan_records_with_major_group_code,
                COUNT(*) FILTER (WHERE ep.selection_requirement IS NOT NULL)::INTEGER
                    AS plan_records_with_selection_requirement,
                COALESCE(SUM(ep.plan_count), 0)::INTEGER AS plan_count_sum,
                COUNT(DISTINCT ep.major_id) FILTER (WHERE ep.major_id IS NOT NULL)::INTEGER AS plan_majors
            FROM enrollment_plans ep
            JOIN target_province tp ON tp.id = ep.province_id
            WHERE ep.year = ANY($2::INTEGER[])
            GROUP BY ep.school_id, ep.year
        )
        SELECT
            tp.code AS province_code,
            tp.name AS province_name,
            asy.year,
            s.id AS school_id,
            s.name AS school_name,
            asy.admission_records,
            asy.admission_records_with_plan_count,
            asy.admission_records_with_major_group_code,
            asy.admission_majors,
            COALESCE(ps.plan_records, 0)::INTEGER AS plan_records,
            COALESCE(ps.plan_records_with_plan_count, 0)::INTEGER AS plan_records_with_plan_count,
            COALESCE(ps.plan_records_with_major_group_code, 0)::INTEGER
                AS plan_records_with_major_group_code,
            COALESCE(ps.plan_records_with_selection_requirement, 0)::INTEGER
                AS plan_records_with_selection_requirement,
            COALESCE(ps.plan_count_sum, 0)::INTEGER AS plan_count_sum,
            COALESCE(ps.plan_majors, 0)::INTEGER AS plan_majors
        FROM admission_school_years asy
        JOIN schools s ON s.id = asy.school_id
        CROSS JOIN target_province tp
        LEFT JOIN plan_school_years ps
          ON ps.school_id = asy.school_id
         AND ps.year = asy.year
        WHERE COALESCE(ps.plan_records, 0) = 0
        ORDER BY asy.year DESC, asy.admission_records DESC, s.name
        LIMIT $3
        """,
        province,
        list(years),
        limit,
    )
    return [dict(row) for row in rows]


async def fetch_major_answer_readiness_gaps(
    conn: asyncpg.Connection,
    *,
    province: str,
    plan_year: int,
    admission_years: Sequence[int],
    subject_category_id: int | None = None,
    batch: str | None = None,
    limit: int = 50,
) -> list[dict]:
    rows = await conn.fetch(
        _MAJOR_ANSWER_READINESS_GAPS_SQL,
        province,
        plan_year,
        list(admission_years),
        subject_category_id,
        batch,
        limit,
    )
    return [dict(row) for row in rows]


async def fetch_major_answer_readiness_summary(
    conn: asyncpg.Connection,
    *,
    province: str,
    plan_year: int,
    admission_years: Sequence[int],
    subject_category_id: int | None = None,
    batch: str | None = None,
) -> dict[str, object]:
    rows = await conn.fetch(
        _MAJOR_ANSWER_READINESS_SUMMARY_SQL,
        province,
        plan_year,
        list(admission_years),
        subject_category_id,
        batch,
    )
    if rows:
        return dict(rows[0])

    return {
        "plan_major_count": 0,
        "answer_ready_count": 0,
        "gap_count": 0,
        "missing_plan_count": 0,
        "missing_major_group_code": 0,
        "missing_major_code_raw": 0,
        "missing_selection_requirement": 0,
        "missing_admission_min_score": 0,
        "missing_admission_min_rank": 0,
        "missing_strength_evidence": 0,
    }
