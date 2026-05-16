import hashlib
import logging
import os
import re
import time
from datetime import datetime
from typing import Iterable
from urllib.parse import quote_plus, urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

try:
    from jobspy import scrape_jobs
except Exception:  # pragma: no cover - Airflow logs the real import error at runtime.
    scrape_jobs = None


logger = logging.getLogger(__name__)


SEARCH_TERMS = [
    "Data Engineer", "Data Analyst", "Data Scientist", "Analytics Engineer",
    "ETL Developer", "Data Warehouse Engineer", "Big Data Engineer",
    "Business Intelligence Developer", "Power BI Developer", "dbt Developer",
    "Data Architect", "Data Governance", "Data Quality Engineer",
    "Reporting Analyst", "Tableau Developer", "Data Modeler",
    "Azure Data Engineer", "AWS Data Engineer", "GCP Data Engineer",
    "Cloud Engineer", "Cloud Architect", "DevOps Engineer",
    "Platform Engineer", "Kubernetes Engineer", "Terraform Engineer",
    "AI Engineer", "ML Engineer", "Machine Learning Engineer",
    "NLP Engineer", "MLOps Engineer", "Deep Learning Engineer",
    "Generative AI Engineer", "LLM Engineer",
    "Backend Engineer", "Frontend Engineer", "Full Stack Developer",
    "Software Engineer", "Python Developer", "Java Developer",
    "React Developer", "Node.js Developer",
    "PHP Developer", "Laravel Developer", "Vue.js Developer",
    "Web Developer", "Frontend Developer", "Symfony Developer",
    "iOS Developer", "Android Developer", "React Native Developer",
    "Flutter Developer",
    "Network Engineer", "Cybersecurity Engineer", "Security Analyst",
    "Database Administrator", "Systems Administrator", "Linux Administrator",
    "SAP Consultant", "Salesforce Developer", "ServiceNow Developer",
    "Oracle ERP Consultant", "QA Engineer", "Test Automation Engineer",
    "Product Manager", "Scrum Master", "Business Analyst",
    "Ingenieur Data", "Ingenieur Logiciel", "Developpeur Full Stack",
    "Ingenieur DevOps", "Architecte Cloud", "Consultant SAP",
    "Chef de Projet IT", "Analyste Fonctionnel", "Developpeur Python",
    "Developpeur PHP", "Developpeur React", "Developpeur Mobile",
    "Ingenieur Cloud", "Ingenieur Reseaux", "Ingenieur Systemes",
    "Responsable Informatique", "Architecte Logiciel", "Product Owner",
]

MOROCCO_CITIES = ["Morocco", "Casablanca", "Rabat", "Tanger", "Marrakech"]
CITIES = MOROCCO_CITIES
FRANCE_DEPARTMENTS = ["75", "69", "13", "31", "44", "33", "59", "92"]

CATEGORY_KEYWORDS = {
    "Data & Analytics": [
        "data", "analytics", "bi ", "business intelligence", "tableau",
        "power bi", "qlik", "looker", "dbt", "warehouse", "etl", "reporting",
    ],
    "AI & Machine Learning": [
        "machine learning", "ml ", "ai ", "nlp", "deep learning", "mlops",
        "generative", "llm", "computer vision",
    ],
    "Cloud & DevOps": [
        "cloud", "devops", "azure", "aws", "gcp", "kubernetes", "terraform",
        "docker", "sre ", "platform",
    ],
    "Cybersecurity": ["security", "cyber", "soc ", "siem", "pentest", "iam "],
    "Software Engineering": [
        "software", "backend", "frontend", "full stack", "developer",
        "developpeur", "engineer", "ingenieur", "python", "java", "react",
        "node", "php", "laravel", "angular", "vue", "mobile", "ios", "android",
    ],
    "ERP & Business Systems": ["sap", "salesforce", "servicenow", "oracle erp"],
    "Infrastructure": [
        "network", "infrastructure", "sysadmin", "linux", "database",
        "storage", "virtualization", "reseaux", "systemes",
    ],
    "Management & Product": [
        "manager", "architect", "lead ", "cto", "vp ", "product", "scrum",
        "agile", "project", "chef de projet",
    ],
    "QA & Testing": ["qa ", "quality", "test", "sdet"],
}


def scrape_all(results_wanted: int = 20) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    if _enabled("ENABLE_JOBSPY", default=True):
        frames.append(scrape_jobspy_sources(results_wanted=results_wanted))
    if _enabled("ENABLE_FRANCE_TRAVAIL", default=False):
        frames.append(scrape_france_travail(results_wanted=results_wanted))
    if _enabled("ENABLE_REKRUTE", default=True):
        frames.append(scrape_rekrute(results_wanted=results_wanted))
    if _enabled("ENABLE_EMPLOI_MA", default=True):
        frames.append(scrape_emploi_ma(results_wanted=results_wanted))

    frames = [frame for frame in frames if frame is not None and not frame.empty]
    if not frames:
        logger.warning("No jobs scraped from any configured source.")
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined = _post_process(combined)
    before = len(combined)
    combined = combined.drop_duplicates(subset=["job_url"], keep="first")
    logger.info("Cross-source deduplication: %s -> %s jobs", before, len(combined))
    return combined


def scrape_jobspy_sources(results_wanted: int = 20) -> pd.DataFrame:
    if scrape_jobs is None:
        logger.warning("JobSpy is not importable; skipping Indeed/LinkedIn.")
        return pd.DataFrame()

    site_names = _csv_env("JOBSPY_SITES", default=["indeed", "linkedin"])
    frames = []

    for term in SEARCH_TERMS:
        for city in MOROCCO_CITIES:
            logger.info("JobSpy scrape: %s in %s on %s", term, city, site_names)
            try:
                jobs = scrape_jobs(
                    site_name=site_names,
                    search_term=term,
                    location=city,
                    country_indeed="Morocco",
                    results_wanted=results_wanted,
                    hours_old=168,
                    linkedin_fetch_description=True,
                )
            except Exception as exc:
                logger.warning("JobSpy failed for %s / %s: %s", term, city, exc)
                continue

            if jobs.empty:
                continue

            jobs["search_term"] = term
            jobs["search_city"] = city
            jobs["country"] = "Morocco"
            frames.append(jobs)

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def scrape_france_travail(results_wanted: int = 20) -> pd.DataFrame:
    token = _france_travail_token()
    if not token:
        logger.warning("France Travail is enabled but credentials/token are missing.")
        return pd.DataFrame()

    base_url = os.getenv(
        "FRANCE_TRAVAIL_API_BASE_URL",
        "https://api.francetravail.io/partenaire/offresdemploi/v2",
    ).rstrip("/")
    departments = _csv_env("FRANCE_TRAVAIL_DEPARTMENTS", default=FRANCE_DEPARTMENTS)
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

            for offer in response.json().get("resultats", []):
                rows.append(_normalize_france_travail_offer(offer, term, department))

            _sleep_between_html_requests()

    return pd.DataFrame(rows)


def scrape_rekrute(results_wanted: int = 20) -> pd.DataFrame:
    max_pages = int(os.getenv("REKRUTE_MAX_PAGES", "2"))
    rows = []

    for term in SEARCH_TERMS:
        for page in range(1, max_pages + 1):
            url = (
                "https://www.rekrute.com/offres.html"
                f"?keyword={quote_plus(term)}&query={quote_plus(term)}&s=3&p={page}"
            )
            soup = _soup(url)
            if soup is None:
                continue

            rows.extend(_parse_rekrute_listing(soup, url, term))
            if len(rows) >= results_wanted * len(SEARCH_TERMS):
                break
            _sleep_between_html_requests()

    return pd.DataFrame(rows)


def scrape_emploi_ma(results_wanted: int = 20) -> pd.DataFrame:
    max_pages = int(os.getenv("EMPLOI_MA_MAX_PAGES", "2"))
    rows = []

    for term in SEARCH_TERMS:
        slug = quote_plus(term.lower().replace(" ", "-"))
        for page in range(max_pages):
            page_suffix = f"?page={page}" if page else ""
            url = f"https://www.emploi.ma/recherche-jobs-maroc/{slug}{page_suffix}"
            soup = _soup(url)
            if soup is None:
                continue

            rows.extend(_parse_emploi_ma_listing(soup, url, term))
            if len(rows) >= results_wanted * len(SEARCH_TERMS):
                break
            _sleep_between_html_requests()

    return pd.DataFrame(rows)


def classify_job(title: str) -> str:
    title_lower = (title or "").lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in title_lower for keyword in keywords):
            return category
    return "Other"


def _normalize_france_travail_offer(offer: dict, term: str, department: str) -> dict:
    offer_id = str(offer.get("id") or "")
    lieu = offer.get("lieuTravail") or {}
    entreprise = offer.get("entreprise") or {}
    salary = offer.get("salaire") or {}
    date_creation = _safe_date(offer.get("dateCreation"))

    return {
        "id": f"france-travail-{offer_id}",
        "site": "france_travail",
        "job_url": f"https://candidat.francetravail.fr/offres/recherche/detail/{offer_id}",
        "job_url_direct": None,
        "title": offer.get("intitule"),
        "company": entreprise.get("nom"),
        "location": lieu.get("libelle"),
        "city": _extract_city(lieu.get("libelle")),
        "country": "France",
        "date_posted": date_creation,
        "description": offer.get("description"),
        "salary_source": salary.get("libelle"),
        "interval": None,
        "min_amount": None,
        "max_amount": None,
        "currency": "EUR" if salary else None,
        "is_remote": _is_remote(" ".join([str(offer.get("intitule")), str(offer.get("description"))])),
        "job_type": offer.get("typeContratLibelle") or offer.get("typeContrat"),
        "emails": None,
        "search_term": term,
        "search_city": department,
    }


def _parse_rekrute_listing(soup: BeautifulSoup, source_url: str, term: str) -> list[dict]:
    rows = []
    seen_urls = set()

    for heading in soup.select("h2, h3"):
        link = heading.find("a", href=True)
        if not link:
            continue
        title = _clean_text(link.get_text(" ", strip=True) or heading.get_text(" ", strip=True))
        href = urljoin(source_url, link["href"])
        if not title or href in seen_urls or "rekrute.com" not in href:
            continue
        seen_urls.add(href)

        card = _nearest_card(heading)
        card_text = _clean_text(card.get_text(" ", strip=True)) if card else title
        location = _location_from_title(title) or _find_morocco_location(card_text)

        rows.append({
            "id": _stable_id("rekrute", href),
            "site": "rekrute",
            "job_url": href,
            "job_url_direct": None,
            "title": title,
            "company": None,
            "location": location,
            "city": _extract_city(location),
            "country": "Morocco",
            "date_posted": _first_date(card_text),
            "description": card_text[:4000],
            "salary_source": None,
            "interval": None,
            "min_amount": None,
            "max_amount": None,
            "currency": None,
            "is_remote": _is_remote(card_text),
            "job_type": _job_type_from_text(card_text),
            "emails": None,
            "search_term": term,
            "search_city": "Morocco",
        })

    return rows


def _parse_emploi_ma_listing(soup: BeautifulSoup, source_url: str, term: str) -> list[dict]:
    rows = []
    cards = soup.select(".card-job-detail, .job-description-wrapper, .views-row, article")
    if not cards:
        cards = soup.select("h2, h3")

    for card in cards:
        link = card.select_one("h3 a[href], h2 a[href], a[href]")
        if not link:
            continue
        title = _clean_text(link.get_text(" ", strip=True))
        href = urljoin(source_url, link["href"])
        if not title or "emploi.ma" not in href:
            continue

        card_text = _clean_text(card.get_text(" ", strip=True))
        location = _find_morocco_location(card_text)

        rows.append({
            "id": _stable_id("emploi-ma", href),
            "site": "emploi_ma",
            "job_url": href,
            "job_url_direct": None,
            "title": title,
            "company": None,
            "location": location,
            "city": _extract_city(location),
            "country": "Morocco",
            "date_posted": _first_date(card_text),
            "description": card_text[:4000],
            "salary_source": None,
            "interval": None,
            "min_amount": None,
            "max_amount": None,
            "currency": None,
            "is_remote": _is_remote(card_text),
            "job_type": _job_type_from_text(card_text),
            "emails": None,
            "search_term": term,
            "search_city": "Morocco",
        })

    return rows


def _post_process(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    if "job_category" not in df.columns:
        df["job_category"] = df["title"].apply(classify_job)
    if "city" not in df.columns:
        df["city"] = df["location"].apply(_extract_city)
    if "country" not in df.columns:
        df["country"] = "Morocco"

    for col in ["min_amount", "max_amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "is_remote" in df.columns:
        df["is_remote"] = df["is_remote"].fillna(False).astype(bool)
    if "date_posted" in df.columns:
        df["date_posted"] = pd.to_datetime(df["date_posted"], errors="coerce").dt.date

    return df


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
    return response.json().get("access_token")


def _soup(url: str) -> BeautifulSoup | None:
    headers = {
        "User-Agent": os.getenv(
            "JOB_INTELLIGENCE_USER_AGENT",
            "job-intelligence-pipeline/0.1 (+local academic project)",
        )
    }
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml")
    except Exception as exc:
        logger.warning("HTML source request failed for %s: %s", url, exc)
        return None


def _enabled(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str, default: Iterable[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _sleep_between_html_requests() -> None:
    time.sleep(float(os.getenv("HTML_SCRAPER_DELAY_SECONDS", "1.0")))


def _stable_id(source: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]
    return f"{source}-{digest}"


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", " ", value).strip()


def _nearest_card(node):
    for parent in node.parents:
        if getattr(parent, "name", None) in {"article", "li", "div"}:
            text = parent.get_text(" ", strip=True)
            if len(text) > 80:
                return parent
    return node.parent


def _location_from_title(title: str | None) -> str | None:
    if not title or "|" not in title:
        return None
    return title.split("|")[-1].strip()


def _find_morocco_location(text: str | None) -> str | None:
    if not text:
        return None
    cities = [
        "Casablanca", "Rabat", "Tanger", "Marrakech", "Fes", "Agadir",
        "Meknes", "Oujda", "Kenitra", "Mohammedia", "Temara", "Tetouan",
    ]
    for city in cities:
        if city.lower() in text.lower():
            return city
    return "Morocco"


def _extract_city(location: str | None) -> str:
    if not location:
        return "Unknown"
    for city in [
        "Casablanca", "Rabat", "Tanger", "Marrakech", "Fes", "Agadir",
        "Meknes", "Oujda", "Kenitra", "Paris", "Lyon", "Marseille",
        "Toulouse", "Nantes", "Bordeaux", "Lille",
    ]:
        if city.lower() in str(location).lower():
            return city
    return str(location).split(",")[0].strip()


def _safe_date(value) -> str | None:
    if not value:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _first_date(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", text)
    if not match:
        return None
    parsed = datetime.strptime(match.group(1), "%d/%m/%Y")
    return parsed.date().isoformat()


def _is_remote(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(token in lowered for token in ["remote", "teletravail", "tele-travail", "hybride"])


def _job_type_from_text(text: str | None) -> str | None:
    if not text:
        return None
    lowered = text.lower()
    for token in ["cdi", "cdd", "freelance", "stage", "interim", "alternance"]:
        if token in lowered:
            return token
    return None
