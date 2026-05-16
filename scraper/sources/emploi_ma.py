import logging
import os
from urllib.parse import quote_plus, urljoin

import pandas as pd

from sources.common import (
    SEARCH_TERMS,
    clean_text,
    extract_city,
    find_morocco_location,
    first_date,
    is_remote,
    job_type_from_text,
    sleep_between_requests,
    soup,
    stable_id,
)


logger = logging.getLogger(__name__)


def scrape(results_wanted: int = 20) -> pd.DataFrame:
    max_pages = int(os.getenv("EMPLOI_MA_MAX_PAGES", "2"))
    rows = []

    for term in SEARCH_TERMS:
        slug = quote_plus(term.lower().replace(" ", "-"))
        for page in range(max_pages):
            page_suffix = f"?page={page}" if page else ""
            url = f"https://www.emploi.ma/recherche-jobs-maroc/{slug}{page_suffix}"
            page_soup = soup(url)
            if page_soup is None:
                continue

            rows.extend(_parse_listing(page_soup, url, term))
            if len(rows) >= results_wanted * len(SEARCH_TERMS):
                break
            sleep_between_requests()

    return pd.DataFrame(rows)


def _parse_listing(page_soup, source_url: str, term: str) -> list[dict]:
    rows = []
    cards = page_soup.select(".card-job-detail, .job-description-wrapper, .views-row, article")
    if not cards:
        cards = page_soup.select("h2, h3")

    for card in cards:
        link = card.select_one("h3 a[href], h2 a[href], a[href]")
        if not link:
            continue
        title = clean_text(link.get_text(" ", strip=True))
        href = urljoin(source_url, link["href"])
        if not title or "emploi.ma" not in href:
            continue

        card_text = clean_text(card.get_text(" ", strip=True))
        location = find_morocco_location(card_text)

        rows.append({
            "id": stable_id("emploi-ma", href),
            "site": "emploi_ma",
            "job_url": href,
            "job_url_direct": None,
            "title": title,
            "company": None,
            "location": location,
            "city": extract_city(location),
            "country": "Morocco",
            "date_posted": first_date(card_text),
            "description": card_text[:4000],
            "salary_source": None,
            "interval": None,
            "min_amount": None,
            "max_amount": None,
            "currency": None,
            "is_remote": is_remote(card_text),
            "job_type": job_type_from_text(card_text),
            "emails": None,
            "search_term": term,
            "search_city": "Morocco",
        })

    return rows
