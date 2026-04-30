-- =============================================================
-- Gaokao Vault — Full DDL
-- =============================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- -----------------------------------------------------------
-- 1. Crawl metadata
-- -----------------------------------------------------------

CREATE TABLE IF NOT EXISTS crawl_tasks (
    id              BIGSERIAL PRIMARY KEY,
    task_type       VARCHAR(50) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    total_items     INTEGER DEFAULT 0,
    new_items       INTEGER DEFAULT 0,
    updated_items   INTEGER DEFAULT 0,
    unchanged_items INTEGER DEFAULT 0,
    failed_items    INTEGER DEFAULT 0,
    error_message   TEXT,
    params          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crawl_tasks_type_status ON crawl_tasks(task_type, status);
CREATE INDEX IF NOT EXISTS idx_crawl_tasks_created ON crawl_tasks(created_at DESC);

CREATE TABLE IF NOT EXISTS crawl_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    crawl_task_id   BIGINT NOT NULL REFERENCES crawl_tasks(id),
    entity_type     VARCHAR(50) NOT NULL,
    entity_id       BIGINT NOT NULL,
    content_hash    VARCHAR(64) NOT NULL,
    change_type     VARCHAR(10) NOT NULL,
    previous_hash   VARCHAR(64),
    snapshot_data   JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_snapshots_entity ON crawl_snapshots(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_task ON crawl_snapshots(crawl_task_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_hash ON crawl_snapshots(entity_type, entity_id, content_hash);

-- -----------------------------------------------------------
-- 2. Dimension tables
-- -----------------------------------------------------------

CREATE TABLE IF NOT EXISTS provinces (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(20) NOT NULL UNIQUE,
    code            VARCHAR(10),
    region          VARCHAR(10),
    gaokao_mode     VARCHAR(20),
    gaokao_mode_year INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subject_categories (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(20) NOT NULL UNIQUE,
    category_type   VARCHAR(20) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------
-- 3. School tables
-- -----------------------------------------------------------

CREATE TABLE IF NOT EXISTS schools (
    id              BIGSERIAL PRIMARY KEY,
    sch_id          INTEGER UNIQUE NOT NULL,
    name            VARCHAR(100) NOT NULL,
    province_id     INTEGER REFERENCES provinces(id),
    city            VARCHAR(50),
    authority       VARCHAR(100),
    level           VARCHAR(20),
    is_211          BOOLEAN DEFAULT FALSE,
    is_985          BOOLEAN DEFAULT FALSE,
    is_double_first BOOLEAN DEFAULT FALSE,
    is_private      BOOLEAN DEFAULT FALSE,
    is_independent  BOOLEAN DEFAULT FALSE,
    is_sino_foreign BOOLEAN DEFAULT FALSE,
    school_type     VARCHAR(30),
    website         VARCHAR(255),
    phone           VARCHAR(100),
    email           VARCHAR(100),
    address         VARCHAR(255),
    introduction    TEXT,
    logo_url        VARCHAR(255),
    content_hash    VARCHAR(64),
    crawl_task_id   BIGINT REFERENCES crawl_tasks(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_schools_province ON schools(province_id);
CREATE INDEX IF NOT EXISTS idx_schools_level ON schools(level);
CREATE INDEX IF NOT EXISTS idx_schools_name ON schools USING gin(name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_schools_features ON schools(is_double_first, is_985, is_211);

DROP TRIGGER IF EXISTS update_schools_updated_at ON schools;
CREATE TRIGGER update_schools_updated_at BEFORE UPDATE ON schools
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS school_satisfaction (
    id              BIGSERIAL PRIMARY KEY,
    school_id       BIGINT NOT NULL REFERENCES schools(id),
    year            SMALLINT,
    overall_score   NUMERIC(3,1),
    environment_score NUMERIC(3,1),
    life_score      NUMERIC(3,1),
    vote_count      INTEGER,
    content_hash    VARCHAR(64),
    crawl_task_id   BIGINT REFERENCES crawl_tasks(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(school_id, year)
);

CREATE INDEX IF NOT EXISTS idx_school_satisfaction_school ON school_satisfaction(school_id);

DROP TRIGGER IF EXISTS update_school_satisfaction_updated_at ON school_satisfaction;
CREATE TRIGGER update_school_satisfaction_updated_at BEFORE UPDATE ON school_satisfaction
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- -----------------------------------------------------------
-- 4. Major tables
-- -----------------------------------------------------------

CREATE TABLE IF NOT EXISTS major_categories (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(50) NOT NULL,
    education_level VARCHAR(20) NOT NULL,
    code            VARCHAR(10),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(name, education_level)
);

CREATE TABLE IF NOT EXISTS major_subcategories (
    id              SERIAL PRIMARY KEY,
    category_id     INTEGER NOT NULL REFERENCES major_categories(id),
    name            VARCHAR(50) NOT NULL,
    code            VARCHAR(10),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(category_id, name)
);

CREATE TABLE IF NOT EXISTS majors (
    id              BIGSERIAL PRIMARY KEY,
    source_id       VARCHAR(50),
    subcategory_id  INTEGER REFERENCES major_subcategories(id),
    code            VARCHAR(20),
    name            VARCHAR(100) NOT NULL,
    education_level VARCHAR(20) NOT NULL,
    duration        VARCHAR(20),
    degree          VARCHAR(50),
    description     TEXT,
    employment_rate VARCHAR(20),
    graduate_directions TEXT,
    content_hash    VARCHAR(64),
    crawl_task_id   BIGINT REFERENCES crawl_tasks(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(code, education_level)
);

CREATE INDEX IF NOT EXISTS idx_majors_subcategory ON majors(subcategory_id);
CREATE INDEX IF NOT EXISTS idx_majors_name ON majors USING gin(name gin_trgm_ops);

DROP TRIGGER IF EXISTS update_majors_updated_at ON majors;
CREATE TRIGGER update_majors_updated_at BEFORE UPDATE ON majors
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS school_majors (
    id              BIGSERIAL PRIMARY KEY,
    school_id       BIGINT NOT NULL REFERENCES schools(id),
    major_id        BIGINT NOT NULL REFERENCES majors(id),
    content_hash    VARCHAR(64),
    crawl_task_id   BIGINT REFERENCES crawl_tasks(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(school_id, major_id)
);

CREATE INDEX IF NOT EXISTS idx_school_majors_major ON school_majors(major_id);
CREATE INDEX IF NOT EXISTS idx_school_majors_school ON school_majors(school_id);

CREATE TABLE IF NOT EXISTS major_satisfaction (
    id              BIGSERIAL PRIMARY KEY,
    major_id        BIGINT NOT NULL REFERENCES majors(id),
    school_id       BIGINT REFERENCES schools(id),
    overall_score   NUMERIC(3,1),
    vote_count      INTEGER,
    content_hash    VARCHAR(64),
    crawl_task_id   BIGINT REFERENCES crawl_tasks(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(major_id, school_id)
);

DROP TRIGGER IF EXISTS update_major_satisfaction_updated_at ON major_satisfaction;
CREATE TRIGGER update_major_satisfaction_updated_at BEFORE UPDATE ON major_satisfaction
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS major_interpretations (
    id              BIGSERIAL PRIMARY KEY,
    major_id        BIGINT REFERENCES majors(id),
    title           VARCHAR(200),
    content         TEXT NOT NULL,
    author          VARCHAR(100),
    publish_date    DATE,
    source_url      VARCHAR(255),
    content_hash    VARCHAR(64),
    crawl_task_id   BIGINT REFERENCES crawl_tasks(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE NULLS NOT DISTINCT (major_id, title)
);

CREATE INDEX IF NOT EXISTS idx_major_interpretations_major ON major_interpretations(major_id);

DROP TRIGGER IF EXISTS update_major_interpretations_updated_at ON major_interpretations;
CREATE TRIGGER update_major_interpretations_updated_at BEFORE UPDATE ON major_interpretations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- -----------------------------------------------------------
-- 5. Score tables
-- -----------------------------------------------------------

CREATE TABLE IF NOT EXISTS admission_score_lines (
    id              BIGSERIAL PRIMARY KEY,
    province_id     INTEGER NOT NULL REFERENCES provinces(id),
    year            SMALLINT NOT NULL,
    subject_category_id INTEGER REFERENCES subject_categories(id),
    batch           VARCHAR(50) NOT NULL,
    score           INTEGER,
    note            VARCHAR(200),
    special_name    VARCHAR(200),
    content_hash    VARCHAR(64),
    crawl_task_id   BIGINT REFERENCES crawl_tasks(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(province_id, year, subject_category_id, batch, special_name)
);

CREATE INDEX IF NOT EXISTS idx_score_lines_province_year ON admission_score_lines(province_id, year);

DROP TRIGGER IF EXISTS update_admission_score_lines_updated_at ON admission_score_lines;
CREATE TRIGGER update_admission_score_lines_updated_at BEFORE UPDATE ON admission_score_lines
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS score_segments (
    id              BIGSERIAL PRIMARY KEY,
    province_id     INTEGER NOT NULL REFERENCES provinces(id),
    year            SMALLINT NOT NULL,
    subject_category_id INTEGER REFERENCES subject_categories(id),
    score           INTEGER NOT NULL,
    segment_count   INTEGER NOT NULL,
    cumulative_count INTEGER NOT NULL,
    content_hash    VARCHAR(64),
    crawl_task_id   BIGINT REFERENCES crawl_tasks(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(province_id, year, subject_category_id, score)
);

CREATE INDEX IF NOT EXISTS idx_segments_province_year ON score_segments(province_id, year, subject_category_id);
CREATE INDEX IF NOT EXISTS idx_segments_score ON score_segments(province_id, year, subject_category_id, score);

DROP TRIGGER IF EXISTS update_score_segments_updated_at ON score_segments;
CREATE TRIGGER update_score_segments_updated_at BEFORE UPDATE ON score_segments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- -----------------------------------------------------------
-- 6. Enrollment tables
-- -----------------------------------------------------------

CREATE TABLE IF NOT EXISTS enrollment_plans (
    id              BIGSERIAL PRIMARY KEY,
    school_id       BIGINT NOT NULL REFERENCES schools(id),
    province_id     INTEGER NOT NULL REFERENCES provinces(id),
    year            SMALLINT NOT NULL,
    subject_category_id INTEGER REFERENCES subject_categories(id),
    batch           VARCHAR(50),
    batch_code      VARCHAR(30),
    batch_category  VARCHAR(30),
    batch_segment   VARCHAR(30),
    major_name      VARCHAR(100),
    major_id        BIGINT REFERENCES majors(id),
    plan_count      INTEGER,
    duration        VARCHAR(20),
    tuition         VARCHAR(50),
    note            VARCHAR(500),
    major_group_code VARCHAR(50),
    major_code_raw  VARCHAR(50),
    campus          VARCHAR(100),
    education_location VARCHAR(100),
    selection_requirement VARCHAR(255),
    physical_exam_limit VARCHAR(255),
    single_subject_limit VARCHAR(255),
    adjustment_rule VARCHAR(255),
    program_type    VARCHAR(100),
    eligibility_requirements TEXT,
    physical_exam_or_political_review TEXT,
    political_review_requirement TEXT,
    service_obligation TEXT,
    data_source     VARCHAR(100),
    source_url      VARCHAR(255),
    source_updated_at TIMESTAMPTZ,
    quality_flags   JSONB NOT NULL DEFAULT '[]'::jsonb,
    content_hash    VARCHAR(64),
    crawl_task_id   BIGINT REFERENCES crawl_tasks(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE NULLS NOT DISTINCT (school_id, province_id, year, subject_category_id, batch, major_name)
);

CREATE INDEX IF NOT EXISTS idx_plans_school_province_year ON enrollment_plans(school_id, province_id, year);
CREATE INDEX IF NOT EXISTS idx_plans_province_year ON enrollment_plans(province_id, year);
CREATE INDEX IF NOT EXISTS idx_plans_major ON enrollment_plans(major_id) WHERE major_id IS NOT NULL;

ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS major_group_code VARCHAR(50);
ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS batch_code VARCHAR(30);
ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS batch_category VARCHAR(30);
ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS batch_segment VARCHAR(30);
ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS major_code_raw VARCHAR(50);
ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS campus VARCHAR(100);
ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS education_location VARCHAR(100);
ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS selection_requirement VARCHAR(255);
ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS physical_exam_limit VARCHAR(255);
ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS single_subject_limit VARCHAR(255);
ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS adjustment_rule VARCHAR(255);
ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS program_type VARCHAR(100);
ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS eligibility_requirements TEXT;
ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS physical_exam_or_political_review TEXT;
ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS political_review_requirement TEXT;
ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS service_obligation TEXT;
ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS data_source VARCHAR(100);
ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS source_url VARCHAR(255);
ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS source_updated_at TIMESTAMPTZ;
ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS quality_flags JSONB NOT NULL DEFAULT '[]'::jsonb;

DROP TRIGGER IF EXISTS update_enrollment_plans_updated_at ON enrollment_plans;
CREATE TRIGGER update_enrollment_plans_updated_at BEFORE UPDATE ON enrollment_plans
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS major_admission_results (
    id              BIGSERIAL PRIMARY KEY,
    school_id       BIGINT NOT NULL REFERENCES schools(id),
    major_id        BIGINT NOT NULL REFERENCES majors(id),
    province_id     INTEGER NOT NULL REFERENCES provinces(id),
    year            SMALLINT NOT NULL,
    subject_category_id INTEGER REFERENCES subject_categories(id),
    batch           VARCHAR(50) NOT NULL,
    batch_code      VARCHAR(30),
    batch_category  VARCHAR(30),
    batch_segment   VARCHAR(30),
    min_score       INTEGER,
    min_rank        INTEGER,
    avg_score       INTEGER,
    avg_rank        INTEGER,
    max_score       INTEGER,
    max_rank        INTEGER,
    admitted_count  INTEGER,
    plan_count      INTEGER,
    school_code_raw VARCHAR(50),
    school_name_raw VARCHAR(100),
    major_group_code VARCHAR(50),
    major_code_raw  VARCHAR(50),
    campus          VARCHAR(100),
    program_type    VARCHAR(100),
    eligibility_requirements TEXT,
    physical_exam_or_political_review TEXT,
    political_review_requirement TEXT,
    service_obligation TEXT,
    major_name_raw  VARCHAR(100),
    subject_category_raw VARCHAR(50),
    batch_raw       VARCHAR(50),
    remark          VARCHAR(500),
    source_url      VARCHAR(255),
    data_source     VARCHAR(100),
    source_updated_at TIMESTAMPTZ,
    quality_flags   JSONB NOT NULL DEFAULT '[]'::jsonb,
    content_hash    VARCHAR(64),
    crawl_task_id   BIGINT REFERENCES crawl_tasks(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE NULLS NOT DISTINCT (school_id, major_id, province_id, year, subject_category_id, batch)
);

CREATE INDEX IF NOT EXISTS idx_major_admission_school_province_year
    ON major_admission_results(school_id, province_id, year);
CREATE INDEX IF NOT EXISTS idx_major_admission_major
    ON major_admission_results(major_id);

ALTER TABLE major_admission_results ADD COLUMN IF NOT EXISTS school_code_raw VARCHAR(50);
ALTER TABLE major_admission_results ADD COLUMN IF NOT EXISTS batch_code VARCHAR(30);
ALTER TABLE major_admission_results ADD COLUMN IF NOT EXISTS batch_category VARCHAR(30);
ALTER TABLE major_admission_results ADD COLUMN IF NOT EXISTS batch_segment VARCHAR(30);
ALTER TABLE major_admission_results ADD COLUMN IF NOT EXISTS school_name_raw VARCHAR(100);
ALTER TABLE major_admission_results ADD COLUMN IF NOT EXISTS major_group_code VARCHAR(50);
ALTER TABLE major_admission_results ADD COLUMN IF NOT EXISTS major_code_raw VARCHAR(50);
ALTER TABLE major_admission_results ADD COLUMN IF NOT EXISTS campus VARCHAR(100);
ALTER TABLE major_admission_results ADD COLUMN IF NOT EXISTS plan_count INTEGER;
ALTER TABLE major_admission_results ADD COLUMN IF NOT EXISTS program_type VARCHAR(100);
ALTER TABLE major_admission_results ADD COLUMN IF NOT EXISTS eligibility_requirements TEXT;
ALTER TABLE major_admission_results ADD COLUMN IF NOT EXISTS physical_exam_or_political_review TEXT;
ALTER TABLE major_admission_results ADD COLUMN IF NOT EXISTS political_review_requirement TEXT;
ALTER TABLE major_admission_results ADD COLUMN IF NOT EXISTS service_obligation TEXT;
ALTER TABLE major_admission_results ADD COLUMN IF NOT EXISTS data_source VARCHAR(100);
ALTER TABLE major_admission_results ADD COLUMN IF NOT EXISTS source_updated_at TIMESTAMPTZ;
ALTER TABLE major_admission_results ADD COLUMN IF NOT EXISTS quality_flags JSONB NOT NULL DEFAULT '[]'::jsonb;

DROP TRIGGER IF EXISTS update_major_admission_results_updated_at ON major_admission_results;
CREATE TRIGGER update_major_admission_results_updated_at BEFORE UPDATE ON major_admission_results
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS admission_charters (
    id              BIGSERIAL PRIMARY KEY,
    school_id       BIGINT NOT NULL REFERENCES schools(id),
    year            SMALLINT NOT NULL,
    title           VARCHAR(200),
    content         TEXT NOT NULL,
    publish_date    DATE,
    source_url      VARCHAR(255),
    content_hash    VARCHAR(64),
    crawl_task_id   BIGINT REFERENCES crawl_tasks(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(school_id, year)
);

CREATE INDEX IF NOT EXISTS idx_charters_school ON admission_charters(school_id);
CREATE INDEX IF NOT EXISTS idx_charters_year ON admission_charters(year);

DROP TRIGGER IF EXISTS update_admission_charters_updated_at ON admission_charters;
CREATE TRIGGER update_admission_charters_updated_at BEFORE UPDATE ON admission_charters
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS volunteer_timelines (
    id              BIGSERIAL PRIMARY KEY,
    province_id     INTEGER NOT NULL REFERENCES provinces(id),
    year            SMALLINT NOT NULL,
    batch           VARCHAR(50) NOT NULL,
    start_time      TIMESTAMPTZ,
    end_time        TIMESTAMPTZ,
    note            VARCHAR(500),
    content_hash    VARCHAR(64),
    crawl_task_id   BIGINT REFERENCES crawl_tasks(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(province_id, year, batch)
);

CREATE INDEX IF NOT EXISTS idx_timelines_province_year ON volunteer_timelines(province_id, year);

DROP TRIGGER IF EXISTS update_volunteer_timelines_updated_at ON volunteer_timelines;
CREATE TRIGGER update_volunteer_timelines_updated_at BEFORE UPDATE ON volunteer_timelines
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- -----------------------------------------------------------
-- 7. Extension tables
-- -----------------------------------------------------------

CREATE TABLE IF NOT EXISTS special_enrollments (
    id              BIGSERIAL PRIMARY KEY,
    enrollment_type VARCHAR(30) NOT NULL,
    special_admission_type VARCHAR(50),
    province_code   VARCHAR(20),
    school_id       BIGINT REFERENCES schools(id),
    year            SMALLINT NOT NULL,
    title           VARCHAR(200),
    content         TEXT,
    publish_date    DATE,
    source_url      VARCHAR(255),
    application_url VARCHAR(255),
    registration_window JSONB NOT NULL DEFAULT '{}'::jsonb,
    registration_start DATE,
    registration_end DATE,
    shortlist_rule  TEXT,
    selection_rule  TEXT,
    school_assessment TEXT,
    school_exam_rule TEXT,
    composite_score_formula TEXT,
    admission_rule  TEXT,
    eligible_majors JSONB NOT NULL DEFAULT '[]'::jsonb,
    quality_flags   JSONB NOT NULL DEFAULT '[]'::jsonb,
    content_hash    VARCHAR(64),
    crawl_task_id   BIGINT REFERENCES crawl_tasks(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE NULLS NOT DISTINCT (enrollment_type, school_id, year, title)
);

CREATE INDEX IF NOT EXISTS idx_special_type_year ON special_enrollments(enrollment_type, year);
CREATE INDEX IF NOT EXISTS idx_special_school ON special_enrollments(school_id);

ALTER TABLE special_enrollments ADD COLUMN IF NOT EXISTS special_admission_type VARCHAR(50);
ALTER TABLE special_enrollments ADD COLUMN IF NOT EXISTS province_code VARCHAR(20);
ALTER TABLE special_enrollments ADD COLUMN IF NOT EXISTS application_url VARCHAR(255);
ALTER TABLE special_enrollments ADD COLUMN IF NOT EXISTS registration_window JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE special_enrollments ADD COLUMN IF NOT EXISTS registration_start DATE;
ALTER TABLE special_enrollments ADD COLUMN IF NOT EXISTS registration_end DATE;
ALTER TABLE special_enrollments ADD COLUMN IF NOT EXISTS shortlist_rule TEXT;
ALTER TABLE special_enrollments ADD COLUMN IF NOT EXISTS selection_rule TEXT;
ALTER TABLE special_enrollments ADD COLUMN IF NOT EXISTS school_assessment TEXT;
ALTER TABLE special_enrollments ADD COLUMN IF NOT EXISTS school_exam_rule TEXT;
ALTER TABLE special_enrollments ADD COLUMN IF NOT EXISTS composite_score_formula TEXT;
ALTER TABLE special_enrollments ADD COLUMN IF NOT EXISTS admission_rule TEXT;
ALTER TABLE special_enrollments ADD COLUMN IF NOT EXISTS eligible_majors JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE special_enrollments ADD COLUMN IF NOT EXISTS quality_flags JSONB NOT NULL DEFAULT '[]'::jsonb;

DROP TRIGGER IF EXISTS update_special_enrollments_updated_at ON special_enrollments;
CREATE TRIGGER update_special_enrollments_updated_at BEFORE UPDATE ON special_enrollments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TABLE IF NOT EXISTS provincial_announcements (
    id              BIGSERIAL PRIMARY KEY,
    province_id     INTEGER NOT NULL REFERENCES provinces(id),
    year            SMALLINT,
    title           VARCHAR(200) NOT NULL,
    content         TEXT,
    announcement_type VARCHAR(30),
    publish_date    DATE,
    source_url      VARCHAR(255),
    content_hash    VARCHAR(64),
    crawl_task_id   BIGINT REFERENCES crawl_tasks(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_announcements_province ON provincial_announcements(province_id, year);

DROP TRIGGER IF EXISTS update_provincial_announcements_updated_at ON provincial_announcements;
CREATE TRIGGER update_provincial_announcements_updated_at BEFORE UPDATE ON provincial_announcements
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- -----------------------------------------------------------
-- 8. Compatibility source views for gaokao-agent
-- -----------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS gaokao_source;

CREATE OR REPLACE VIEW gaokao_source.schools_v AS
SELECT
    s.id AS school_id,
    s.name AS school_name,
    p.name AS province,
    s.city,
    s.school_type,
    CASE
        WHEN s.is_private THEN '民办'
        ELSE '公办'
    END AS ownership_type,
    ARRAY_REMOVE(ARRAY[
        CASE WHEN s.is_985 THEN '985' END,
        CASE WHEN s.is_211 THEN '211' END,
        CASE WHEN s.is_double_first THEN '双一流' END
    ], NULL) AS school_tier_tags,
    ARRAY_REMOVE(ARRAY[
        CASE WHEN s.is_sino_foreign THEN '中外合作' END,
        CASE WHEN s.is_independent THEN '独立学院' END
    ], NULL) AS cooperation_tags
FROM schools s
LEFT JOIN provinces p ON p.id = s.province_id;

CREATE OR REPLACE VIEW gaokao_source.majors_v AS
SELECT
    m.id AS major_id,
    m.name AS major_name,
    COALESCE(ms.name, mc.name) AS discipline_category,
    m.degree AS degree_type,
    NULL::TEXT AS tuition_range,
    NULL::TEXT AS subject_restrictions
FROM majors m
LEFT JOIN major_subcategories ms ON ms.id = m.subcategory_id
LEFT JOIN major_categories mc ON mc.id = ms.category_id;

CREATE OR REPLACE VIEW gaokao_source.admission_records_v AS
SELECT
    p.code AS province_code,
    mar.year AS admission_year,
    mar.school_id,
    mar.major_id,
    COALESCE(mar.batch_code, mar.batch) AS batch_code,
    mar.min_score,
    mar.min_rank,
    mar.plan_count,
    CONCAT_WS(
        '；',
        mar.remark,
        mar.major_group_code,
        mar.major_code_raw,
        mar.campus,
        mar.program_type,
        mar.eligibility_requirements,
        mar.physical_exam_or_political_review,
        mar.service_obligation
    ) AS major_notes,
    mar.major_group_code,
    mar.major_code_raw,
    mar.campus,
    mar.program_type,
    mar.eligibility_requirements,
    mar.physical_exam_or_political_review,
    mar.political_review_requirement,
    mar.service_obligation,
    mar.source_url,
    mar.data_source,
    'major_admission_results'::TEXT AS evidence_source
FROM major_admission_results mar
JOIN provinces p ON p.id = mar.province_id
UNION ALL
SELECT
    p.code AS province_code,
    ep.year AS admission_year,
    ep.school_id,
    ep.major_id,
    COALESCE(ep.batch_code, ep.batch) AS batch_code,
    NULL::INTEGER AS min_score,
    NULL::INTEGER AS min_rank,
    ep.plan_count,
    CONCAT_WS(
        '；',
        ep.note,
        ep.major_group_code,
        ep.major_code_raw,
        ep.campus,
        ep.education_location,
        ep.selection_requirement,
        ep.physical_exam_limit,
        ep.single_subject_limit,
        ep.adjustment_rule,
        ep.program_type,
        ep.eligibility_requirements,
        ep.physical_exam_or_political_review,
        ep.service_obligation
    ) AS major_notes,
    ep.major_group_code,
    ep.major_code_raw,
    ep.campus,
    ep.program_type,
    ep.eligibility_requirements,
    ep.physical_exam_or_political_review,
    ep.political_review_requirement,
    ep.service_obligation,
    ep.source_url,
    ep.data_source,
    'enrollment_plans'::TEXT AS evidence_source
FROM enrollment_plans ep
JOIN provinces p ON p.id = ep.province_id;

CREATE OR REPLACE VIEW gaokao_source.province_rules_v AS
WITH batch_rows AS (
    SELECT
        p.code AS province_code,
        p.name AS province_name,
        asl.year AS admission_year,
        asl.batch AS batch_code,
        p.gaokao_mode AS subject_mode,
        NULL::TEXT AS subject_requirements,
        TRUE AS score_rank_available,
        NULL::TEXT AS volunteer_mode
    FROM admission_score_lines asl
    JOIN provinces p ON p.id = asl.province_id
    UNION
    SELECT
        p.code AS province_code,
        p.name AS province_name,
        ep.year AS admission_year,
        COALESCE(ep.batch_code, ep.batch) AS batch_code,
        p.gaokao_mode AS subject_mode,
        MAX(ep.selection_requirement) AS subject_requirements,
        EXISTS (
            SELECT 1
            FROM score_segments ss
            WHERE ss.province_id = ep.province_id
              AND ss.year = ep.year
              AND ss.subject_category_id IS NOT DISTINCT FROM ep.subject_category_id
        ) AS score_rank_available,
        NULL::TEXT AS volunteer_mode
    FROM enrollment_plans ep
    JOIN provinces p ON p.id = ep.province_id
    GROUP BY p.code, p.name, ep.province_id, ep.year, COALESCE(ep.batch_code, ep.batch), p.gaokao_mode, ep.subject_category_id
)
SELECT DISTINCT
    province_code,
    province_name,
    admission_year,
    batch_code,
    subject_mode,
    subject_requirements,
    score_rank_available,
    volunteer_mode
FROM batch_rows;

CREATE OR REPLACE VIEW gaokao_source.score_rank_v AS
SELECT
    p.code AS province_code,
    ss.year AS admission_year,
    ss.score,
    ss.cumulative_count AS rank
FROM score_segments ss
JOIN provinces p ON p.id = ss.province_id;
