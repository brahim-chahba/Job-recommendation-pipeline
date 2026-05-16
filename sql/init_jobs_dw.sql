

CREATE SCHEMA IF NOT EXISTS jobs_dw;

-- ------------------------------------------------------------
-- RAW LAYER  
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobs_dw.raw_jobs (
    raw_id          BIGSERIAL PRIMARY KEY,
    scraped_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id          TEXT,
    id              TEXT,
    site            TEXT,
    job_url         TEXT,
    job_url_direct  TEXT,
    title           TEXT,
    company         TEXT,
    location        TEXT,
    city            TEXT,
    country         TEXT,
    date_posted     DATE,
    description     TEXT,
    salary_source   TEXT,
    interval        TEXT,
    min_amount      NUMERIC,
    max_amount      NUMERIC,
    currency        TEXT,
    is_remote       BOOLEAN,
    job_type        TEXT,
    emails          TEXT,
    search_term     TEXT,
    search_city     TEXT
);

ALTER TABLE jobs_dw.raw_jobs ADD COLUMN IF NOT EXISTS city TEXT;
ALTER TABLE jobs_dw.raw_jobs ADD COLUMN IF NOT EXISTS country TEXT;

-- ------------------------------------------------------------
-- CLEAN LAYER 
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobs_dw.dim_jobs (
    job_id          BIGSERIAL PRIMARY KEY,
    job_url         TEXT UNIQUE NOT NULL,
    site            TEXT,
    title           TEXT,
    company         TEXT,
    location        TEXT,
    city            TEXT,
    country         TEXT DEFAULT 'Morocco',
    date_posted     DATE,
    date_first_seen DATE,
    date_last_seen  DATE,
    is_remote       BOOLEAN,
    job_type        TEXT,
    job_category    TEXT,
    salary_min      NUMERIC,
    salary_max      NUMERIC,
    salary_interval TEXT,
    currency        TEXT,
    description     TEXT,
    job_url_direct  TEXT,
    emails          TEXT
);

-- ------------------------------------------------------------
-- PIPELINE RUN LOG
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobs_dw.pipeline_runs (
    run_id        TEXT PRIMARY KEY,
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ,
    status        TEXT,
    rows_scraped  INT DEFAULT 0,
    rows_inserted INT DEFAULT 0,
    rows_updated  INT DEFAULT 0,
    error_message TEXT
);

-- ------------------------------------------------------------
-- VIEWS  
-- ------------------------------------------------------------

-- Main jobs view 
CREATE OR REPLACE VIEW jobs_dw.vw_latest_jobs AS
SELECT
    j.*,
    EXTRACT(YEAR  FROM j.date_posted) AS post_year,
    EXTRACT(MONTH FROM j.date_posted) AS post_month,
    TO_CHAR(j.date_posted, 'YYYY-MM') AS post_month_label,
    (j.salary_min + j.salary_max) / 2.0 AS salary_mid
FROM jobs_dw.dim_jobs j;

-- Skills frequency
CREATE OR REPLACE VIEW jobs_dw.vw_skill_mentions AS
WITH skills(skill) AS (
    VALUES
        ('Python'),('SQL'),('Spark'),('Kafka'),('Airflow'),('dbt'),
        ('Power BI'),('Tableau'),('Azure'),('AWS'),('GCP'),
        ('Docker'),('Kubernetes'),('Terraform'),('Java'),('Scala'),
        ('R'),('Machine Learning'),('Deep Learning'),('NLP'),
        ('React'),('Node.js'),('Laravel'),('PHP'),('Angular'),('Vue.js'),
        ('SAP'),('Salesforce'),('ServiceNow'),('Oracle'),('MongoDB'),
        ('FastAPI'),('Django'),('Spring Boot'),('Microservices')
)
SELECT
    s.skill,
    COUNT(*) AS mention_count
FROM jobs_dw.dim_jobs j
CROSS JOIN skills s
WHERE (
        s.skill = 'R'
        AND (
            COALESCE(j.description, '') ~* '(^|[^[:alnum:]_])r([^[:alnum:]_]|$)'
            OR COALESCE(j.title, '') ~* '(^|[^[:alnum:]_])r([^[:alnum:]_]|$)'
        )
      )
   OR (
        s.skill <> 'R'
        AND (
            LOWER(COALESCE(j.description, '')) LIKE '%' || LOWER(s.skill) || '%'
            OR LOWER(COALESCE(j.title, ''))    LIKE '%' || LOWER(s.skill) || '%'
        )
      )
GROUP BY s.skill
ORDER BY mention_count DESC;

-- Jobs per category + city
CREATE OR REPLACE VIEW jobs_dw.vw_jobs_by_category_city AS
SELECT
    COALESCE(job_category, 'Other') AS job_category,
    COALESCE(city, 'Unknown')       AS city,
    COUNT(*)                        AS job_count,
    COUNT(*) FILTER (WHERE is_remote = true) AS remote_count,
    MIN(date_posted)                AS oldest_post,
    MAX(date_posted)                AS newest_post
FROM jobs_dw.dim_jobs
GROUP BY job_category, city;

-- Salary statistics
CREATE OR REPLACE VIEW jobs_dw.vw_salary_stats AS
SELECT
    job_category,
    city,
    salary_interval,
    currency,
    COUNT(*)                                         AS jobs_with_salary,
    ROUND(AVG(salary_min), 0)                        AS avg_salary_min,
    ROUND(AVG(salary_max), 0)                        AS avg_salary_max,
    ROUND(AVG((salary_min + salary_max) / 2.0), 0)  AS avg_salary_mid
FROM jobs_dw.dim_jobs
WHERE salary_min IS NOT NULL
   OR salary_max IS NOT NULL
GROUP BY job_category, city, salary_interval, currency;

-- Pipeline health 
CREATE OR REPLACE VIEW jobs_dw.vw_pipeline_health AS
SELECT
    run_id,
    started_at,
    finished_at,
    status,
    rows_scraped,
    rows_inserted,
    rows_updated,
    ROUND(EXTRACT(EPOCH FROM (finished_at - started_at)) / 60.0, 1) AS duration_minutes
FROM jobs_dw.pipeline_runs
ORDER BY started_at DESC;
