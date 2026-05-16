import logging
from collections.abc import Callable

import pandas as pd

from sources.common import CITIES, SEARCH_TERMS, classify_job, enabled, normalize_jobs_frame
from sources.emploi_ma import scrape as scrape_emploi_ma
from sources.france_travail import scrape as scrape_france_travail
from sources.indeed import scrape as scrape_indeed
from sources.linkedin import scrape as scrape_linkedin
from sources.rekrute import scrape as scrape_rekrute


logger = logging.getLogger(__name__)


SOURCE_SCRAPERS: list[tuple[str, str, bool, Callable[[int], pd.DataFrame]]] = [
    ("ENABLE_INDEED", "Indeed", True, scrape_indeed),
    ("ENABLE_LINKEDIN", "LinkedIn", True, scrape_linkedin),
    ("ENABLE_FRANCE_TRAVAIL", "France Travail", False, scrape_france_travail),
    ("ENABLE_REKRUTE", "Rekrute", True, scrape_rekrute),
    ("ENABLE_EMPLOI_MA", "Emploi.ma", True, scrape_emploi_ma),
]


def scrape_all(results_wanted: int = 20) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    for env_flag, source_name, default_enabled, scraper_func in SOURCE_SCRAPERS:
        if not enabled(env_flag, default=default_enabled):
            logger.info("%s source disabled by %s.", source_name, env_flag)
            continue

        frame = _scrape_source(source_name, scraper_func, results_wanted)
        if frame is not None and not frame.empty:
            frames.append(normalize_jobs_frame(frame))

    if not frames:
        logger.warning("No jobs scraped from any configured source.")
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined = normalize_jobs_frame(combined)
    before = len(combined)
    combined = combined.drop_duplicates(subset=["job_url"], keep="first")
    logger.info("Cross-source deduplication: %s -> %s jobs", before, len(combined))
    return combined


def _scrape_source(source_name: str, scraper_func: Callable[[int], pd.DataFrame], results_wanted: int) -> pd.DataFrame:
    """One broken upstream source should not fail the whole pipeline."""
    try:
        frame = scraper_func(results_wanted)
    except Exception as exc:
        logger.exception("%s source failed; continuing with remaining sources: %s", source_name, exc)
        return pd.DataFrame()

    if frame is None or frame.empty:
        logger.info("%s source returned 0 jobs.", source_name)
        return pd.DataFrame()

    logger.info("%s source returned %s jobs.", source_name, len(frame))
    return frame
