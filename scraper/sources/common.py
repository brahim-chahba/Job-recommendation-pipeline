import hashlib
import logging
import os
import re
import time
from datetime import datetime
from typing import Iterable

import pandas as pd
import requests
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)


JOB_COLUMNS = [
    "id", "site", "job_url", "job_url_direct", "title", "company",
    "location", "city", "country", "date_posted", "description",
    "salary_source", "interval", "min_amount", "max_amount", "currency",
    "is_remote", "job_type", "emails", "search_term", "search_city",
    "job_category",
]

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


def normalize_jobs_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=JOB_COLUMNS)

    normalized = df.copy()
    for col in JOB_COLUMNS:
        if col not in normalized.columns:
            normalized[col] = None

    normalized["title"] = normalized["title"].fillna("")
    normalized["job_category"] = normalized["job_category"].where(
        normalized["job_category"].notna(),
        normalized["title"].apply(classify_job),
    )
    normalized["city"] = normalized["city"].where(
        normalized["city"].notna(),
        normalized["location"].apply(extract_city),
    )
    normalized["country"] = normalized["country"].fillna("Morocco")
    normalized["is_remote"] = normalized["is_remote"].fillna(False).astype(bool)

    for col in ["min_amount", "max_amount"]:
        normalized[col] = pd.to_numeric(normalized[col], errors="coerce")

    parsed_dates = pd.to_datetime(normalized["date_posted"], errors="coerce")
    normalized["date_posted"] = parsed_dates.dt.date
    normalized["date_posted"] = normalized["date_posted"].where(parsed_dates.notna(), None)

    normalized = normalized[JOB_COLUMNS]
    normalized = normalized[normalized["job_url"].notna()]
    normalized = normalized[normalized["job_url"].astype(str).str.strip() != ""]
    return normalized


def classify_job(title: str) -> str:
    title_lower = (title or "").lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in title_lower for keyword in keywords):
            return category
    return "Other"


def enabled(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        legacy_jobspy = name in {"ENABLE_INDEED", "ENABLE_LINKEDIN"} and enabled("ENABLE_JOBSPY", True)
        return legacy_jobspy if name in {"ENABLE_INDEED", "ENABLE_LINKEDIN"} else default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def csv_env(name: str, default: Iterable[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def soup(url: str) -> BeautifulSoup | None:
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


def safe_response_json(response: requests.Response, context: str, *parts: str) -> dict | None:
    try:
        return response.json()
    except ValueError:
        label = " / ".join(str(part) for part in parts if part)
        detail = f" ({label})" if label else ""
        content_type = response.headers.get("content-type", "")
        snippet = (response.text or "")[:300].replace("\n", " ")
        logger.warning(
            "%s returned non-JSON response%s: status=%s content_type=%s body_prefix=%r",
            context,
            detail,
            response.status_code,
            content_type,
            snippet,
        )
        return None


def sleep_between_requests() -> None:
    time.sleep(float(os.getenv("HTML_SCRAPER_DELAY_SECONDS", "1.0")))


def stable_id(source: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]
    return f"{source}-{digest}"


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", " ", value).strip()


def nearest_card(node):
    for parent in node.parents:
        if getattr(parent, "name", None) in {"article", "li", "div"}:
            text = parent.get_text(" ", strip=True)
            if len(text) > 80:
                return parent
    return node.parent


def location_from_title(title: str | None) -> str | None:
    if not title or "|" not in title:
        return None
    return title.split("|")[-1].strip()


def find_morocco_location(text: str | None) -> str | None:
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


def extract_city(location: str | None) -> str:
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


def safe_date(value) -> str | None:
    if not value:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def first_date(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", text)
    if not match:
        return None
    parsed = datetime.strptime(match.group(1), "%d/%m/%Y")
    return parsed.date().isoformat()


def is_remote(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(token in lowered for token in ["remote", "teletravail", "tele-travail", "hybride"])


def job_type_from_text(text: str | None) -> str | None:
    if not text:
        return None
    lowered = text.lower()
    for token in ["cdi", "cdd", "freelance", "stage", "interim", "alternance"]:
        if token in lowered:
            return token
    return None
