from __future__ import annotations

import re
from pathlib import Path


def _normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def test_enrollment_plans_existing_tables_get_conflict_target_index() -> None:
    schema_sql = Path("src/gaokao_vault/db/schema.sql").read_text()

    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_enrollment_plans_unique_key" in schema_sql
    assert "ON enrollment_plans(school_id, province_id, year, subject_category_id, batch, major_name)" in schema_sql
    assert "NULLS NOT DISTINCT" in schema_sql


def test_school_majors_existing_tables_get_school_major_strength_columns() -> None:
    schema_sql = Path("src/gaokao_vault/db/schema.sql").read_text()

    assert "school_major_display_order INTEGER" in schema_sql
    assert "major_strength_rank INTEGER" in schema_sql
    assert "major_strength_score NUMERIC(6,2)" in schema_sql
    assert "major_strength_tier VARCHAR(50)" in schema_sql
    assert "is_featured_major BOOLEAN NOT NULL DEFAULT FALSE" in schema_sql
    assert "strength_evidence JSONB NOT NULL DEFAULT '[]'::jsonb" in schema_sql
    assert "ALTER TABLE school_majors ADD COLUMN IF NOT EXISTS school_major_display_order INTEGER" in schema_sql
    assert "ALTER TABLE school_majors ADD COLUMN IF NOT EXISTS major_strength_rank INTEGER" in schema_sql
    assert "ALTER TABLE school_majors ADD COLUMN IF NOT EXISTS major_strength_score NUMERIC(6,2)" in schema_sql
    assert "ALTER TABLE school_majors ADD COLUMN IF NOT EXISTS major_strength_tier VARCHAR(50)" in schema_sql
    assert (
        "ALTER TABLE school_majors ADD COLUMN IF NOT EXISTS is_featured_major BOOLEAN NOT NULL DEFAULT FALSE"
        in schema_sql
    )
    assert (
        "ALTER TABLE school_majors ADD COLUMN IF NOT EXISTS strength_evidence JSONB NOT NULL DEFAULT '[]'::jsonb"
        in schema_sql
    )
    assert (
        "UPDATE school_majors\n"
        "SET major_strength_rank = NULL,\n"
        "    major_strength_score = NULL,\n"
        "    major_strength_tier = NULL,\n"
        "    is_featured_major = FALSE,\n"
        "    strength_evidence = '[]'::jsonb\n"
        "WHERE NOT EXISTS ("
    ) in schema_sql


def test_school_majors_strength_index_is_created_after_existing_table_columns_are_added() -> None:
    schema_sql = _normalize_sql(Path("src/gaokao_vault/db/schema.sql").read_text())

    featured_index_sql = (
        "CREATE INDEX IF NOT EXISTS idx_school_majors_featured "
        "ON school_majors(school_id, is_featured_major, major_strength_rank, major_strength_score DESC)"
    )
    column_statements = (
        "ALTER TABLE school_majors ADD COLUMN IF NOT EXISTS school_major_display_order INTEGER",
        "ALTER TABLE school_majors ADD COLUMN IF NOT EXISTS major_strength_rank INTEGER",
        "ALTER TABLE school_majors ADD COLUMN IF NOT EXISTS major_strength_score NUMERIC(6,2)",
        "ALTER TABLE school_majors ADD COLUMN IF NOT EXISTS major_strength_tier VARCHAR(50)",
        "ALTER TABLE school_majors ADD COLUMN IF NOT EXISTS is_featured_major BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE school_majors ADD COLUMN IF NOT EXISTS strength_evidence JSONB NOT NULL DEFAULT '[]'::jsonb",
    )

    assert featured_index_sql in schema_sql
    for column_sql in column_statements:
        assert column_sql in schema_sql

    featured_index_position = schema_sql.find(featured_index_sql)
    for column_sql in column_statements:
        assert schema_sql.find(column_sql) < featured_index_position


def test_school_major_strength_signals_table_is_declared() -> None:
    schema_sql = Path("src/gaokao_vault/db/schema.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS school_major_strength_signals" in schema_sql
    assert "signal_type     VARCHAR(50) NOT NULL" in schema_sql
    assert "signal_level    VARCHAR(50)" in schema_sql
    assert "strength_score  NUMERIC(6,2) NOT NULL" in schema_sql
    assert "source_url      VARCHAR(255)" in schema_sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_school_major_strength_signals_unique_key" in schema_sql


def test_major_admission_results_tracks_min_rank_source() -> None:
    schema_sql = Path("src/gaokao_vault/db/schema.sql").read_text()

    for column_sql in (
        "min_rank_source VARCHAR(50)",
        "min_rank_is_derived BOOLEAN NOT NULL DEFAULT FALSE",
    ):
        assert column_sql in schema_sql
        assert f"ALTER TABLE major_admission_results ADD COLUMN IF NOT EXISTS {column_sql}" in schema_sql

    assert "mar.min_rank_source" in schema_sql
    assert "mar.min_rank_is_derived" in schema_sql


def test_special_enrollments_existing_tables_get_null_safe_conflict_target_index() -> None:
    schema_sql = Path("src/gaokao_vault/db/schema.sql").read_text()

    assert "DROP INDEX IF EXISTS idx_special_enrollments_unique_key" in schema_sql
    assert "CREATE UNIQUE INDEX idx_special_enrollments_unique_key" in schema_sql
    assert (
        "ON special_enrollments(enrollment_type, school_id, school_code_raw, year, title, source_section, detail_url)"
        in (schema_sql)
    )
    assert "NULLS NOT DISTINCT" in schema_sql


def test_special_enrollments_existing_tables_get_content_text_column() -> None:
    schema_sql = Path("src/gaokao_vault/db/schema.sql").read_text()

    assert "content_text    TEXT" in schema_sql
    assert "ALTER TABLE special_enrollments ADD COLUMN IF NOT EXISTS content_text TEXT" in schema_sql


def test_special_enrollments_existing_tables_get_chsi_strong_base_lineage_columns() -> None:
    schema_sql = Path("src/gaokao_vault/db/schema.sql").read_text()

    for column_sql in (
        "school_code_raw VARCHAR(50)",
        "school_name_raw VARCHAR(200)",
        "source_section VARCHAR(50)",
        "detail_url VARCHAR(255)",
        "milestones JSONB NOT NULL DEFAULT '{}'::jsonb",
    ):
        assert column_sql in schema_sql
        assert f"ALTER TABLE special_enrollments ADD COLUMN IF NOT EXISTS {column_sql}" in schema_sql


def test_volunteer_timelines_batch_accepts_long_source_labels() -> None:
    schema_sql = Path("src/gaokao_vault/db/schema.sql").read_text()

    assert re.search(
        r"CREATE TABLE IF NOT EXISTS volunteer_timelines \(.+?batch\s+VARCHAR\(255\) NOT NULL",
        schema_sql,
        re.S,
    )
    assert "ALTER TABLE volunteer_timelines ALTER COLUMN batch TYPE VARCHAR(255)" in schema_sql


def test_source_lineage_tables_are_declared() -> None:
    schema_sql = Path("src/gaokao_vault/db/schema.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS data_sources" in schema_sql
    assert "CREATE TABLE IF NOT EXISTS source_documents" in schema_sql
    assert "CREATE TABLE IF NOT EXISTS entity_evidence" in schema_sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_data_sources_code" in schema_sql
    assert "DROP INDEX IF EXISTS idx_source_documents_source_url_hash" in schema_sql
    assert "CREATE UNIQUE INDEX idx_source_documents_source_url_hash" in schema_sql
    assert "ON source_documents(data_source_id, source_url, content_hash)" in schema_sql
    assert "CREATE INDEX IF NOT EXISTS idx_source_documents_data_source" in schema_sql
    assert "CREATE INDEX IF NOT EXISTS idx_entity_evidence_entity" in schema_sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_evidence_unique_key" in schema_sql
    assert "CREATE INDEX IF NOT EXISTS idx_entity_evidence_source_document" in schema_sql
    assert "CHECK (authority_level BETWEEN 0 AND 100)" in schema_sql


def test_vector_documents_view_is_declared() -> None:
    schema_sql = Path("src/gaokao_vault/db/schema.sql").read_text()

    assert "CREATE OR REPLACE VIEW gaokao_source.vector_documents_v AS" in schema_sql
    assert "CREATE OR REPLACE VIEW gaokao_source.vector_documents_source_v AS" in schema_sql
    assert "DROP VIEW IF EXISTS gaokao_source.vector_documents_v" in schema_sql
    assert "FROM gaokao_source.special_enrollments_v" in schema_sql
    assert "document_uid" in schema_sql
    assert "authority_level" in schema_sql
    assert "metadata" in schema_sql
    assert "COALESCE(sd.title, sd.source_url)::TEXT AS text" not in schema_sql
    assert "COALESCE(NULLIF(sd.title, ''), '')::TEXT AS text" in schema_sql
    assert "CONCAT_WS('\\n', NULLIF(se.title, ''), NULLIF(se.content_text, ''))::TEXT AS text" in schema_sql
    assert "regexp_replace(sd.source_url, '[?#].*$', '')::TEXT AS source_url" in schema_sql
    assert "'source_section', se.source_section" in schema_sql
    assert "'detail_url', se.detail_url" in schema_sql
    assert "'milestones', se.milestones" in schema_sql


def test_admission_records_view_is_dropped_before_recreate_to_allow_column_order_changes() -> None:
    schema_sql = _normalize_sql(Path("src/gaokao_vault/db/schema.sql").read_text())
    drop_view_sql = "DROP VIEW IF EXISTS gaokao_source.admission_records_v"
    create_view_sql = "CREATE OR REPLACE VIEW gaokao_source.admission_records_v AS"

    assert drop_view_sql in schema_sql
    assert create_view_sql in schema_sql
    assert schema_sql.count(drop_view_sql) == 1
    assert schema_sql.count(create_view_sql) == 1
    assert schema_sql.find(drop_view_sql) < schema_sql.find(create_view_sql)


def test_admission_records_view_appends_min_rank_provenance_to_preserve_existing_column_order() -> None:
    schema_sql = _normalize_sql(Path("src/gaokao_vault/db/schema.sql").read_text())

    assert "mar.min_rank, mar.plan_count" in schema_sql
    assert "NULL::INTEGER AS min_rank, ep.plan_count" in schema_sql
    assert "mar.min_rank_source, mar.min_rank_is_derived" in schema_sql
    assert "NULL::TEXT AS min_rank_source, FALSE AS min_rank_is_derived" in schema_sql
    assert schema_sql.find("mar.min_rank, mar.plan_count") < schema_sql.find(
        "mar.min_rank_source, mar.min_rank_is_derived"
    )
