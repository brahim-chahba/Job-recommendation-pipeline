"""
Flask API for Job Matcher Model
================================
REST API that serves the trained ML model.
Endpoints:
  GET  /api/filters     → available cities, countries, skills, work_modes
  POST /api/match        → match jobs based on user preferences
  GET  /api/health       → health check
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from job_matcher_model_v2 import JobMatcherModelV2, train_and_save
from pathlib import Path

app = Flask(__name__)
CORS(app)  # Allow frontend to call this API

MODEL_PATH = "job_matcher_v2.pkl"

# ─── Load or train model on startup (Auto-reload trigger 5) ───
def get_model():
    if Path(MODEL_PATH).exists():
        return JobMatcherModelV2.load(MODEL_PATH)
    else:
        print("[API] No model found. Training a new one...")
        return train_and_save()

model = get_model()


# ─── Endpoints ────────────────────────────────────────────────────
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "total_jobs": len(model.jobs),
        "model_file": MODEL_PATH,
    })


@app.route("/api/filters", methods=["GET"])
def filters():
    """Return available filter options for the UI."""
    return jsonify(model.get_filters())


@app.route("/api/match", methods=["POST"])
def match():
    """
    Match jobs based on user preferences.

    Request body (JSON):
    {
        "title":     "Data Analyst",
        "city":      "Casablanca",
        "country":   "Morocco",
        "work_mode": "remote",
        "skills":    ["python", "sql"],
        "top_n":     20
    }
    """
    data = request.get_json()
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

    return jsonify({
        "query": {
            "title":     title,
            "city":      data.get("city", ""),
            "country":   data.get("country", ""),
            "work_mode": data.get("work_mode", "all"),
            "skills":    data.get("skills", []),
        },
        "total_matches": len(results),
        "results": results,
    })


@app.route("/api/retrain", methods=["POST"])
def retrain():
    """Re-train the model from the JSON data file."""
    global model
    model = train_and_save()
    return jsonify({"status": "retrained", "total_jobs": len(model.jobs)})


if __name__ == "__main__":
    print("\n[API] Starting Job Matcher API on http://localhost:5001")
    print("[API] Endpoints:")
    print("  GET  /api/health   -> Health check")
    print("  GET  /api/filters  -> Available filters")
    print("  POST /api/match    -> Match jobs")
    print("  POST /api/retrain  -> Re-train model")
    app.run(host="0.0.0.0", port=5001, debug=True)
