import os
from datetime import date, datetime
from decimal import Decimal

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
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


def _lake_enabled() -> bool:
    value = os.getenv("ENABLE_MINIO_LAKE", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _get_object_store_client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
        aws_access_key_id=os.getenv("MINIO_ROOT_USER", "minioadmin"),
        aws_secret_access_key=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin"),
        region_name=os.getenv("MINIO_REGION", "us-east-1"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _prefix_stats(client, bucket: str, prefix: str) -> dict:
    paginator = client.get_paginator("list_objects_v2")
    object_count = 0
    total_size_bytes = 0
    latest = None

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            object_count += 1
            total_size_bytes += int(obj.get("Size", 0))
            last_modified = obj.get("LastModified")
            if last_modified and (latest is None or last_modified > latest["last_modified"]):
                latest = {"key": obj.get("Key"), "last_modified": last_modified}

    result = {
        "prefix": prefix,
        "object_count": object_count,
        "total_size_bytes": total_size_bytes,
    }
    if latest:
        result["latest_object_key"] = latest["key"]
        result["latest_object_last_modified"] = _jsonable(latest["last_modified"])
    return result


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


@app.get("/lake-health")
def lake_health():
    enabled = _lake_enabled()
    bucket = os.getenv("MINIO_BUCKET", "jobs-lake")
    endpoint = os.getenv("MINIO_ENDPOINT", "http://minio:9000")

    if not enabled:
        return {"enabled": False, "bucket": bucket, "endpoint": endpoint}

    client = _get_object_store_client()

    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        return {
            "enabled": True,
            "reachable": False,
            "bucket": bucket,
            "endpoint": endpoint,
            "error": code,
        }

    zones = {
        "bronze": _prefix_stats(client, bucket, "bronze/"),
        "silver": _prefix_stats(client, bucket, "silver/"),
        "gold": _prefix_stats(client, bucket, "gold/"),
    }

    total_objects = sum(zone["object_count"] for zone in zones.values())
    total_size_bytes = sum(zone["total_size_bytes"] for zone in zones.values())

    return {
        "enabled": True,
        "reachable": True,
        "bucket": bucket,
        "endpoint": endpoint,
        "total_objects": total_objects,
        "total_size_bytes": total_size_bytes,
        "zones": zones,
    }
