"""
Run from your backend/ folder:

    python debug_multisource.py

Closest equivalent to hitting /job-matches end-to-end, plus verification:

1. Uses a REAL resume from the DB (latest uploaded, same source /job-matches
   reads) via get_or_create_profile — exercising the profile cache path.
   Falls back to a built-in sample resume if the DB is unreachable.
2. Wraps each matcher test_* fetcher to record how many items each platform
   returned (pass-through, so no duplicate API calls).
3. Runs the production find_and_rank_jobs.
4. Independently re-sorts the captured pool by final_score and checks the
   production top-10 matches — proving global (not per-platform) ranking.
5. Audits freshness: matcher.is_fresh on every top-10 job's parsed date.
   Known limitation: JSearch omits posting dates for most listings (not a
   parsing issue) and SerpAPI's relative strings are discarded by the
   matcher's fetcher, so only Jooble dates are reliably parseable; undated
   jobs are kept by design and simply score 0 freshness points.
6. Prints role_level / matched_skills / classification for a relevance
   spot-check.
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

# ------------------------------------------------------------------
# 1. Real resume from the DB (same query /job-matches uses)
# ------------------------------------------------------------------
resume_text = None
resume_id = None
try:
    from db import get_connection

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, extracted_text FROM resumes ORDER BY uploaded_at DESC LIMIT 1"
    )
    row = cur.fetchone()
    if row:
        resume_id = row["id"]
        resume_text = row["extracted_text"]
    cur.close()
    conn.close()
except Exception as e:
    print(f"[verify] DB unavailable ({e}); using sample resume")

if resume_text:
    print(f"[verify] Using real resume id={resume_id} ({len(resume_text)} chars)")
    try:
        profile = job_search.get_or_create_profile(resume_id, resume_text)
    except Exception as e:
        # e.g. candidate_profiles table not migrated yet (needs superuser to
        # run migrations.sql). Fall back to direct extraction so the
        # multi-platform verification can still run; the cache path is
        # exercised separately once the table exists.
        print(f"[verify] profile cache unavailable ({type(e).__name__}: {e})")
        print("[verify] >> run migrations.sql as a superuser to enable caching <<")
        profile = job_search._profile_from_resume(resume_text)
else:
    print("[verify] Using built-in sample resume")
    resume_text = SAMPLE_RESUME
    profile = job_search._profile_from_resume(resume_text)

print("[verify] PROFILE:", profile)

scenario = {
    "job_role": TARGET_ROLE,
    "skills": profile["skills"],
    "experience_years": profile["experience_years"],
    "location": profile["location"],
    "country": job_search._country_code(profile["country"], profile["location"]),
}
print("[verify] SCENARIO:", scenario)

# ------------------------------------------------------------------
# 2. Pass-through wrappers that capture each platform's fetched items
# ------------------------------------------------------------------
matcher = job_search.matcher
raw_fetchers = {
    "Jooble": matcher.test_jooble,
    "JSearch": matcher.test_jsearch,
    "SerpAPI": matcher.test_serpapi,
}
captured = {}
failed = {}

def make_wrapper(name, fn):
    def inner(scen):
        try:
            items = fn(scen)
        except Exception as e:
            failed[name] = str(e)
            raise
        captured[name] = items or []
        return items
    return inner

matcher.test_jooble = make_wrapper("Jooble", raw_fetchers["Jooble"])
matcher.test_jsearch = make_wrapper("JSearch", raw_fetchers["JSearch"])
matcher.test_serpapi = make_wrapper("SerpAPI", raw_fetchers["SerpAPI"])

# ------------------------------------------------------------------
# 3. Production path (same function /job-matches calls)
# ------------------------------------------------------------------
result = job_search.find_and_rank_jobs(
    resume_text, TARGET_ROLE, limit=10, profile=profile
)

print("\n================ PLATFORM CALLS ================")
for name in ("Jooble", "JSearch", "SerpAPI"):
    if name in failed:
        print(f"  {name}: FAILED - {failed[name]}")
    elif name in captured:
        print(f"  {name}: {len(captured[name])} results fetched")
    else:
        print(f"  {name}: NOT CALLED (unexpected!)")
print(f"  combined totalFound: {result['totalFound']}")

# ------------------------------------------------------------------
# 4. Ranking proof: independently re-sort the captured pool
# ------------------------------------------------------------------
print("\n================ RANKING PROOF =================")
independent_pool = []
for name, items in captured.items():
    for item in items:
        independent_pool.append(item)

# Mirror production's freshness gate (drop provably-stale, keep undated) so
# the independent sort is an apples-to-apples check of the same pool.
independent_pool = [
    r for r in independent_pool
    if r.get("date") is None or matcher.is_fresh(r["date"])
]
# Mirror production's relevance gate (drop NOT RELEVANT) for the same reason.
independent_pool = [
    r for r in independent_pool
    if r.get("final", {}).get("final_classification") != "NOT RELEVANT"
]
independent_pool.sort(
    key=lambda x: x.get("final", {}).get("final_score", 0), reverse=True
)
independent_top10 = independent_pool[:10]

prod = [(j["title"], j["score"]) for j in result["jobs"]]
indep = [
    (r.get("title", ""), r.get("final", {}).get("final_score", 0))
    for r in independent_top10
]
if prod == indep:
    print("  PASS: production top-10 == independently re-sorted global top-10")
else:
    print("  FAIL: production top-10 does NOT match independent global sort")
    print("  production:", prod)
    print("  independent:", indep)

per_platform_in_top10 = {}
for r in independent_top10:
    per_platform_in_top10[r.get("platform", "?")] = (
        per_platform_in_top10.get(r.get("platform", "?"), 0) + 1
    )
print(f"  platform mix in top-10: {per_platform_in_top10}")

# ------------------------------------------------------------------
# 5. Freshness + relevance audit of the top 10
# ------------------------------------------------------------------
print("\n========== TOP-10 FRESHNESS / RELEVANCE =========")
provably_stale = 0
undated = 0
for j, r in zip(result["jobs"], independent_top10):
    date_val = r.get("date")
    fresh = matcher.is_fresh(date_val)
    age = matcher.days_old(date_val)
    if date_val is None:
        undated += 1
    elif not fresh:
        provably_stale += 1
    print(
        f"  [{r.get('platform', '?'):7}] {j['score']:>3} | "
        f"{j['classification']:<18} | role={j['role_level']:<9} | "
        f"exp={j['experience_match']:<9} | loc={j['location_match']:<12} | "
        f"age={age}d | fresh={fresh}"
    )
    print(f"            title: {j['title'][:70]}")
    print(f"            matched_skills: {j['matched_skills']}")
    print(f"            reason: {j['match_reason'][:100]}")

if provably_stale == 0:
    print("  PASS: no provably-stale listing in the top-10")
else:
    print(f"  FLAG: {provably_stale} top-10 job(s) are provably stale - BUG")
print(f"  [info] {undated} top-10 job(s) have no parseable date (kept by design; 0 freshness points)")

print("\n[verify] done.")
