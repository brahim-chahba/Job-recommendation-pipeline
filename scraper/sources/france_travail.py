import logging
import os

import pandas as pd
import requests

from sources.common import (
    FRANCE_DEPARTMENTS,
    SEARCH_TERMS,
    csv_env,
    extract_city,
    is_remote,
    safe_date,
    safe_response_json,
    sleep_between_requests,
)


logger = logging.getLogger(__name__)


def scrape(results_wanted: int = 20) -> pd.DataFrame:
    token = _france_travail_token()
    if not token:
        logger.warning("France Travail is enabled but credentials/token are missing.")
        return pd.DataFrame()

    base_url = os.getenv(
        "FRANCE_TRAVAIL_API_BASE_URL",
        "https://api.francetravail.io/partenaire/offresdemploi/v2",
    ).rstrip("/")
    departments = csv_env("FRANCE_TRAVAIL_DEPARTMENTS", default=FRANCE_DEPARTMENTS)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    rows = []

    for term in SEARCH_TERMS:
        for department in departments:
            params = {
                "motsCles": term,
                "departement": department,
                "range": f"0-{max(results_wanted - 1, 0)}",
            }
            try:
                response = requests.get(
                    f"{base_url}/offres/search",
                    headers=headers,
                    params=params,
                    timeout=30,
                )
                response.raise_for_status()
            except Exception as exc:
                logger.warning("France Travail failed for %s / %s: %s", term, department, exc)
                continue

            payload = safe_response_json(response, "France Travail search", term, department)
            if not payload:
                continue

            for offer in payload.get("resultats", []):
                rows.append(_normalize_offer(offer, term, department))

            sleep_between_requests()

    return pd.DataFrame(rows)


def _normalize_offer(offer: dict, term: str, department: str) -> dict:
    offer_id = str(offer.get("id") or "")
    lieu = offer.get("lieuTravail") or {}
    entreprise = offer.get("entreprise") or {}
    salary = offer.get("salaire") or {}
    title = offer.get("intitule")
    description = offer.get("description")

    return {
        "id": f"france-travail-{offer_id}",
        "site": "france_travail",
        "job_url": f"https://candidat.francetravail.fr/offres/recherche/detail/{offer_id}",
        "job_url_direct": None,
        "title": title,
        "company": entreprise.get("nom"),
        "location": lieu.get("libelle"),
        "city": extract_city(lieu.get("libelle")),
        "country": "France",
        "date_posted": safe_date(offer.get("dateCreation")),
        "description": description,
        "salary_source": salary.get("libelle"),
        "interval": None,
        "min_amount": None,
        "max_amount": None,
        "currency": "EUR" if salary else None,
        "is_remote": is_remote(" ".join([str(title), str(description)])),
        "job_type": offer.get("typeContratLibelle") or offer.get("typeContrat"),
        "emails": None,
        "search_term": term,
        "search_city": department,
    }


def _france_travail_token() -> str | None:
    client_id = os.getenv("FRANCE_TRAVAIL_CLIENT_ID")
    client_secret = os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    token_url = os.getenv(
        "FRANCE_TRAVAIL_TOKEN_URL",
        "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire",
    )
    scope = os.getenv("FRANCE_TRAVAIL_SCOPE", "api_offresdemploiv2 o2dsoffre")
    try:
        response = requests.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": scope,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        response.raise_for_status()
    except Exception as exc:
        logger.warning("France Travail token request failed: %s", exc)
        return None

    payload = safe_response_json(response, "France Travail token")
    if not payload:
        return None
    return payload.get("access_token")
