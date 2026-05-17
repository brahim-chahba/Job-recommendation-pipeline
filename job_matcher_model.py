"""
Job Matcher ML Model V2 - Supervised Learning
===============================================
Uses XGBoost classifier trained on real job data
with proper feature engineering for better matching.
"""

import json
import re
import pickle
import numpy as np
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import classification_report, accuracy_score
from sklearn.preprocessing import LabelEncoder
from collections import Counter

DATA_FILE = "jobs_manual__split_sources_2026_05_16.json"
MODEL_FILE = "job_matcher_v2.pkl"

SKILLS_DB = [
    "python","java","javascript","typescript","c++","c#","scala","go","php","ruby",
    "sql","nosql","mongodb","postgresql","mysql","oracle","redis","elasticsearch",
    "machine learning","deep learning","nlp","computer vision","tensorflow","pytorch",
    "keras","scikit-learn","pandas","numpy","spark","hadoop","kafka","airflow","dbt",
    "aws","azure","gcp","google cloud","docker","kubernetes","terraform","ansible",
    "jenkins","ci/cd","git","github","gitlab","power bi","tableau","looker",
    "react","angular","vue.js","vue","node.js","django","flask","fastapi",
    "spring boot","spring","laravel","next.js","html","css",
    "sap","salesforce","servicenow","dynamics 365","odoo",
    "cybersecurity","siem","firewall","pentesting","soc",
    "android","ios","react native","flutter",
    "scrum","agile","jira","linux","microservices","api","rest","etl",
]


def load_data(filepath=DATA_FILE):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"[INFO] Loaded {len(data)} records.")
    return data


def clean_text(text):
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s/&+.\-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_city_name(city):
    if not city:
        return ""
    city = re.sub(r"^\d+\s*-\s*", "", city)
    city = city.strip().title()
    
    blacklist = [
        "unknown", "ma", "na", "n/a", "remote", "morocco", "arg",
        "bouches-du-rhône", "gironde", "haute-garonne", "hauts-de-seine", 
        "loire-atlantique", "nord", "rhône", "rhone"
    ]
    if city.lower() in blacklist:
        return ""

    alias_map = {
        "Fez": "Fes", "Fès": "Fes", "Fès-Meknès": "Fes",
        "Meknès": "Meknes",
        "Tétouan": "Tetouan",
        "Kénitra": "Kenitra",
        "Salé": "Sale",
        "Tangier": "Tanger", "Tangier-Medina": "Tanger", "Charf-Souani": "Tanger", "Charf-Mghogha": "Tanger",
        "Marrakesh": "Marrakech", "Marakech": "Marrakech", "Marrakesh-Safi": "Marrakech",
        "Témara": "Temara", "Tmara": "Temara",
        "Sidi Belyout": "Casablanca", "Maarif": "Casablanca", "Maârif": "Casablanca", 
        "Anfa": "Casablanca", "Bouskoura": "Casablanca", "Nouaceur": "Casablanca", 
        "Ain-Sebaa": "Casablanca", "Assoukhour Assawda": "Casablanca",
        "Agdal": "Rabat", "Hassan": "Rabat",
        "Mohammadia": "Mohammedia", "Mohamédia": "Mohammedia",
        "Jadida": "El Jadida", "El-Jadida": "El Jadida",
        "Béni Mellal": "Beni Mellal",
        "Laâyoune": "Laayoune",
        "El Hoceima": "Al Hoceima", "El-Hoceima": "Al Hoceima",
        "Asfi": "Safi",
        "Aix En Provence": "Aix-En-Provence",
        "Asnieres Sur Seine": "Asnières-Sur-Seine", "Asnieres-Sur-Seine": "Asnières-Sur-Seine",
        "Bois Colombes": "Bois-Colombes",
        "Boulogne Billancourt": "Boulogne-Billancourt",
        "Bouscat": "Le Bouscat",
        "Chapelle-Sur-Erdre": "La Chapelle-Sur-Erdre",
        "Haillan": "Le Haillan",
        "Levallois Perret": "Levallois-Perret",
        "Marcy L Etoile": "Marcy-L'Étoile", "Marcy L'etoile": "Marcy-L'Étoile",
        "Merignac": "Mérignac",
        "Neuilly Sur Seine": "Neuilly-Sur-Seine",
        "Plessis-Robinson": "Le Plessis-Robinson", "Le Plessis Robinson": "Le Plessis-Robinson",
        "St Aignan Grandlieu": "Saint-Aignan-Grandlieu",
        "St Cloud": "Saint-Cloud",
        "St Cyr Au Mont D Or": "Saint-Cyr-Au-Mont-D'Or",
        "St Herblain": "Saint-Herblain",
        "St Jean D Illac": "Saint-Jean-D'Illac",
        "St Paul Les Durance": "Saint-Paul-Lès-Durance",
        "St Priest": "Saint-Priest",
        "Vaulx En Velin": "Vaulx-En-Velin",
        "Venissieux": "Vénissieux",
        "Villeneuve D Ascq": "Villeneuve-D'Ascq"
    }
    
    for k, v in alias_map.items():
        if city.lower() == k.lower() or k.lower() in city.lower():
            city = v
            break

    if len(city) <= 2 and city.isdigit():
        return ""
    if len(city) <= 1:
        return ""
    return city


def extract_skills(text):
    if not text:
        return []
    text_lower = text.lower()
    found = []
    for skill in SKILLS_DB:
        if len(skill) <= 2:
            pattern = r"(?:^|[\s,;:(./])" + re.escape(skill) + r"(?:[\s,;:)./]|$)"
            if re.search(pattern, text_lower):
                found.append(skill)
        else:
            if skill in text_lower:
                found.append(skill)
    return list(set(found))


def detect_work_mode(record):
    is_remote = record.get("is_remote", False)
    desc = (record.get("description") or "").lower()
    title = (record.get("title") or "").lower()
    loc = (record.get("location") or "").lower()
    city = (record.get("city") or "").lower()

    hybrid_kw = ["hybrid","hybride","teletravail partiel","mode hybride","travail hybride"]
    for kw in hybrid_kw:
        if kw in desc or kw in title or kw in loc:
            return "hybrid"
    if is_remote:
        return "remote"
    remote_kw = ["remote","a distance","teletravail","work from home","full remote","fully remote"]
    for kw in remote_kw:
        if kw in desc or kw in title or kw in loc:
            return "remote"
    if city == "remote":
        return "remote"
    return "onsite"


def normalize_job_type(job_type):
    if not job_type:
        return "unknown"
    jt = job_type.lower().strip()
    if "cdi" in jt or jt == "fulltime":
        return "fulltime"
    if "cdd" in jt or "temporary" in jt or "contract" in jt:
        return "contract"
    if "interim" in jt:
        return "interim"
    if "internship" in jt or "stage" in jt:
        return "internship"
    if "parttime" in jt:
        return "parttime"
    return "other"


class JobMatcherModelV2:
    """
    Supervised ML model for job matching.
    
    Training: learns to predict job_category from features.
    Prediction: combines classifier probabilities with similarity scores.
    """

    def __init__(self):
        self.tfidf_title = TfidfVectorizer(max_features=5000, ngram_range=(1,2), max_df=0.95)
        self.tfidf_desc = TfidfVectorizer(max_features=8000, ngram_range=(1,2), max_df=0.90, min_df=2)
        self.category_encoder = LabelEncoder()
        self.city_encoder = LabelEncoder()
        self.country_encoder = LabelEncoder()
        self.mode_encoder = LabelEncoder()
        self.classifier = GradientBoostingClassifier(
            n_estimators=200, max_depth=5, learning_rate=0.1,
            subsample=0.8, random_state=42
        )
        self.title_matrix = None
        self.desc_matrix = None
        self.jobs = []
        self.cities = []
        self.countries = []
        self.categories = []
        self.all_skills = []
        self.skill_to_idx = {}
        self.is_trained = False
        self.classification_report_str = ""

    def _preprocess(self, data):
        processed = []
        for rec in data:
            full_text = (rec.get("title") or "") + " " + (rec.get("description") or "")
            skills = extract_skills(full_text)
            title_clean = clean_text(rec.get("title", ""))
            category = clean_text(rec.get("job_category", ""))
            search_term = clean_text(rec.get("search_term", ""))
            desc_clean = clean_text(rec.get("description", ""))
            
            clean_city = clean_city_name(rec.get("city", ""))
            rec["city"] = clean_city

            processed.append({
                "original": rec,
                "title_clean": title_clean,
                "combined_title": f"{title_clean} {category} {search_term}",
                "desc_for_tfidf": f"{desc_clean} {' '.join(skills)}",
                "city_clean": clean_text(clean_city),
                "country_clean": clean_text(rec.get("country", "")),
                "category": rec.get("job_category", "Other"),
                "work_mode": detect_work_mode(rec),
                "job_type_norm": normalize_job_type(rec.get("job_type")),
                "skills": skills,
            })
        return processed

    def _build_skill_vector(self, skills):
        vec = np.zeros(len(self.skill_to_idx))
        for s in skills:
            if s in self.skill_to_idx:
                vec[self.skill_to_idx[s]] = 1.0
        return vec

    def fit(self, data):
        """Train the model."""
        self.jobs = self._preprocess(data)
        n = len(self.jobs)

        # Collect unique values
        self.cities = sorted(set(j["original"].get("city","") for j in self.jobs if j["original"].get("city")))
        self.countries = sorted(set(j["original"].get("country","") for j in self.jobs if j["original"].get("country")))
        self.categories = sorted(set(j["category"] for j in self.jobs if j["category"]))
        skill_set = set()
        for j in self.jobs:
            skill_set.update(j["skills"])
        self.all_skills = sorted(skill_set)
        self.skill_to_idx = {s: i for i, s in enumerate(self.all_skills)}

        # TF-IDF matrices
        title_corpus = [j["combined_title"] for j in self.jobs]
        self.title_matrix = self.tfidf_title.fit_transform(title_corpus)
        desc_corpus = [j["desc_for_tfidf"] for j in self.jobs]
        self.desc_matrix = self.tfidf_desc.fit_transform(desc_corpus)

        # Encode categoricals
        all_cities = [j["city_clean"] if j["city_clean"] else "unknown" for j in self.jobs]
        all_countries = [j["country_clean"] if j["country_clean"] else "unknown" for j in self.jobs]
        all_modes = [j["work_mode"] for j in self.jobs]
        all_categories = [j["category"] if j["category"] else "Other" for j in self.jobs]

        self.city_encoder.fit(list(set(all_cities)) + ["unknown"])
        self.country_encoder.fit(list(set(all_countries)) + ["unknown"])
        self.mode_encoder.fit(["remote","hybrid","onsite","all","unknown"])
        self.category_encoder.fit(all_categories)

        # Build feature matrix for classifier
        print("[INFO] Building feature matrix for classifier...")
        X = []
        for i, job in enumerate(self.jobs):
            skill_vec = self._build_skill_vector(job["skills"])
            city_enc = self.city_encoder.transform([job["city_clean"] if job["city_clean"] else "unknown"])[0]
            country_enc = self.country_encoder.transform([job["country_clean"] if job["country_clean"] else "unknown"])[0]
            mode_enc = self.mode_encoder.transform([job["work_mode"]])[0]
            n_skills = len(job["skills"])
            title_len = len(job["title_clean"].split())

            features = np.concatenate([
                skill_vec,
                [city_enc, country_enc, mode_enc, n_skills, title_len]
            ])
            X.append(features)

        X = np.array(X)
        y = self.category_encoder.transform(all_categories)

        # Train/test split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        # Train classifier
        print(f"[INFO] Training GradientBoosting on {X_train.shape[0]} samples...")
        self.classifier.fit(X_train, y_train)

        # Evaluate
        y_pred = self.classifier.predict(X_test)
        acc = accuracy_score(y_test, y_pred)
        print(f"\n[RESULT] Classification Accuracy: {acc*100:.1f}%")

        target_names = self.category_encoder.classes_
        report = classification_report(y_test, y_pred, target_names=target_names, zero_division=0)
        self.classification_report_str = report
        print(f"\n{report}")

        # Cross-validation
        # print("[INFO] Running 5-fold cross-validation...")
        # cv_scores = cross_val_score(self.classifier, X, y, cv=5, scoring='accuracy')
        # print(f"[RESULT] CV Accuracy: {cv_scores.mean()*100:.1f}% (+/- {cv_scores.std()*100:.1f}%)")

        self.is_trained = True
        print(f"\n[INFO] Model V2 trained successfully.")
        return self

    def predict(self, title, city="", country="", work_mode="all",
                skills=None, top_n=20):
        """Match user preferences against all jobs using ML + similarity."""
        title_q = clean_text(title)
        city_q = clean_text(city)
        country_q = clean_text(country)
        
        # Override country dynamically if city is provided, because the frontend might hardcode country
        if city_q:
            for job in self.jobs:
                if job["city_clean"] == city_q:
                    country_q = job["country_clean"]
                    break

        work_mode_q = work_mode.lower().strip()
        
        # Enrich skills_q by extracting actual technical skills from title_q
        skills_q = [s.lower().strip() for s in (skills or [])]
        extracted_skills = extract_skills(title_q)
        skills_q = list(set(skills_q) | set(extracted_skills))
        
        n = len(self.jobs)

        # 1) Title TF-IDF similarity (30%)
        query_title_vec = self.tfidf_title.transform([title_q])
        title_scores = cosine_similarity(query_title_vec, self.title_matrix).flatten()

        # 2) Description TF-IDF similarity (15%)
        desc_query = f"{title_q} {' '.join(skills_q)}"
        query_desc_vec = self.tfidf_desc.transform([desc_query])
        desc_scores = cosine_similarity(query_desc_vec, self.desc_matrix).flatten()

        # 3) Classifier probability boost (15%)
        # Predict category from user input, boost jobs of same predicted category
        user_skill_vec = self._build_skill_vector(skills_q)
        try:
            city_enc = self.city_encoder.transform([city_q if city_q else "unknown"])[0]
        except ValueError:
            city_enc = 0
        try:
            country_enc = self.country_encoder.transform([country_q if country_q else "unknown"])[0]
        except ValueError:
            country_enc = 0
        try:
            mode_enc = self.mode_encoder.transform([work_mode_q if work_mode_q != "all" else "unknown"])[0]
        except ValueError:
            mode_enc = 0

        user_features = np.concatenate([
            user_skill_vec,
            [city_enc, country_enc, mode_enc, len(skills_q), len(title_q.split())]
        ]).reshape(1, -1)

        predicted_proba = self.classifier.predict_proba(user_features)[0]
        predicted_category = self.category_encoder.classes_[np.argmax(predicted_proba)]

        # Boost jobs matching predicted category
        category_scores = np.zeros(n)
        for i, job in enumerate(self.jobs):
            job_cat = job["category"]
            if job_cat == predicted_category:
                category_scores[i] = 1.0
            else:
                cat_idx = np.where(self.category_encoder.classes_ == job_cat)[0]
                if len(cat_idx) > 0:
                    category_scores[i] = predicted_proba[cat_idx[0]]

        # 4) Skills overlap (10%)
        skills_scores = np.zeros(n)
        if skills_q:
            for i, job in enumerate(self.jobs):
                if job["skills"]:
                    overlap = len(set(skills_q) & set(job["skills"]))
                    skills_scores[i] = overlap / max(len(skills_q), 1)
        else:
            skills_scores[:] = 0.5

        # 5) City matching (15%)
        city_scores = np.zeros(n)
        for i, job in enumerate(self.jobs):
            jc = job["city_clean"]
            if not city_q:
                city_scores[i] = 0.3
            elif jc == city_q:
                city_scores[i] = 1.0
            elif city_q in jc or jc in city_q:
                city_scores[i] = 0.7
            else:
                city_scores[i] = 0.0

        # 6) Country matching (5%)
        country_scores = np.zeros(n)
        for i, job in enumerate(self.jobs):
            jco = job["country_clean"]
            if not country_q:
                country_scores[i] = 0.3
            elif jco == country_q:
                country_scores[i] = 1.0
            else:
                country_scores[i] = 0.0

        # 7) Work mode matching (10%)
        mode_scores = np.zeros(n)
        for i, job in enumerate(self.jobs):
            if work_mode_q == "all":
                mode_scores[i] = 1.0
            elif job["work_mode"] == work_mode_q:
                mode_scores[i] = 1.0
            elif work_mode_q in ("remote","onsite") and job["work_mode"] == "hybrid":
                mode_scores[i] = 0.5
            else:
                mode_scores[i] = 0.0

        # Weighted combination
        final_scores = (
            0.30 * title_scores +
            0.15 * desc_scores +
            0.15 * category_scores +
            0.10 * skills_scores +
            0.15 * city_scores +
            0.05 * country_scores +
            0.10 * mode_scores
        )

        # Filtre Strict : Ville et Type de travail (Work Mode)
        for i, job in enumerate(self.jobs):
            # Filtre Ville
            if city_q:
                jc = job["city_clean"]
                if not jc or (jc != city_q and city_q not in jc and jc not in city_q):
                    final_scores[i] = 0.0
            
            # Filtre Work Mode (si on ne cherche pas "tous")
            if work_mode_q != "all":
                if job["work_mode"] != work_mode_q:
                    final_scores[i] = 0.0

        # Filtre de pertinence textuelle minimale :
        # Si une recherche textuelle est entrée, l'offre DOIT avoir une correspondance minimale
        # dans le titre, la description ou les compétences. Sinon son score est mis à 0.
        # Cela empêche que des offres 100% hors sujet s'affichent sous prétexte d'être dans la bonne ville.
        if title_q:
            for i in range(n):
                text_relevance = title_scores[i] + desc_scores[i] + skills_scores[i]
                if text_relevance < 0.05:
                    final_scores[i] = 0.0

        if final_scores.max() > 0:
            final_scores = (final_scores / final_scores.max()) * 100

        top_indices = np.argsort(final_scores)[::-1][:top_n]

        results = []
        for idx in top_indices:
            job = self.jobs[idx]
            orig = job["original"]
            score = round(float(final_scores[idx]), 1)
            if score <= 0:
                continue
            results.append({
                "match_score": score,
                "title": orig.get("title", ""),
                "company": orig.get("company", ""),
                "city": orig.get("city", ""),
                "country": orig.get("country", ""),
                "work_mode": job["work_mode"],
                "job_type": job["job_type_norm"],
                "job_category": orig.get("job_category", ""),
                "job_url": orig.get("job_url", ""),
                "site": orig.get("site", ""),
                "date_posted": orig.get("date_posted", ""),
                "skills": job["skills"],
                "predicted_category": predicted_category,
                "description": (orig.get("description") or "")[:500],
            })
        return results

    def get_filters(self):
        morocco_cities = set()
        france_cities = set()
        
        for job in self.jobs:
            city = job["original"].get("city")
            country = job["original"].get("country", "").lower()
            if city:
                if country == "morocco":
                    morocco_cities.add(city)
                else:
                    france_cities.add(city)
                    
        ordered_cities = sorted(list(morocco_cities)) + sorted(list(france_cities))
        
        return {
            "cities": ordered_cities,
            "countries": self.countries,
            "categories": self.categories,
            "skills": self.all_skills,
            "work_modes": ["all", "remote", "hybrid", "onsite"],
        }

    def save(self, filepath=MODEL_FILE):
        with open(filepath, "wb") as f:
            pickle.dump(self, f)
        size_mb = Path(filepath).stat().st_size / (1024 * 1024)
        print(f"[INFO] Model saved to {filepath} ({size_mb:.1f} MB)")

    @staticmethod
    def load(filepath=MODEL_FILE):
        with open(filepath, "rb") as f:
            model = pickle.load(f)
        print(f"[INFO] Model loaded from {filepath}")
        return model


def train_and_save():
    data = load_data()
    model = JobMatcherModelV2()
    model.fit(data)
    model.save()
    return model


if __name__ == "__main__":
    model = train_and_save()

    tests = [
        {"name": "Data Analyst, Casablanca, remote",
         "params": {"title":"Data Analyst","city":"Casablanca","country":"Morocco",
                     "work_mode":"remote","skills":["python","sql","power bi"],"top_n":5}},
        {"name": "Software Engineer, Rabat, onsite",
         "params": {"title":"Software Engineer","city":"Rabat","country":"Morocco",
                     "work_mode":"onsite","skills":["java","spring boot"],"top_n":5}},
        {"name": "DevOps, France, hybrid",
         "params": {"title":"DevOps Engineer","city":"","country":"France",
                     "work_mode":"hybrid","skills":["docker","kubernetes","aws"],"top_n":5}},
    ]

    for test in tests:
        print("\n" + "="*70)
        print(f"TEST: {test['name']}")
        print("="*70)
        results = model.predict(**test["params"])
        print(f"  Predicted category: {results[0]['predicted_category'] if results else 'N/A'}")
        for i, r in enumerate(results, 1):
            print(f"  {i}. [{r['match_score']:5.1f}%] {r['title']}")
            print(f"     {r['company']} | {r['city']}, {r['country']} | {r['work_mode']}")
            print(f"     Cat: {r['job_category']} | Skills: {', '.join(r['skills'][:6])}")
            print()
