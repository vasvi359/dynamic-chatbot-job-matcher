"""
Run this from inside your backend/ folder (same folder as job_search.py, app.py, .env):

    python debug_job_search.py

It bypasses the chatbot UI entirely and prints exactly what SerpAPI returns,
so we can see whether the problem is the API key, the query, or the location.
"""
import os
from dotenv import load_dotenv

load_dotenv()

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "").strip()
print("SERPAPI_KEY present:", bool(SERPAPI_KEY), "| length:", len(SERPAPI_KEY))

import requests

SERPAPI_URL = "https://serpapi.com/search.json"

# Test 1: bare minimum query, no location, no skills — just the role
params = {
    "engine": "google_jobs",
    "q": "Frontend Developer",
    "api_key": SERPAPI_KEY,
    "hl": "en",
}

print("\n--- TEST 1: minimal query, no location ---")
resp = requests.get(SERPAPI_URL, params=params, timeout=30)
print("HTTP status:", resp.status_code)
data = resp.json()
print("Top-level keys in response:", list(data.keys()))
if "error" in data:
    print("SerpAPI ERROR:", data["error"])
print("jobs_results count:", len(data.get("jobs_results", [])))
if data.get("jobs_results"):
    print("First job title:", data["jobs_results"][0].get("title"))

# Test 2: with a location, mimicking what job_search.py sends
print("\n--- TEST 2: with location='Delhi, India', gl='in' ---")
params2 = dict(params)
params2["location"] = "Delhi, India"
params2["gl"] = "in"
resp2 = requests.get(SERPAPI_URL, params=params2, timeout=30)
print("HTTP status:", resp2.status_code)
data2 = resp2.json()
if "error" in data2:
    print("SerpAPI ERROR:", data2["error"])
print("jobs_results count:", len(data2.get("jobs_results", [])))