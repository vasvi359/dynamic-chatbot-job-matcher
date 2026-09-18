import importlib.util
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "").strip()
SERPAPI_URL = "https://serpapi.com/search.json"

MATCHER_PATH = Path(__file__).with_name("submission_small_test_v2.py")
_spec = importlib.util.spec_from_file_location("job_matcher", MATCHER_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Could not load matcher from {MATCHER_PATH}")
matcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(matcher)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

PROFILE_PROMPT = """
Extract a job-search candidate profile from the resume below. Return JSON only:
{
  "skills": ["every concrete technical/tool/technology skill supported by the resume"],
  "experience_years": 0.0,
  "location": "City, Country",
  "country": "two-letter lowercase country code",
  "current_role": "most recent/current job title"
}
Rules:
- Do not invent skills, experience, location, or a role.
- If experience cannot be calculated, use 0.
- If location is absent, use an empty string and empty country.
- Prefer the most recent work experience for current_role.
"""


def _profile_from_resume(resume_text: str) -> dict:
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": PROFILE_PROMPT},
            {"role": "user", "content": f"Resume:\n{resume_text}"},
        ],
    )
    data = json.loads(response.choices[0].message.content)
    skills = data.get("skills") if isinstance(data.get("skills"), list) else []
    return {
        "skills": [str(s).strip() for s in skills if str(s).strip()],
        "experience_years": float(data.get("experience_years") or 0),
        "location": str(data.get("location") or "").strip(),
        "country": str(data.get("country") or "").strip().lower(),
        "current_role": str(data.get("current_role") or "").strip(),
    }


def get_cached_profile(resume_id: int):
    """Return the canonical cached profile for a resume, or None."""
    from db import get_connection

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT profile_data FROM candidate_profiles WHERE resume_id = %s",
            (resume_id,),
        )
        row = cur.fetchone()
        return row["profile_data"] if row else None
    finally:
        cur.close()
        conn.close()


def save_profile(resume_id: int, profile: dict) -> dict:
    """Persist the canonical profile for a resume (computed once per upload)."""
    from db import get_connection

    profile = {
        "skills": profile.get("skills", []),
        "experience_years": profile.get("experience_years", 0),
        "location": profile.get("location", ""),
        "country": profile.get("country", ""),
        "current_role": profile.get("current_role", ""),
    }
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO candidate_profiles (resume_id, profile_data) VALUES (%s, %s)",
            (resume_id, json.dumps(profile)),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()
    return profile


def get_or_create_profile(resume_id: int, resume_text: str) -> dict:
    """Single source of truth for the candidate profile: DB cache first,
    one LLM extraction per resume as fallback."""
    cached = get_cached_profile(resume_id)
    if cached:
        return cached
    return save_profile(resume_id, _profile_from_resume(resume_text))


# ------------------------------------------------------------------
# DEPRECATED SerpAPI helpers — kept ONLY for the debug scripts.
# debug_pipeline.py monkeypatches _search_jobs and debug_breakdown.py
# calls _search_jobs/_apply_link/_job_date directly. The production
# path in find_and_rank_jobs uses the matcher's test_* fetchers instead.
# ------------------------------------------------------------------


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _country_code(country: str, location: str) -> str:
    if country:
        return country.lower()
    low = location.lower()
    mapping = {
        "india": "in", "united states": "us", "usa": "us", "uk": "gb",
        "united kingdom": "gb", "germany": "de", "canada": "ca",
        "australia": "au", "france": "fr", "singapore": "sg",
    }
    for name, code in mapping.items():
        if name in low:
            return code
    return ""


def _apply_link(item: dict) -> str:
    options = item.get("apply_options") or []
    if options and isinstance(options, list):
        first = options[0]
        if isinstance(first, dict) and first.get("link"):
            return first["link"]
    return item.get("share_link") or item.get("link") or ""


def _job_date(item: dict):
    ext = item.get("detected_extensions") or {}
    posted = ext.get("posted_at") or item.get("date")
    if not posted:
        return None
    now = datetime.now(timezone.utc)
    text = str(posted).lower()
    m = re.search(r"(\d+)\s+(day|days|week|weeks|month|months)\s+ago", text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        days = n if "day" in unit else n * 7 if "week" in unit else n * 30
        return now.replace(microsecond=0) - __import__("datetime").timedelta(days=days)
    return _parse_date(posted)


def _search_jobs(query: str, location: str, country: str) -> list:
    if not SERPAPI_KEY:
        raise RuntimeError("SERPAPI_KEY is missing from backend/.env")

    params = {
        "engine": "google_jobs",
        "q": query,
        "api_key": SERPAPI_KEY,
        "hl": "en",
    }
    if location:
        params["location"] = location
    if country:
        params["gl"] = country

    response = requests.get(SERPAPI_URL, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    return payload.get("jobs_results", [])


def _redact_error(message: str) -> str:
    """matcher.clean_error redacts Jooble/JSearch/Adzuna keys but not the
    SerpAPI key (requests errors embed the full signed URL), so add it here."""
    if SERPAPI_KEY:
        message = message.replace(SERPAPI_KEY, "***REDACTED***")
    return message


def _within_seniority_gap(result: dict) -> bool:
    """True if the job's seniority is within 1 level of the candidate's,
    using the matcher's SENIORITY_LEVELS (INTERN=0, JUNIOR/ENTRY=1, MID=2,
    SENIOR=3, LEAD=4, MANAGER=5). Symmetric: gap >= 2 excludes in either
    direction (a fresher won't see senior roles, a senior won't see
    intern/junior roles). Unmapped strings default to level 2 (MID),
    mirroring the matcher's get_seniority_match fallback."""
    final = result.get("final", {})
    job_level = matcher.SENIORITY_LEVELS.get(final.get("job_seniority"), 2)
    cand_level = matcher.SENIORITY_LEVELS.get(final.get("candidate_seniority"), 2)
    return abs(job_level - cand_level) < 2


def find_and_rank_jobs(resume_text: str, target_role: str, limit: int = 10, profile: dict = None) -> dict:
    if profile is None:
        profile = _profile_from_resume(resume_text)
    country = _country_code(profile["country"], profile["location"])
    skills = profile["skills"]

    scenario = {
        "job_role": target_role,
        "skills": skills,
        "experience_years": profile["experience_years"],
        "location": profile["location"],
        "country": country,
    }

    # Reuse the matcher's verified platform fetchers as-is (same result
    # shape: title, description, apply_link, date). The fetchers build their
    # search query via build_query(job_role, skills), so skills=[] makes the
    # query the target role ONLY — the same query the old SerpAPI-only path
    # used. Verified against JSearch: a role-only query returns results while
    # appending the full profile skill list (50+ skills on security-heavy
    # resumes) over-constrains the search and returns zero. Scoring below
    # still uses the FULL skill list via `scenario`.
    fetch_scenario = dict(scenario)
    fetch_scenario["skills"] = []

    fetchers = {
        "Jooble": matcher.test_jooble,
        "JSearch": matcher.test_jsearch,
        "SerpAPI": matcher.test_serpapi,
    }

    combined = []
    platform_notes = []
    platform_counts = {}

    for platform, fetch in fetchers.items():
        try:
            items = fetch(fetch_scenario)
        except Exception as e:
            note = _redact_error(f"{platform}: {matcher.clean_error(e)}")
            platform_notes.append(note)
            print(f"[job_search] platform failed - {note}")
            continue

        # Same fallback the old SerpAPI-only path had: if a location-filtered
        # search returns nothing (e.g. sparse coverage for that location),
        # retry once without location/country before treating the platform
        # as empty.
        if not items and scenario["location"]:
            try:
                fallback_scenario = dict(fetch_scenario)
                fallback_scenario["location"] = ""
                fallback_scenario["country"] = ""
                items = fetch(fallback_scenario)
                if items:
                    print(f"[job_search] {platform}: 0 results with location, "
                          f"retry without location returned {len(items)}")
            except Exception as e:
                note = _redact_error(f"{platform} retry: {matcher.clean_error(e)}")
                platform_notes.append(note)
                print(f"[job_search] platform failed - {note}")
                continue

        platform_counts[platform] = len(items)
        for item in items:
            item["platform"] = platform
            combined.append(item)

    for platform, count in platform_counts.items():
        print(f"[job_search] {platform}: {count} results")
    if platform_notes:
        print("[job_search] platform issues: " + "; ".join(platform_notes))

    if not combined:
        raise RuntimeError(
            "All job platforms failed: "
            + ("; ".join(platform_notes) or "no results from any platform")
        )

    # Score each job with the locked matcher, passing the correct platform
    # string per source (same values run_all() uses). Mirrors score_results'
    # per-result side effects (link_reachable/link_status/final) without
    # touching the matcher itself.
    for result in combined:
        link = result.get("apply_link")
        if matcher.has_apply_link(link):
            if matcher.CHECK_APPLY_LINK_REACHABILITY:
                reachable, status = matcher.check_apply_link(link)
                result["link_reachable"] = reachable
                result["link_status"] = status
            else:
                result["link_reachable"] = False
                result["link_status"] = "not_checked"
        else:
            result["link_reachable"] = False
            result["link_status"] = "missing_or_invalid"

        result["final"] = matcher.calculate_final_score(result, scenario, result["platform"])

    # Freshness gate: drop provably-stale listings (parseable date older
    # than the matcher's 30-day freshness window). Undated listings are KEPT:
    # JSearch omits posting dates entirely for most listings (both
    # job_posted_at fields are None — a data gap, not a parsing issue), and
    # SerpAPI's relative posted_at strings ("X days ago") are converted to
    # None inside the matcher's fetcher, so staleness can't be proven for
    # them from here. They already earn 0 freshness points in scoring, and
    # excluding them would collapse the pool to Jooble-only. KNOWN
    # LIMITATION: expiry filtering is only fully effective on Jooble.
    stale_count = sum(
        1 for r in combined
        if r.get("date") is not None and not matcher.is_fresh(r["date"])
    )
    if stale_count:
        print(f"[job_search] freshness gate: excluding {stale_count} provably-stale listing(s)")
    combined = [
        r for r in combined
        if r.get("date") is None or matcher.is_fresh(r["date"])
    ]

    # Relevance gate: drop jobs the matcher classified NOT RELEVANT (wrong
    # role, wrong seniority) so they can't fill top-N slots. Everything else
    # (APPLY, CHECK, SKILL MATCH ONLY) is kept, then further filtered by the
    # seniority gap gate below. If fewer than `limit` relevant jobs remain,
    # we return fewer; no padding with irrelevant ones. NOTE: no fetch-count
    # lever exists — Jooble/JSearch/SerpAPI fetchers expose no page-size
    # scenario param — so the pool stays at each platform's default page
    # size and the filters shrink it honestly.
    relevant = [
        r for r in combined
        if r.get("final", {}).get("final_classification") != "NOT RELEVANT"
    ]
    not_relevant_count = len(combined) - len(relevant)
    if not_relevant_count:
        print(f"[job_search] relevance gate: excluding {not_relevant_count} "
              f"NOT RELEVANT listing(s), {len(relevant)} relevant remain")

    # Seniority gap gate (alongside the relevance gate above): drop jobs
    # 2+ levels above OR below the candidate's seniority per the matcher's
    # SENIORITY_LEVELS. Gap of 0 or 1 stays — stretch roles in either
    # direction are fine to show. Pure display filter: scoring and
    # classification already happened untouched in the matcher.
    seniority_kept = [r for r in relevant if _within_seniority_gap(r)]
    seniority_gap_count = len(relevant) - len(seniority_kept)
    if seniority_gap_count:
        print(f"[job_search] seniority gate: excluding {seniority_gap_count} "
              f"listing(s) with seniority gap >= 2 levels, "
              f"{len(seniority_kept)} remain")
    relevant = seniority_kept

    # Rank the relevant pool across ALL platforms together, then keep the
    # global top N — not top-N-per-platform.
    relevant.sort(key=lambda x: x.get("final", {}).get("final_score", 0), reverse=True)

    jobs = []
    for result in relevant[:limit]:
        final = result.get("final", {})
        jobs.append({
            "title": result.get("title", ""),
            "description": result.get("description", "")[:600],
            "apply_link": result.get("apply_link", ""),
            "score": final.get("final_score", 0),
            "classification": final.get("final_classification", ""),
            "role_level": final.get("role_level", ""),
            "matched_skills": final.get("matched_skills", []),
            "experience_match": final.get("experience_match", "UNKNOWN"),
            "required_experience": final.get("required_experience", ""),
            "location_match": final.get("location_match", "UNKNOWN"),
            "match_reason": final.get("match_reason", ""),
        })

    return {
        "type": "job_matches",
        "targetRole": target_role,
        "candidate": profile,
        "jobs": jobs,
        "totalFound": len(relevant),
    }