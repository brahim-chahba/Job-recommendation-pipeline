import os
from datetime import date, datetime
from decimal import Decimal

from fastapi import FastAPI, Query
from sqlalchemy import create_engine, text


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://airflow:airflow@postgres:5432/airflow",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
app = FastAPI(title="Job Intelligence API", version="0.1.0")


def _jsonable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _rows(sql: str, params: dict | None = None):
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params or {}).mappings().all()
    return [{key: _jsonable(value) for key, value in row.items()} for row in rows]


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/jobs")
def jobs(
    category: str | None = None,
    city: str | None = None,
    country: str | None = None,
    remote: bool | None = None,
    source: str | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    filters = ["1=1"]
    params = {"limit": limit}

    if category:
        filters.append("job_category = :category")
        params["category"] = category
    if city:
        filters.append("city = :city")
        params["city"] = city
    if country:
        filters.append("country = :country")
        params["country"] = country
    if remote is not None:
        filters.append("is_remote = :remote")
        params["remote"] = remote
    if source:
        filters.append("site = :source")
        params["source"] = source

    where_clause = " AND ".join(filters)
    return _rows(
        f"""
        SELECT *
        FROM jobs_dw.vw_latest_jobs
        WHERE {where_clause}
        ORDER BY date_last_seen DESC NULLS LAST, date_posted DESC NULLS LAST
        LIMIT :limit
        """,
        params,
    )


@app.get("/skills")
def skills(limit: int = Query(50, ge=1, le=200)):
    return _rows(
        """
        SELECT *
        FROM jobs_dw.vw_skill_mentions
        ORDER BY mention_count DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )


@app.get("/stats/category-city")
def category_city_stats():
    return _rows(
        """
        SELECT *
        FROM jobs_dw.vw_jobs_by_category_city
        ORDER BY job_count DESC
        """
    )


@app.get("/stats/salary")
def salary_stats():
    return _rows(
        """
        SELECT *
        FROM jobs_dw.vw_salary_stats
        ORDER BY jobs_with_salary DESC
        """
    )


@app.get("/pipeline-health")
def pipeline_health(limit: int = Query(20, ge=1, le=100)):
    return _rows(
        """
        SELECT *
        FROM jobs_dw.vw_pipeline_health
        LIMIT :limit
        """,
        {"limit": limit},
    )
