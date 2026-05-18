"""
Airflow 3.x DAG:
scrape jobs -> MinIO lake -> PostgreSQL data warehouse

Schedule: daily at 05:00 UTC

Pipeline:
  scrape_jobs -> publish_to_lake -> load_raw -> upsert_dim_jobs
  -> export_lake_curated -> log_run
"""

import logging
import os
import re
import sys
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path

import boto3
import pandas as pd
from botocore.config import Config
from botocore.exceptions import ClientError
from sqlalchemy import create_engine, text

from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG
from airflow.sdk.bases.hook import BaseHook

logger = logging.getLogger(__name__)
SCRAPER_DIR = Path("/opt/airflow/scraper")
DATA_DIR = Path("/opt/airflow/data")


def _safe_run_id(run_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", run_id)


def _safe_run_file(run_id: str) -> Path:
    return DATA_DIR / f"jobs_{_safe_run_id(run_id)}.json"


def _read_jobs_frame(context) -> pd.DataFrame:
    jobs_file = context["ti"].xcom_pull(key="jobs_file", task_ids="scrape_jobs")
    if not jobs_file:
        return pd.DataFrame()
    path = Path(jobs_file)
    if not path.exists():
        raise FileNotFoundError(f"Scraped jobs file not found: {path}")
    return pd.read_json(path)


default_args = {
    "owner": "data_team",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": False,
}


def _get_engine():
    conn = BaseHook.get_connection("jobs_dw_postgres")
    url = (
        f"postgresql+psycopg2://{conn.login}:{conn.password}"
        f"@{conn.host}:{conn.port}/{conn.schema}"
    )
    return create_engine(url, pool_pre_ping=True)


def _ensure_raw_jobs_columns(engine):
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE jobs_dw.raw_jobs ADD COLUMN IF NOT EXISTS city TEXT"))
        conn.execute(
            text("ALTER TABLE jobs_dw.raw_jobs ADD COLUMN IF NOT EXISTS country TEXT")
        )


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


def _ensure_lake_bucket(client, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
        return
    except ClientError:
        pass

    try:
        client.create_bucket(Bucket=bucket)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
            raise


def _upload_parquet(client, bucket: str, key: str, frame: pd.DataFrame) -> None:
    buffer = BytesIO()
    frame.to_parquet(buffer, index=False)
    buffer.seek(0)
    client.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())


def _lake_partition_prefix(layer: str, run_id: str, base_name: str) -> str:
    now = datetime.utcnow()
    return (
        f"{layer}/{base_name}/"
        f"year={now:%Y}/month={now:%m}/day={now:%d}/run_id={_safe_run_id(run_id)}"
    )


def scrape_jobs_task(**context):
    if not SCRAPER_DIR.exists():
        raise FileNotFoundError(
            f"Scraper directory not found: {SCRAPER_DIR}. "
            "Mount the local ./scraper folder into the Airflow containers."
        )

    sys.path.insert(0, str(SCRAPER_DIR))
    from indeed_scraper import scrape_all

    run_id = context["run_id"]
    logger.info("[%s] Starting scrape ...", run_id)

    engine = _get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jobs_dw.pipeline_runs (run_id, started_at, status)
                VALUES (:run_id, :now, 'running')
                ON CONFLICT (run_id) DO UPDATE
                SET started_at = EXCLUDED.started_at, status = 'running'
                """
            ),
            {"run_id": run_id, "now": datetime.utcnow()},
        )

    df = scrape_all(results_wanted=20)

    count = len(df)
    logger.info("[%s] Scraped %s unique jobs.", run_id, count)
    context["ti"].xcom_push(key="scraped_count", value=count)

    if df.empty:
        context["ti"].xcom_push(key="jobs_file", value="")
        return

    if "date_posted" in df.columns:
        parsed = pd.to_datetime(df["date_posted"], errors="coerce")
        df["date_posted"] = parsed.dt.strftime("%Y-%m-%d")
        df.loc[parsed.isna(), "date_posted"] = None

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    jobs_file = _safe_run_file(run_id)
    df.to_json(jobs_file, orient="records")
    context["ti"].xcom_push(key="jobs_file", value=str(jobs_file))


def publish_to_lake_task(**context):
    if not _lake_enabled():
        logger.info("MinIO publishing is disabled. Skipping publish_to_lake.")
        return

    run_id = context["run_id"]
    jobs_file = context["ti"].xcom_pull(key="jobs_file", task_ids="scrape_jobs")
    if not jobs_file:
        logger.info("[%s] No staged file found. Skipping lake publish.", run_id)
        return

    path = Path(jobs_file)
    if not path.exists():
        raise FileNotFoundError(f"Scraped jobs file not found: {path}")

    bucket = os.getenv("MINIO_BUCKET", "jobs-lake")
    client = _get_object_store_client()
    _ensure_lake_bucket(client, bucket)

    bronze_prefix = _lake_partition_prefix("bronze", run_id, "jobs")
    json_key = f"{bronze_prefix}/jobs.json"
    parquet_key = f"{bronze_prefix}/jobs.parquet"

    with path.open("rb") as handle:
        client.upload_fileobj(handle, bucket, json_key)

    frame = pd.read_json(path)
    _upload_parquet(client, bucket, parquet_key, frame)

    json_uri = f"s3://{bucket}/{json_key}"
    parquet_uri = f"s3://{bucket}/{parquet_key}"
    logger.info("[%s] Published bronze lake artifacts.", run_id)
    context["ti"].xcom_push(key="lake_bronze_json_uri", value=json_uri)
    context["ti"].xcom_push(key="lake_bronze_parquet_uri", value=parquet_uri)


def load_raw_task(**context):
    run_id = context["run_id"]
    df = _read_jobs_frame(context)

    if df.empty:
        logger.info("Nothing to load into raw_jobs.")
        return

    raw_cols = [
        "id",
        "site",
        "job_url",
        "job_url_direct",
        "title",
        "company",
        "location",
        "city",
        "country",
        "date_posted",
        "description",
        "salary_source",
        "interval",
        "min_amount",
        "max_amount",
        "currency",
        "is_remote",
        "job_type",
        "emails",
        "search_term",
        "search_city",
    ]
    df = df[[c for c in raw_cols if c in df.columns]].copy()
    if "date_posted" in df.columns:
        df["date_posted"] = pd.to_datetime(df["date_posted"], errors="coerce").dt.date
        df["date_posted"] = df["date_posted"].where(df["date_posted"].notna(), None)
    df["run_id"] = run_id
    df["scraped_at"] = datetime.utcnow()

    engine = _get_engine()
    _ensure_raw_jobs_columns(engine)
    df.to_sql(
        "raw_jobs",
        engine,
        schema="jobs_dw",
        if_exists="append",
        index=False,
        method="multi",
        chunksize=200,
    )
    logger.info("[%s] Inserted %s rows into raw_jobs.", run_id, len(df))
    context["ti"].xcom_push(key="raw_inserted", value=len(df))


def upsert_dim_jobs_task(**context):
    run_id = context["run_id"]
    df = _read_jobs_frame(context)

    if df.empty:
        logger.info("Nothing to upsert into dim_jobs.")
        context["ti"].xcom_push(key="dim_inserted", value=0)
        context["ti"].xcom_push(key="dim_updated", value=0)
        return

    today = date.today()

    upsert_sql = text(
        """
        INSERT INTO jobs_dw.dim_jobs (
            job_url, site, title, company, location, city, country,
            date_posted, date_first_seen, date_last_seen,
            is_remote, job_type, job_category,
            salary_min, salary_max, salary_interval, currency,
            description, job_url_direct, emails
        ) VALUES (
            :job_url, :site, :title, :company, :location, :city, :country,
            :date_posted, :today, :today,
            :is_remote, :job_type, :job_category,
            :salary_min, :salary_max, :salary_interval, :currency,
            :description, :job_url_direct, :emails
        )
        ON CONFLICT (job_url) DO UPDATE SET
            date_last_seen  = EXCLUDED.date_last_seen,
            title           = EXCLUDED.title,
            company         = EXCLUDED.company,
            salary_min      = COALESCE(EXCLUDED.salary_min, dim_jobs.salary_min),
            salary_max      = COALESCE(EXCLUDED.salary_max, dim_jobs.salary_max)
        RETURNING (xmax = 0) AS was_inserted
        """
    )

    inserted = 0
    updated = 0

    engine = _get_engine()
    with engine.begin() as conn:
        for _, row in df.iterrows():
            url = str(row.get("job_url", ""))
            if not url or url in {"nan", "None", ""}:
                continue

            def _clean(val):
                s = str(val)
                return None if s in {"nan", "None", "", "NaT"} else s

            def _clean_num(val):
                try:
                    f = float(val)
                    return None if f != f else f
                except (TypeError, ValueError):
                    return None

            def _clean_date(val):
                ts = pd.to_datetime(val, errors="coerce")
                if pd.isna(ts):
                    return None
                return ts.date()

            params = {
                "job_url": url,
                "site": _clean(row.get("site")),
                "title": _clean(row.get("title")),
                "company": _clean(row.get("company")),
                "location": _clean(row.get("location")),
                "city": _clean(row.get("city")),
                "country": _clean(row.get("country")) or "Morocco",
                "date_posted": _clean_date(row.get("date_posted")),
                "today": today,
                "is_remote": bool(row.get("is_remote", False)),
                "job_type": _clean(row.get("job_type")),
                "job_category": _clean(row.get("job_category")),
                "salary_min": _clean_num(row.get("min_amount")),
                "salary_max": _clean_num(row.get("max_amount")),
                "salary_interval": _clean(row.get("interval")),
                "currency": _clean(row.get("currency")),
                "description": _clean(row.get("description")),
                "job_url_direct": _clean(row.get("job_url_direct")),
                "emails": _clean(row.get("emails")),
            }
            result = conn.execute(upsert_sql, params).fetchone()
            if result and result[0]:
                inserted += 1
            else:
                updated += 1

    logger.info("[%s] dim_jobs -> inserted=%s, updated=%s", run_id, inserted, updated)
    context["ti"].xcom_push(key="dim_inserted", value=inserted)
    context["ti"].xcom_push(key="dim_updated", value=updated)


def export_lake_curated_task(**context):
    if not _lake_enabled():
        logger.info("MinIO publishing is disabled. Skipping export_lake_curated.")
        return

    run_id = context["run_id"]
    bucket = os.getenv("MINIO_BUCKET", "jobs-lake")
    client = _get_object_store_client()
    _ensure_lake_bucket(client, bucket)
    engine = _get_engine()

    exports = [
        ("silver", "dim_jobs", "SELECT * FROM jobs_dw.dim_jobs"),
        ("gold", "vw_latest_jobs", "SELECT * FROM jobs_dw.vw_latest_jobs"),
    ]
    uris = []

    for layer, name, sql_query in exports:
        frame = pd.read_sql(sql_query, engine)
        if frame.empty:
            logger.info("[%s] Skip %s/%s export (empty result set).", run_id, layer, name)
            continue

        key = f"{_lake_partition_prefix(layer, run_id, name)}/data.parquet"
        _upload_parquet(client, bucket, key, frame)
        uris.append(f"s3://{bucket}/{key}")

    context["ti"].xcom_push(key="lake_curated_uris", value=uris)
    logger.info("[%s] Exported %s curated datasets to the lake.", run_id, len(uris))


def retrain_model_task(**context):
    import requests
    run_id = context["run_id"]
    urls = [
        "http://matcher-api:5001/api/retrain",
        "http://localhost:5001/api/retrain",
    ]
    for url in urls:
        try:
            logger.info("[%s] Tentative de declenchement du re-entrainement via: %s", run_id, url)
            response = requests.post(url, timeout=300)
            if response.status_code == 200:
                logger.info("[%s] Modele ML re-entraine avec succes ! Status: %s", run_id, response.json())
                return
            else:
                logger.warning("[%s] Echec du re-entrainement sur %s (code %s)", run_id, url, response.status_code)
        except Exception as e:
            logger.warning("[%s] Impossible de joindre l'API %s: %s", run_id, url, e)
    
    logger.error("[%s] Le re-entrainement automatique a echoue sur toutes les adresses.", run_id)


def log_run_task(**context):
    run_id = context["run_id"]
    scraped = context["ti"].xcom_pull(key="scraped_count", task_ids="scrape_jobs") or 0
    inserted = context["ti"].xcom_pull(key="dim_inserted", task_ids="upsert_dim_jobs") or 0
    updated = context["ti"].xcom_pull(key="dim_updated", task_ids="upsert_dim_jobs") or 0
    upstream_tasks = {
        "scrape_jobs",
        "publish_to_lake",
        "load_raw",
        "upsert_dim_jobs",
        "export_lake_curated",
        "retrain_model",
    }
    dag_id = context["dag"].dag_id

    engine = _get_engine()
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT task_id, state
                FROM task_instance
                WHERE dag_id = :dag_id
                  AND run_id = :run_id
                  AND task_id = ANY(:task_ids)
                """
            ),
            {"dag_id": dag_id, "run_id": run_id, "task_ids": list(upstream_tasks)},
        ).mappings().all()

    task_states = {row["task_id"]: row["state"] for row in rows}
    for task_id in upstream_tasks:
        task_states.setdefault(task_id, "missing")

    failed_states = {
        task_id: state for task_id, state in task_states.items() if state != "success"
    }
    status = "failed" if failed_states else "success"
    error_message = None
    if failed_states:
        error_message = "; ".join(
            f"{task_id}={state}" for task_id, state in sorted(failed_states.items())
        )

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE jobs_dw.pipeline_runs
                SET finished_at   = :now,
                    status        = :status,
                    rows_scraped  = :scraped,
                    rows_inserted = :inserted,
                    rows_updated  = :updated,
                    error_message = :error_message
                WHERE run_id = :run_id
                """
            ),
            {
                "run_id": run_id,
                "now": datetime.utcnow(),
                "status": status,
                "scraped": scraped,
                "inserted": inserted,
                "updated": updated,
                "error_message": error_message,
            },
        )

    logger.info(
        "[%s] Done. status=%s scraped=%s inserted=%s updated=%s",
        run_id,
        status,
        scraped,
        inserted,
        updated,
    )
    if failed_states:
        raise RuntimeError(f"Pipeline failed before log_run: {error_message}")


with DAG(
    dag_id="jobs_intelligence_pipeline",
    default_args=default_args,
    description="Daily job scrape -> MinIO lake -> PostgreSQL DW (jobs_dw schema)",
    schedule="0 5 * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=3),
    tags=["jobs", "scraping", "lakehouse", "dw"],
) as dag:
    scrape = PythonOperator(task_id="scrape_jobs", python_callable=scrape_jobs_task)
    lake_bronze = PythonOperator(
        task_id="publish_to_lake", python_callable=publish_to_lake_task
    )
    raw = PythonOperator(task_id="load_raw", python_callable=load_raw_task)
    upsert = PythonOperator(task_id="upsert_dim_jobs", python_callable=upsert_dim_jobs_task)
    lake_curated = PythonOperator(
        task_id="export_lake_curated", python_callable=export_lake_curated_task
    )
    retrain = PythonOperator(
        task_id="retrain_model", python_callable=retrain_model_task
    )
    log = PythonOperator(
        task_id="log_run", python_callable=log_run_task, trigger_rule="all_done"
    )

    scrape >> lake_bronze >> raw >> upsert >> lake_curated >> retrain >> log
