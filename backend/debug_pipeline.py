"""
Run from your backend/ folder:

    python debug_pipeline.py

This calls the REAL job_search.find_and_rank_jobs() with a sample AI/ML-ish
resume targeting "Frontend Developer", and prints the exact query sent to
SerpAPI plus how many jobs came back — so we can see if the query is the problem.

NOTE: find_and_rank_jobs now fetches from Jooble + JSearch + SerpAPI via the
matcher's test_* fetchers. The old job_search._search_jobs monkeypatch is
inert for the production path (_search_jobs is kept only as a deprecated
debug helper), so the query tracer is patched onto matcher.test_serpapi.
"""
import job_search

SAMPLE_RESUME = """
Vasvi Bali
AI/ML Junior Engineer Intern

Experience:
AI Junior Engineer Intern, XYZ Company, 2024-2025
- Built machine learning models using Python, TensorFlow, Pandas, NumPy, Scikit-learn, Keras.
- Worked on data pipelines and model evaluation.

Skills: Python, TensorFlow, Pandas, NumPy, Scikit-learn, Keras, SQL, Git

Location: Delhi, India
"""

TARGET_ROLE = "Frontend Developer"

# Monkey-patch the matcher's SerpAPI fetcher (the production path) to print
# the query before calling the API.
original_search = job_search.matcher.test_serpapi

def patched_search(scenario):
    print("=== ACTUAL QUERY SENT TO SERPAPI ===")
    print(repr(job_search.matcher.build_query(scenario["job_role"], scenario["skills"])))
    print("location:", repr(scenario["location"]), "| country:", repr(scenario["country"]))
    print("=====================================")
    return original_search(scenario)

job_search.matcher.test_serpapi = patched_search

result = job_search.find_and_rank_jobs(SAMPLE_RESUME, TARGET_ROLE, limit=10)

print("\nExtracted candidate profile:", result["candidate"])
print("\ntotalFound (raw jobs across all successful platforms):", result["totalFound"])
print("Jobs returned after scoring/sorting:", len(result["jobs"]))
for j in result["jobs"][:3]:
    print(" -", j["title"], "| score:", j["score"], "| class:", j["classification"])