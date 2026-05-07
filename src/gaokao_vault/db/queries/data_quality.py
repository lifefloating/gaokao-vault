from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import asyncpg

COMPLETENESS_YEAR_WINDOW = 3
CURRENT_YEAR_READY_MONTH = 12

_MAJOR_NAME_NORMALIZATION_PATTERN_SQL = "CONCAT('[', CHR(65288), '(].*[', CHR(65289), ')]|\\s+|专业|类')"


def _normalized_major_name_sql(value_sql: str) -> str:
    return f"LOWER(REGEXP_REPLACE({value_sql}, {_MAJOR_NAME_NORMALIZATION_PATTERN_SQL}, '', 'g'))"


_NORMALIZED_PLAN_MAJOR_NAME_SQL = _normalized_major_name_sql("COALESCE(plan_major.name, ep.major_name, '')")
_NORMALIZED_ADMISSION_MAJOR_NAME_SQL = _normalized_major_name_sql("COALESCE(mar.major_name_raw, adm_major.name, '')")

_PLAN_MAJOR_NAME_PLACEHOLDER = "__NORMALIZED_PLAN_MAJOR_NAME_SQL__"
_ADMISSION_MAJOR_NAME_PLACEHOLDER = "__NORMALIZED_ADMISSION_MAJOR_NAME_SQL__"

_MAJOR_ANSWER_READINESS_CTE_SQL_TEMPLATE = """
        WITH target_province AS (
            SELECT id, code, name
            FROM provinces
            WHERE code = $1 OR name = $1
            ORDER BY CASE WHEN name = $1 THEN 0 ELSE 1 END
            LIMIT 1
        ),
        target_plans AS (
            SELECT
                ep.id AS enrollment_plan_id,
                ep.school_id,
                ep.major_id,
                COALESCE(plan_major.name, ep.major_name) AS major_name,
                __NORMALIZED_PLAN_MAJOR_NAME_SQL__ AS normalized_major_name,
                ep.plan_count,
                ARRAY_REMOVE(ARRAY[ep.major_group_code], NULL::VARCHAR) AS major_group_codes,
                ARRAY_REMOVE(ARRAY[ep.major_code_raw], NULL::VARCHAR) AS major_code_raws,
                ARRAY_REMOVE(ARRAY[ep.selection_requirement], NULL::VARCHAR) AS selection_requirements,
                ep.plan_count IS NOT NULL AS has_plan_count,
                ep.major_group_code IS NOT NULL AS has_major_group_code,
                ep.major_code_raw IS NOT NULL AS has_major_code_raw,
                ep.selection_requirement IS NOT NULL AS has_selection_requirement
            FROM enrollment_plans ep
            JOIN target_province tp ON tp.id = ep.province_id
            LEFT JOIN majors plan_major ON plan_major.id = ep.major_id
            WHERE ep.year = $2
              AND ($4::INTEGER IS NULL OR ep.subject_category_id IS NOT DISTINCT FROM $4)
              AND ($5::TEXT IS NULL OR ep.batch = $5 OR ep.batch_category = $5)
        ),
        admission_by_major_id AS (
            SELECT
                mar.school_id,
                mar.major_id,
                COUNT(DISTINCT mar.year) FILTER (WHERE mar.min_score IS NOT NULL) AS years_with_min_score,
                COUNT(DISTINCT mar.year) FILTER (WHERE mar.min_rank IS NOT NULL) AS years_with_min_rank,
                MAX(mar.year) FILTER (WHERE mar.min_score IS NOT NULL) AS latest_min_score_year,
                (ARRAY_AGG(mar.min_score ORDER BY mar.year DESC)
                    FILTER (WHERE mar.min_score IS NOT NULL))[1] AS latest_min_score,
                MAX(mar.year) FILTER (WHERE mar.min_rank IS NOT NULL) AS latest_min_rank_year,
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
        admission_by_normalized_name AS (
            SELECT
                mar.school_id,
                __NORMALIZED_ADMISSION_MAJOR_NAME_SQL__ AS normalized_major_name,
                COUNT(DISTINCT mar.year) FILTER (WHERE mar.min_score IS NOT NULL) AS years_with_min_score,
                COUNT(DISTINCT mar.year) FILTER (WHERE mar.min_rank IS NOT NULL) AS years_with_min_rank,
                MAX(mar.year) FILTER (WHERE mar.min_score IS NOT NULL) AS latest_min_score_year,
                (ARRAY_AGG(mar.min_score ORDER BY mar.year DESC)
                    FILTER (WHERE mar.min_score IS NOT NULL))[1] AS latest_min_score,
                MAX(mar.year) FILTER (WHERE mar.min_rank IS NOT NULL) AS latest_min_rank_year,
                (ARRAY_AGG(mar.min_rank ORDER BY mar.year DESC)
                    FILTER (WHERE mar.min_rank IS NOT NULL))[1] AS latest_min_rank,
                BOOL_OR(mar.max_score IS NOT NULL) AS has_max_score,
                BOOL_OR(mar.avg_score IS NOT NULL) AS has_avg_score,
                BOOL_OR(mar.admitted_count IS NOT NULL) AS has_admitted_count
            FROM major_admission_results mar
            JOIN target_province tp ON tp.id = mar.province_id
            LEFT JOIN majors adm_major ON adm_major.id = mar.major_id
            WHERE mar.year = ANY($3::INTEGER[])
              AND ($4::INTEGER IS NULL OR mar.subject_category_id IS NOT DISTINCT FROM $4)
              AND ($5::TEXT IS NULL OR mar.batch = $5 OR mar.batch_category = $5)
            GROUP BY
                mar.school_id,
                __NORMALIZED_ADMISSION_MAJOR_NAME_SQL__
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
                tpl.enrollment_plan_id,
                tpl.major_id,
                COALESCE(m.name, tpl.major_name) AS major_name,
                tpl.plan_count,
                tpl.major_group_codes,
                tpl.major_code_raws,
                tpl.selection_requirements,
                CASE
                    WHEN ads_exact.school_id IS NOT NULL THEN 'major_id'
                    WHEN ads_name.school_id IS NOT NULL THEN 'normalized_name'
                    ELSE NULL
                END AS admission_match_type,
                CASE
                    WHEN ads_exact.school_id IS NOT NULL THEN ads_exact.latest_min_score_year
                    ELSE ads_name.latest_min_score_year
                END AS latest_min_score_year,
                CASE
                    WHEN ads_exact.school_id IS NOT NULL THEN ads_exact.latest_min_score
                    ELSE ads_name.latest_min_score
                END AS latest_min_score,
                CASE
                    WHEN ads_exact.school_id IS NOT NULL THEN ads_exact.latest_min_rank_year
                    ELSE ads_name.latest_min_rank_year
                END AS latest_min_rank_year,
                CASE
                    WHEN ads_exact.school_id IS NOT NULL THEN ads_exact.latest_min_rank
                    ELSE ads_name.latest_min_rank
                END AS latest_min_rank,
                CASE
                    WHEN ads_exact.school_id IS NOT NULL THEN COALESCE(ads_exact.years_with_min_score, 0)
                    ELSE COALESCE(ads_name.years_with_min_score, 0)
                END::INTEGER AS years_with_min_score,
                CASE
                    WHEN ads_exact.school_id IS NOT NULL THEN COALESCE(ads_exact.years_with_min_rank, 0)
                    ELSE COALESCE(ads_name.years_with_min_rank, 0)
                END::INTEGER AS years_with_min_rank,
                CASE
                    WHEN ads_exact.school_id IS NOT NULL THEN COALESCE(ads_exact.has_max_score, FALSE)
                    ELSE COALESCE(ads_name.has_max_score, FALSE)
                END AS has_max_score,
                CASE
                    WHEN ads_exact.school_id IS NOT NULL THEN COALESCE(ads_exact.has_avg_score, FALSE)
                    ELSE COALESCE(ads_name.has_avg_score, FALSE)
                END AS has_avg_score,
                CASE
                    WHEN ads_exact.school_id IS NOT NULL THEN COALESCE(ads_exact.has_admitted_count, FALSE)
                    ELSE COALESCE(ads_name.has_admitted_count, FALSE)
                END AS has_admitted_count,
                COALESCE(strength.has_strength_evidence, FALSE) AS has_strength_evidence,
                ARRAY_REMOVE(ARRAY[
                    CASE WHEN NOT COALESCE(tpl.has_plan_count, FALSE) THEN 'missing_plan_count' END,
                    CASE WHEN NOT COALESCE(tpl.has_major_group_code, FALSE) THEN 'missing_major_group_code' END,
                    CASE WHEN NOT COALESCE(tpl.has_major_code_raw, FALSE) THEN 'missing_major_code_raw' END,
                    CASE WHEN NOT COALESCE(tpl.has_selection_requirement, FALSE)
                        THEN 'missing_selection_requirement' END,
                    CASE WHEN ads_exact.school_id IS NULL THEN 'missing_admission_linkage' END,
                    CASE
                        WHEN (
                            CASE
                                WHEN ads_exact.school_id IS NOT NULL THEN COALESCE(ads_exact.years_with_min_score, 0)
                                ELSE COALESCE(ads_name.years_with_min_score, 0)
                            END
                        ) < CARDINALITY($3::INTEGER[]) THEN 'missing_admission_min_score'
                    END,
                    CASE
                        WHEN (
                            CASE
                                WHEN ads_exact.school_id IS NOT NULL THEN COALESCE(ads_exact.years_with_min_rank, 0)
                                ELSE COALESCE(ads_name.years_with_min_rank, 0)
                            END
                        ) < CARDINALITY($3::INTEGER[]) THEN 'missing_admission_min_rank'
                    END,
                    CASE WHEN NOT COALESCE(strength.has_strength_evidence, FALSE)
                        THEN 'missing_strength_evidence' END
                ], NULL) AS readiness_flags
            FROM target_plans tpl
            CROSS JOIN target_province tp
            JOIN schools s ON s.id = tpl.school_id
            LEFT JOIN majors m ON m.id = tpl.major_id
            LEFT JOIN admission_by_major_id ads_exact
              ON ads_exact.school_id = tpl.school_id
             AND ads_exact.major_id IS NOT DISTINCT FROM tpl.major_id
            LEFT JOIN admission_by_normalized_name ads_name
              ON ads_name.school_id = tpl.school_id
             AND ads_name.normalized_major_name = tpl.normalized_major_name
             AND tpl.normalized_major_name <> ''
            LEFT JOIN strength_summary strength
              ON strength.school_id = tpl.school_id
             AND strength.major_id IS NOT DISTINCT FROM tpl.major_id
        )
"""
_MAJOR_ANSWER_READINESS_CTE_SQL = _MAJOR_ANSWER_READINESS_CTE_SQL_TEMPLATE.replace(
    _PLAN_MAJOR_NAME_PLACEHOLDER, _NORMALIZED_PLAN_MAJOR_NAME_SQL
).replace(_ADMISSION_MAJOR_NAME_PLACEHOLDER, _NORMALIZED_ADMISSION_MAJOR_NAME_SQL)

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
            COUNT(*) FILTER (WHERE 'missing_admission_linkage' = ANY(readiness_flags))::INTEGER
                AS missing_admission_linkage,
            COUNT(*) FILTER (WHERE 'missing_strength_evidence' = ANY(readiness_flags))::INTEGER
                AS missing_strength_evidence
        FROM readiness
        """,
))

_MAJOR_ANSWER_READINESS_MATCH_DIAGNOSTICS_SQL_TEMPLATE = """
        WITH target_province AS (
            SELECT id, code, name
            FROM provinces
            WHERE code = $1 OR name = $1
            ORDER BY CASE WHEN name = $1 THEN 0 ELSE 1 END
            LIMIT 1
        ),
        target_plans AS (
            SELECT DISTINCT
                ep.school_id,
                ep.major_id,
                COALESCE(plan_major.name, ep.major_name) AS major_name,
                __NORMALIZED_PLAN_MAJOR_NAME_SQL__ AS normalized_major_name
            FROM enrollment_plans ep
            JOIN target_province tp ON tp.id = ep.province_id
            LEFT JOIN majors plan_major ON plan_major.id = ep.major_id
            WHERE ep.year = $2
              AND ($4::INTEGER IS NULL OR ep.subject_category_id IS NOT DISTINCT FROM $4)
              AND ($5::TEXT IS NULL OR ep.batch = $5 OR ep.batch_category = $5)
        ),
        admission_records AS (
            SELECT
                mar.school_id,
                mar.major_id,
                COALESCE(mar.major_name_raw, adm_major.name) AS major_name,
                __NORMALIZED_ADMISSION_MAJOR_NAME_SQL__ AS normalized_major_name,
                mar.min_score IS NOT NULL AS has_min_score,
                mar.min_rank IS NOT NULL AS has_min_rank
            FROM major_admission_results mar
            JOIN target_province tp ON tp.id = mar.province_id
            LEFT JOIN majors adm_major ON adm_major.id = mar.major_id
            WHERE mar.year = ANY($3::INTEGER[])
              AND ($4::INTEGER IS NULL OR mar.subject_category_id IS NOT DISTINCT FROM $4)
              AND ($5::TEXT IS NULL OR mar.batch = $5 OR mar.batch_category = $5)
        ),
        exact_matches AS (
            SELECT
                tpl.school_id,
                tpl.major_id,
                tpl.major_name,
                BOOL_OR(adm.has_min_score) AS has_min_score,
                BOOL_OR(adm.has_min_rank) AS has_min_rank
            FROM target_plans tpl
            JOIN admission_records adm
              ON adm.school_id = tpl.school_id
             AND adm.major_id IS NOT DISTINCT FROM tpl.major_id
            GROUP BY tpl.school_id, tpl.major_id, tpl.major_name
        ),
        normalized_name_matches AS (
            SELECT
                tpl.school_id,
                tpl.major_id,
                tpl.major_name,
                BOOL_OR(adm.has_min_score) AS has_min_score,
                BOOL_OR(adm.has_min_rank) AS has_min_rank
            FROM target_plans tpl
            JOIN admission_records adm
              ON adm.school_id = tpl.school_id
             AND adm.normalized_major_name = tpl.normalized_major_name
            WHERE tpl.normalized_major_name <> ''
            GROUP BY tpl.school_id, tpl.major_id, tpl.major_name
        )
        SELECT
            COUNT(*)::INTEGER AS plan_major_count,
            COUNT(*) FILTER (WHERE tpl.major_id IS NOT NULL)::INTEGER AS plan_major_with_major_id_count,
            COUNT(exact_matches.*)::INTEGER AS exact_major_id_match_count,
            COUNT(exact_matches.*) FILTER (WHERE exact_matches.has_min_score)::INTEGER
                AS exact_major_id_match_with_min_score_count,
            COUNT(exact_matches.*) FILTER (WHERE exact_matches.has_min_rank)::INTEGER
                AS exact_major_id_match_with_min_rank_count,
            COUNT(normalized_name_matches.*)::INTEGER AS normalized_name_match_count,
            COUNT(normalized_name_matches.*) FILTER (WHERE normalized_name_matches.has_min_score)::INTEGER
                AS normalized_name_match_with_min_score_count,
            COUNT(normalized_name_matches.*) FILTER (WHERE normalized_name_matches.has_min_rank)::INTEGER
                AS normalized_name_match_with_min_rank_count,
            COUNT(normalized_name_matches.*) FILTER (WHERE exact_matches.school_id IS NULL)::INTEGER
                AS normalized_name_only_match_count,
            COUNT(normalized_name_matches.*) FILTER (
                WHERE exact_matches.school_id IS NULL
                  AND normalized_name_matches.has_min_score
            )::INTEGER AS normalized_name_only_match_with_min_score_count,
            COUNT(normalized_name_matches.*) FILTER (
                WHERE exact_matches.school_id IS NULL
                  AND normalized_name_matches.has_min_rank
            )::INTEGER AS normalized_name_only_match_with_min_rank_count,
            COUNT(*) FILTER (
                WHERE exact_matches.school_id IS NULL
                  AND normalized_name_matches.school_id IS NULL
            )::INTEGER AS unmatched_plan_major_count
        FROM target_plans tpl
        LEFT JOIN exact_matches
          ON exact_matches.school_id = tpl.school_id
         AND exact_matches.major_id IS NOT DISTINCT FROM tpl.major_id
         AND exact_matches.major_name IS NOT DISTINCT FROM tpl.major_name
        LEFT JOIN normalized_name_matches
          ON normalized_name_matches.school_id = tpl.school_id
         AND normalized_name_matches.major_id IS NOT DISTINCT FROM tpl.major_id
         AND normalized_name_matches.major_name IS NOT DISTINCT FROM tpl.major_name
        """
_MAJOR_ANSWER_READINESS_MATCH_DIAGNOSTICS_SQL = _MAJOR_ANSWER_READINESS_MATCH_DIAGNOSTICS_SQL_TEMPLATE.replace(
    _PLAN_MAJOR_NAME_PLACEHOLDER,
    _NORMALIZED_PLAN_MAJOR_NAME_SQL,
).replace(_ADMISSION_MAJOR_NAME_PLACEHOLDER, _NORMALIZED_ADMISSION_MAJOR_NAME_SQL)

_MAJOR_STRENGTH_SIGNAL_DIAGNOSTICS_SQL = """
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
                COALESCE(plan_major.name, ep.major_name) AS major_name
            FROM enrollment_plans ep
            JOIN target_province tp ON tp.id = ep.province_id
            LEFT JOIN majors plan_major ON plan_major.id = ep.major_id
            WHERE ep.year = $2
              AND ($3::INTEGER IS NULL OR ep.subject_category_id IS NOT DISTINCT FROM $3)
              AND ($4::TEXT IS NULL OR ep.batch = $4 OR ep.batch_category = $4)
            GROUP BY ep.school_id, ep.major_id, COALESCE(plan_major.name, ep.major_name)
        ),
        signal_plan_majors AS (
            SELECT DISTINCT
                tpl.school_id,
                tpl.major_id,
                tpl.major_name
            FROM target_plans tpl
            JOIN school_major_strength_signals sms
              ON sms.school_id = tpl.school_id
             AND sms.major_id IS NOT DISTINCT FROM tpl.major_id
        ),
        rollup_plan_majors AS (
            SELECT DISTINCT
                tpl.school_id,
                tpl.major_id,
                tpl.major_name
            FROM target_plans tpl
            JOIN school_majors sm
              ON sm.school_id = tpl.school_id
             AND sm.major_id IS NOT DISTINCT FROM tpl.major_id
            WHERE sm.major_strength_rank IS NOT NULL
               OR sm.major_strength_score IS NOT NULL
               OR sm.is_featured_major
               OR sm.strength_evidence <> '[]'::jsonb
        )
        SELECT
            COUNT(*)::INTEGER AS plan_major_count,
            COUNT(sm.*)::INTEGER AS plan_major_with_school_major_count,
            COUNT(signal_plan_majors.*)::INTEGER AS plan_major_with_strength_signal_count,
            COUNT(rollup_plan_majors.*)::INTEGER AS plan_major_with_strength_rollup_count,
            COUNT(signal_plan_majors.*) FILTER (WHERE rollup_plan_majors.school_id IS NULL)::INTEGER
                AS plan_major_signal_without_rollup_count
        FROM target_plans tpl
        LEFT JOIN school_majors sm
          ON sm.school_id = tpl.school_id
         AND sm.major_id IS NOT DISTINCT FROM tpl.major_id
        LEFT JOIN signal_plan_majors
          ON signal_plan_majors.school_id = tpl.school_id
         AND signal_plan_majors.major_id IS NOT DISTINCT FROM tpl.major_id
         AND signal_plan_majors.major_name IS NOT DISTINCT FROM tpl.major_name
        LEFT JOIN rollup_plan_majors
          ON rollup_plan_majors.school_id = tpl.school_id
         AND rollup_plan_majors.major_id IS NOT DISTINCT FROM tpl.major_id
         AND rollup_plan_majors.major_name IS NOT DISTINCT FROM tpl.major_name
        """


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
        "missing_admission_linkage": 0,
        "missing_strength_evidence": 0,
    }


async def fetch_major_answer_readiness_match_diagnostics(
    conn: asyncpg.Connection,
    *,
    province: str,
    plan_year: int,
    admission_years: Sequence[int],
    subject_category_id: int | None = None,
    batch: str | None = None,
) -> dict[str, object]:
    rows = await conn.fetch(
        _MAJOR_ANSWER_READINESS_MATCH_DIAGNOSTICS_SQL,
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
        "plan_major_with_major_id_count": 0,
        "exact_major_id_match_count": 0,
        "exact_major_id_match_with_min_score_count": 0,
        "exact_major_id_match_with_min_rank_count": 0,
        "normalized_name_match_count": 0,
        "normalized_name_match_with_min_score_count": 0,
        "normalized_name_match_with_min_rank_count": 0,
        "normalized_name_only_match_count": 0,
        "normalized_name_only_match_with_min_score_count": 0,
        "normalized_name_only_match_with_min_rank_count": 0,
        "unmatched_plan_major_count": 0,
    }


async def fetch_major_strength_signal_diagnostics(
    conn: asyncpg.Connection,
    *,
    province: str,
    plan_year: int,
    subject_category_id: int | None = None,
    batch: str | None = None,
) -> dict[str, object]:
    rows = await conn.fetch(
        _MAJOR_STRENGTH_SIGNAL_DIAGNOSTICS_SQL,
        province,
        plan_year,
        subject_category_id,
        batch,
    )
    if rows:
        return dict(rows[0])

    return {
        "plan_major_count": 0,
        "plan_major_with_school_major_count": 0,
        "plan_major_with_strength_signal_count": 0,
        "plan_major_with_strength_rollup_count": 0,
        "plan_major_signal_without_rollup_count": 0,
    }
