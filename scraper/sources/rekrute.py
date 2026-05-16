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
    location_from_title,
    nearest_card,
    sleep_between_requests,
    soup,
    stable_id,
)


logger = logging.getLogger(__name__)


def scrape(results_wanted: int = 20) -> pd.DataFrame:
    max_pages = int(os.getenv("REKRUTE_MAX_PAGES", "2"))
    rows = []

    for term in SEARCH_TERMS:
        for page in range(1, max_pages + 1):
            url = (
                "https://www.rekrute.com/offres.html"
                f"?keyword={quote_plus(term)}&query={quote_plus(term)}&s=3&p={page}"
            )
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
    seen_urls = set()

    for heading in page_soup.select("h2, h3"):
        link = heading.find("a", href=True)
        if not link:
            continue
        title = clean_text(link.get_text(" ", strip=True) or heading.get_text(" ", strip=True))
        href = urljoin(source_url, link["href"])
        if not title or href in seen_urls or "rekrute.com" not in href:
            continue
        seen_urls.add(href)

        card = nearest_card(heading)
        card_text = clean_text(card.get_text(" ", strip=True)) if card else title
        location = location_from_title(title) or find_morocco_location(card_text)

        rows.append({
            "id": stable_id("rekrute", href),
            "site": "rekrute",
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
