"""
Compatibility wrapper for the Airflow DAG.

The DAG still imports ``scrape_all`` from this module, while the actual
multi-source ingestion logic lives in ``job_sources.py``.
"""

from job_sources import CITIES, SEARCH_TERMS, classify_job, scrape_all


__all__ = ["CITIES", "SEARCH_TERMS", "classify_job", "scrape_all"]
