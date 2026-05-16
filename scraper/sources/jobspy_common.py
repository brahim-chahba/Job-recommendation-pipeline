import logging

import pandas as pd

from sources.common import MOROCCO_CITIES, SEARCH_TERMS

try:
    from jobspy import scrape_jobs
except Exception:  # pragma: no cover - Airflow logs import issues at runtime.
    scrape_jobs = None


logger = logging.getLogger(__name__)


def scrape_jobspy_site(site_name: str, results_wanted: int = 20) -> pd.DataFrame:
    if scrape_jobs is None:
        logger.warning("JobSpy is not importable; skipping %s.", site_name)
        return pd.DataFrame()

    frames = []
    for term in SEARCH_TERMS:
        for city in MOROCCO_CITIES:
            logger.info("JobSpy scrape: %s in %s on %s", term, city, site_name)
            try:
                jobs = scrape_jobs(
                    site_name=[site_name],
                    search_term=term,
                    location=city,
                    country_indeed="Morocco",
                    results_wanted=results_wanted,
                    hours_old=168,
                    linkedin_fetch_description=site_name == "linkedin",
                )
            except Exception as exc:
                logger.warning("JobSpy %s failed for %s / %s: %s", site_name, term, city, exc)
                continue

            if jobs.empty:
                continue

            jobs["search_term"] = term
            jobs["search_city"] = city
            jobs["country"] = "Morocco"
            frames.append(jobs)

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
