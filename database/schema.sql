-- =============================================================================
-- Walk-in Jobs Aggregation System — PostgreSQL Schema
-- =============================================================================

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";   -- For fuzzy text matching

-- =============================================================================
-- JOBS TABLE
-- =============================================================================
CREATE TABLE IF NOT EXISTS jobs (
    id                      SERIAL PRIMARY KEY,
    title                   VARCHAR(255) NOT NULL,
    company                 VARCHAR(255) NOT NULL,
    location                VARCHAR(255),
    location_normalized     VARCHAR(100),          -- Standardized city name
    salary                  VARCHAR(100),
    salary_min              INTEGER,               -- In INR (annual)
    salary_max              INTEGER,               -- In INR (annual)
    salary_currency         VARCHAR(10) DEFAULT 'INR',
    experience              VARCHAR(100),
    experience_min_years    DECIMAL(4,1),
    experience_max_years    DECIMAL(4,1),
    experience_level        VARCHAR(20),           -- fresher/junior/mid/senior
    skills                  TEXT[],               -- Array of skill strings
    walkin_dates            VARCHAR(255),
    walkin_time             VARCHAR(100),
    address                 TEXT,
    contact_person          VARCHAR(255),
    contact_phone           VARCHAR(20),
    contact_email           VARCHAR(255),
    job_url                 VARCHAR(1000),
    job_description         TEXT,
    source                  VARCHAR(50),           -- naukri/linkedin/indeed
    source_id               VARCHAR(500),          -- ID from source site
    job_hash                VARCHAR(64),           -- SHA256 for dedup
    is_walkin               BOOLEAN DEFAULT FALSE,
    is_fresher_friendly     BOOLEAN DEFAULT FALSE,
    is_duplicate            BOOLEAN DEFAULT FALSE,
    duplicate_of_id         INTEGER REFERENCES jobs(id),
    extracted_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    posted_date             TIMESTAMP,
    last_checked            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    telegram_posted         BOOLEAN DEFAULT FALSE,
    telegram_posted_at      TIMESTAMP,
    CONSTRAINT uq_source_id_source UNIQUE (source_id, source)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_jobs_source         ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_is_walkin      ON jobs(is_walkin);
CREATE INDEX IF NOT EXISTS idx_jobs_is_fresher     ON jobs(is_fresher_friendly);
CREATE INDEX IF NOT EXISTS idx_jobs_location       ON jobs(location_normalized);
CREATE INDEX IF NOT EXISTS idx_jobs_extracted_at   ON jobs(extracted_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_telegram       ON jobs(telegram_posted);
CREATE INDEX IF NOT EXISTS idx_jobs_hash           ON jobs(job_hash);
CREATE INDEX IF NOT EXISTS idx_jobs_title_trgm     ON jobs USING gin(title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_jobs_company_trgm   ON jobs USING gin(company gin_trgm_ops);

-- =============================================================================
-- SCRAPE LOGS TABLE
-- =============================================================================
CREATE TABLE IF NOT EXISTS scrape_logs (
    id              SERIAL PRIMARY KEY,
    source          VARCHAR(50) NOT NULL,
    status          VARCHAR(20) NOT NULL CHECK (status IN ('success', 'failed', 'partial')),
    jobs_found      INTEGER DEFAULT 0,
    jobs_added      INTEGER DEFAULT 0,
    jobs_skipped    INTEGER DEFAULT 0,
    started_at      TIMESTAMP NOT NULL,
    ended_at        TIMESTAMP,
    duration_secs   DECIMAL(8,2),
    error_message   TEXT,
    metadata        JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_scrape_logs_source     ON scrape_logs(source);
CREATE INDEX IF NOT EXISTS idx_scrape_logs_started_at ON scrape_logs(started_at DESC);

-- =============================================================================
-- TELEGRAM USERS TABLE
-- =============================================================================
CREATE TABLE IF NOT EXISTS telegram_users (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT UNIQUE NOT NULL,
    username        VARCHAR(255),
    first_name      VARCHAR(255),
    last_name       VARCHAR(255),
    preferences     JSONB DEFAULT '{}',   -- {locations:[], salary_min: 0, fresher_only: false}
    subscribed      BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tg_users_subscribed ON telegram_users(subscribed);
CREATE INDEX IF NOT EXISTS idx_tg_users_user_id    ON telegram_users(user_id);

-- =============================================================================
-- JOB DUPLICATES TABLE  (tracks duplicate relationships)
-- =============================================================================
CREATE TABLE IF NOT EXISTS job_duplicates (
    id              SERIAL PRIMARY KEY,
    original_job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    duplicate_job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    similarity_score DECIMAL(5,2),        -- 0-100%
    detected_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_duplicate_pair UNIQUE (original_job_id, duplicate_job_id)
);

-- =============================================================================
-- MONITORING METRICS TABLE
-- =============================================================================
CREATE TABLE IF NOT EXISTS metrics (
    id          SERIAL PRIMARY KEY,
    metric_name VARCHAR(100) NOT NULL,
    metric_value DECIMAL(12,4),
    tags        JSONB DEFAULT '{}',
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_metrics_name        ON metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_metrics_recorded_at ON metrics(recorded_at DESC);

-- =============================================================================
-- HELPER VIEWS
-- =============================================================================
CREATE OR REPLACE VIEW v_active_walkin_jobs AS
    SELECT * FROM jobs
    WHERE is_walkin = TRUE
      AND is_duplicate = FALSE
      AND extracted_at >= NOW() - INTERVAL '30 days'
    ORDER BY extracted_at DESC;

CREATE OR REPLACE VIEW v_unposted_jobs AS
    SELECT * FROM jobs
    WHERE telegram_posted = FALSE
      AND is_duplicate = FALSE
    ORDER BY extracted_at DESC;

CREATE OR REPLACE VIEW v_daily_stats AS
    SELECT
        DATE(extracted_at)  AS date,
        COUNT(*)            AS total_jobs,
        SUM(CASE WHEN is_walkin THEN 1 ELSE 0 END)          AS walkin_jobs,
        SUM(CASE WHEN is_fresher_friendly THEN 1 ELSE 0 END) AS fresher_jobs,
        SUM(CASE WHEN is_duplicate THEN 1 ELSE 0 END)        AS duplicates,
        COUNT(DISTINCT source) AS sources_active
    FROM jobs
    GROUP BY DATE(extracted_at)
    ORDER BY date DESC;
