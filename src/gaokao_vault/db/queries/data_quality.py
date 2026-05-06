from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import asyncpg

COMPLETENESS_YEAR_WINDOW = 3
CURRENT_YEAR_READY_MONTH = 12


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
