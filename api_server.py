"""
Flask API for the Job Matcher model.

Endpoints:
  GET  /api/health   -> health check
  GET  /api/filters  -> available cities, countries, skills, work modes
  POST /api/match    -> match jobs from user preferences
  POST /api/retrain  -> retrain model from source dataset
"""

import os
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS

from job_matcher_model import JobMatcherModelV2, train_and_save

app = Flask(__name__)
CORS(app)

MODEL_PATH = os.getenv("JOB_MATCHER_MODEL_FILE", "job_matcher_v2.pkl")
API_HOST = os.getenv("JOB_MATCHER_API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("JOB_MATCHER_API_PORT", "5001"))
API_DEBUG = os.getenv("JOB_MATCHER_API_DEBUG", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def get_model():
    if Path(MODEL_PATH).exists():
        return JobMatcherModelV2.load(MODEL_PATH)
    print("[API] No model file found. Training a new one...")
    return train_and_save()


model = get_model()


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify(
        {
            "status": "ok",
            "total_jobs": len(model.jobs),
            "model_file": MODEL_PATH,
            "data_file": os.getenv(
                "JOB_MATCHER_DATA_FILE", "data/jobs_manual__split_sources_2026_05_16.json"
            ),
        }
    )


@app.route("/api/filters", methods=["GET"])
def filters():
    return jsonify(model.get_filters())


@app.route("/api/match", methods=["POST"])
def match():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    title = data.get("title", "")
    if not title:
        return jsonify({"error": "'title' is required"}), 400

    results = model.predict(
        title=title,
        city=data.get("city", ""),
        country=data.get("country", ""),
        work_mode=data.get("work_mode", "all"),
        skills=data.get("skills", []),
        top_n=data.get("top_n", 20),
    )

    return jsonify(
        {
            "query": {
                "title": title,
                "city": data.get("city", ""),
                "country": data.get("country", ""),
                "work_mode": data.get("work_mode", "all"),
                "skills": data.get("skills", []),
            },
            "total_matches": len(results),
            "results": results,
        }
    )


@app.route("/api/retrain", methods=["POST"])
def retrain():
    global model
    model = train_and_save()
    return jsonify({"status": "retrained", "total_jobs": len(model.jobs)})


if __name__ == "__main__":
    print(f"\n[API] Starting Job Matcher API on http://localhost:{API_PORT}")
    print("[API] Endpoints:")
    print("  GET  /api/health   -> Health check")
    print("  GET  /api/filters  -> Available filters")
    print("  POST /api/match    -> Match jobs")
    print("  POST /api/retrain  -> Re-train model")
    app.run(host=API_HOST, port=API_PORT, debug=API_DEBUG)
