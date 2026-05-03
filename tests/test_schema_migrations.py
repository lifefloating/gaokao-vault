from __future__ import annotations

import re
from pathlib import Path


def test_enrollment_plans_existing_tables_get_conflict_target_index() -> None:
    schema_sql = Path("src/gaokao_vault/db/schema.sql").read_text()

    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_enrollment_plans_unique_key" in schema_sql
    assert "ON enrollment_plans(school_id, province_id, year, subject_category_id, batch, major_name)" in schema_sql
    assert "NULLS NOT DISTINCT" in schema_sql


def test_special_enrollments_existing_tables_get_null_safe_conflict_target_index() -> None:
    schema_sql = Path("src/gaokao_vault/db/schema.sql").read_text()

    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_special_enrollments_unique_key" in schema_sql
    assert "ON special_enrollments(enrollment_type, school_id, year, title)" in schema_sql
    assert "NULLS NOT DISTINCT" in schema_sql


def test_special_enrollments_existing_tables_get_content_text_column() -> None:
    schema_sql = Path("src/gaokao_vault/db/schema.sql").read_text()

    assert "content_text    TEXT" in schema_sql
    assert "ALTER TABLE special_enrollments ADD COLUMN IF NOT EXISTS content_text TEXT" in schema_sql


def test_volunteer_timelines_batch_accepts_long_source_labels() -> None:
    schema_sql = Path("src/gaokao_vault/db/schema.sql").read_text()

    assert re.search(
        r"CREATE TABLE IF NOT EXISTS volunteer_timelines \(.+?batch\s+VARCHAR\(255\) NOT NULL",
        schema_sql,
        re.S,
    )
    assert "ALTER TABLE volunteer_timelines ALTER COLUMN batch TYPE VARCHAR(255)" in schema_sql
