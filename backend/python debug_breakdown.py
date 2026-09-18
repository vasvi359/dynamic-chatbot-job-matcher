"""
Run from your backend/ folder:

    python debug_breakdown.py

Prints the FULL 'final' dict for the top scored job (not just final_score),
so we can see which scoring category — role match, skills, experience,
location, freshness, apply-link — is contributing 0/low points and dragging
every job down to NOT RELEVANT.

Edit TARGET_ROLE below to match exactly what you typed in the chatbot UI
when you got the AI/ML Engineer results.
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

# <-- CHANGE THIS to exactly what you typed in the chatbot's "Target role" field
TARGET_ROLE = "AI/ML Engineer"

profile = job_search._profile_from_resume(SAMPLE_RESUME)
country = job_search._country_code(profile["country"], profile["location"])

query = TARGET_ROLE.strip()
raw_jobs = job_search._search_jobs(query, profile["location"], country)

scenario = {
    "job_role": TARGET_ROLE,
    "skills": profile["skills"],
    "experience_years": profile["experience_years"],
    "location": profile["location"],
    "country": country,
}
print("SCENARIO SENT TO MATCHER:", scenario)

results = []
for item in raw_jobs[:3]:  # just look at first 3 for readability
    results.append({
        "title": item.get("title", ""),
        "description": item.get("description", ""),
        "apply_link": job_search._apply_link(item),
        "date": job_search._job_date(item),
    })

job_search.matcher.score_results(results, scenario, "SerpAPI")

for r in results:
    print("\n=================================================")
    print("TITLE:", r["title"])
    print("FULL 'final' DICT:")
    for k, v in r.get("final", {}).items():
        print(f"   {k}: {v}")