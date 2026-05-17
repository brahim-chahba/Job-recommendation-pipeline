import json
import os
import urllib.request

url = os.getenv("MATCHER_API_URL", "http://localhost:5001/api/match")
payload = json.dumps({
    "title": "Data Analyst",
    "city": "Casablanca",
    "country": "Morocco",
    "work_mode": "remote",
    "skills": ["python", "sql"],
    "top_n": 5
}).encode("utf-8")

req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read())

print(json.dumps(result, indent=2, ensure_ascii=False)[:3000])
