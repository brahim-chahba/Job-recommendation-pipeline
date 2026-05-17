# Review: Person B (`tarik`) Changes

## Scope Reviewed
- Author: `tarik <tarikboka123@gmail.com>`
- Commit: `7c3101c` (`add frontend et aussi model`)
- Size: 22 files added, 4389 insertions

## Summary
Tarik added three major pieces:
- A Flask-based matcher API (`api_server.py`)
- A supervised ML matching model + serialized artifact (`job_matcher_model.py`, `job_matcher_v2.pkl`)
- A React/Vite frontend (`frontend/`)

The feature direction is good, but the current state is **not runnable end-to-end** in this repository without fixes.

## Findings (Ordered by Severity)

### 1. High - API startup is broken (wrong import + missing runtime deps)
- `api_server.py` imports a non-existent module: `from job_matcher_model_v2 import ...` at `api_server.py:13`.
- Only `job_matcher_model.py` exists in repo.
- Flask dependencies are not declared in active requirements:
  - `api/requirements.txt` contains FastAPI stack only (`fastapi`, `uvicorn`, `sqlalchemy`, `psycopg2-binary`, `boto3`) at `api/requirements.txt:1-5`.
- Runtime evidence:
  - `python -c "import api_server"` fails with `ModuleNotFoundError: No module named 'flask'`.

Impact:
- Matcher API cannot boot, so frontend matcher flow cannot work.

---

### 2. High - Model training/data loading path mismatch
- Model expects root-level JSON file:
  - `DATA_FILE = "jobs_manual__split_sources_2026_05_16.json"` at `job_matcher_model.py:21`.
- Actual dataset lives under `data/` in this repo.
- Runtime evidence:
  - `python -c "from job_matcher_model import load_data; load_data()"` fails with `FileNotFoundError`.

Impact:
- Retraining path fails when model artifact is missing or retrain endpoint is invoked.

---

### 3. High - Service topology/ports are inconsistent
- Frontend calls Flask-style endpoints on `5001`:
  - `frontend/src/App.tsx:46` (`/api/filters`)
  - `frontend/src/App.tsx:73` (`/api/match`)
- Test script calls `5000`:
  - `test_api.py:4`
- Existing compose stack exposes API service as FastAPI on port `8000`:
  - `docker-compose.yaml:400` (service `api`)
  - `docker-compose.jobs.yaml:199` (service `api`)

Impact:
- Components do not talk to each other without manual port/service rewiring.

---

### 4. Medium - Large binary model committed to Git
- `job_matcher_v2.pkl` is tracked (~40.7MB).

Impact:
- Increases repository size and clone/pull overhead.
- Harder collaboration/versioning for model iterations.

Recommendation:
- Move model artifacts to object storage/release assets or `.gitignore` + reproducible training pipeline.

---

### 5. Medium - Frontend text quality / encoding polish needed
- Several UI strings in `frontend/src/App.tsx` show missing accents/typos in French text (for example around `App.tsx:118-123`, `App.tsx:153`, `App.tsx:201`).

Impact:
- User-facing quality issue in production UI.

## What Is Good
- Clear intent to deliver full vertical slice (model + API + UI).
- Frontend scaffolding is complete and structured.
- Model includes useful matching features (text similarity + categorical scoring + skills overlap).

## Fix Checklist
1. Fix API import:
   - Replace `job_matcher_model_v2` import with `job_matcher_model` in `api_server.py`.
2. Add Flask deps:
   - Add `flask` and `flask-cors` to the runtime requirements used by this API.
3. Fix dataset path:
   - Point to `data/jobs_manual__split_sources_2026_05_16.json` or make path configurable by env var.
4. Unify ports/services:
   - Decide single API entrypoint (`8000` FastAPI or `5001` Flask) and align frontend + test script.
5. Clean model artifact strategy:
   - Remove tracked large `.pkl` from Git history going forward (or keep with clear policy).
6. Polish French UI strings.

## Overall Verdict
- **Status: Needs fixes before merge-to-main usage as default app path.**
- The work is promising, but currently integration blockers prevent reliable execution.
