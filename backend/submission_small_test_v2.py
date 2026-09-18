import os
import csv
import re
import requests

from datetime import datetime, timezone
from dotenv import load_dotenv

# ============================================================
# JOB API TESTER - FINAL VERSION
# ============================================================
# This version combines:
# - Jooble, JSearch and Adzuna API testing
# - Role-family matching
# - Skill matching
# - Experience extraction
# - Exact city / country / remote location scoring
# - Freshness scoring
# - Apply-link quality handling
# - 100-point final score
# - APPLY / CHECK / SKILL MATCH ONLY / NOT RELEVANT classification
# - Detailed audit CSV
# ============================================================

load_dotenv()

# ============================================================
# API CREDENTIALS
# ============================================================

JOOBLE_API_KEY = os.getenv("JOOBLE_API_KEY", "").strip()

JSEARCH_API_KEY = os.getenv("JSEARCH_API_KEY", "").strip()
JSEARCH_HOST = "jsearch.p.rapidapi.com"

ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "").strip()
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "").strip()

SERPAPI_API_KEY = os.getenv("SERPAPI_KEY", "").strip()
# ============================================================
# CONFIGURATION
# ============================================================

FRESHNESS_DAYS = 30
API_TIMEOUT = 20
LINK_TIMEOUT = 10

CHECK_APPLY_LINK_REACHABILITY = True

RESULTS_PER_PAGE = 30

# ============================================================
# TEST SCENARIOS
# ============================================================

TEST_SCENARIOS = [
    {
        "job_role": "Software Engineer",
        "skills": ["Python", "AWS", "React"],
        "experience_years": 2,
        "location": "London, UK",
        "country": "gb",
    },
    {
        "job_role": "Data Analyst",
        "skills": ["SQL", "Excel", "Tableau"],
        "experience_years": 2,
        "location": "Berlin, Germany",
        "country": "de",
        "language": "de",
    },
    {
        "job_role": "Frontend Developer",
        "skills": ["JavaScript", "React", "CSS"],
        "experience_years": 2,
        "location": "New York, US",
        "country": "us",
    },
]

# ============================================================
# ROLE FAMILIES
# ============================================================

ROLE_ALIASES = {
    "software engineer": {
        "direct": [
            "software engineer",
            "software developer",
            "application engineer",
            "application developer",
            "product engineer",
        ],
        "related": [
            "full stack engineer",
            "full-stack engineer",
            "fullstack engineer",
            "full stack developer",
            "full-stack developer",
            "fullstack developer",
            "backend engineer",
            "back end engineer",
            "backend developer",
            "back end developer",
            "platform engineer",
            "frontend software engineer",
            "front end software engineer",
            "front-end software engineer",
        ],
        "adjacent": [
            "web developer",
            "web application developer",
            "frontend developer",
            "front end developer",
            "front-end developer",
            "ui developer",
            "ui engineer",
        ],
    },

    "frontend developer": {
        "direct": [
            "frontend developer",
            "front end developer",
            "front-end developer",
            "frontend engineer",
            "front end engineer",
            "front-end engineer",
            "ui developer",
            "ui engineer",
            "react developer",
            "react js developer",
            "reactjs developer",
            "react engineer",
            "react js engineer",
            "reactjs engineer",
        ],
        "related": [
            "frontend software engineer",
            "front end software engineer",
            "front-end software engineer",
            "web application developer",
            "web developer",
        ],
        "adjacent": [
            "interactive developer",
            "software engineer frontend",
            "software engineer front end",
            "software engineer frontend",
        ],
    },

    "data analyst": {
        "direct": [
            "data analyst",
            "analytics analyst",
            "data analytics analyst",
            "business data analyst",
            "reporting analyst",
            "bi analyst",
            "business intelligence analyst",
            "insights analyst",
            "product analyst",
        ],
        "related": [
            "business analyst",
            "business intelligence developer",
            "reporting developer",
        ],
        "adjacent": [
            "data engineer",
            "analytics engineer",
            "database analyst",
        ],
    },
}

# ============================================================
# GENERAL HELPERS
# ============================================================

def build_query(job_role, skills):
    return f"{job_role} {' '.join(skills)}"


def normalize_text(text):
    if not text:
        return ""

    text = str(text).lower()

    text = re.sub(r"[^a-z0-9+#.\-]+", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def parse_datetime(value):
    if not value:
        return None

    try:
        value = str(value).strip()

        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except (ValueError, TypeError):
        return None


def is_fresh(date_value):
    if not date_value:
        return False

    now = datetime.now(timezone.utc)

    age_days = (now - date_value).total_seconds() / 86400

    return 0 <= age_days <= FRESHNESS_DAYS


def days_old(date_value):
    if not date_value:
        return ""

    now = datetime.now(timezone.utc)
    value = (now - date_value).total_seconds() / 86400

    return round(max(0, value), 1)


def has_apply_link(url):
    if not url:
        return False

    url = str(url).strip()

    return url.startswith("http://") or url.startswith("https://")


# ============================================================
# APPLY LINK CHECK
# ============================================================

def check_apply_link(url):
    if not has_apply_link(url):
        return False, "missing_or_invalid"

    try:
        response = requests.get(
            url,
            allow_redirects=True,
            timeout=LINK_TIMEOUT,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                )
            },
            stream=True,
        )

        status = response.status_code
        response.close()

        if status < 400:
            return True, f"HTTP {status}"

        if status in (401, 403, 429):
            # The server responded, so the destination is reachable.
            # Automated access was blocked/rate-limited.
            return True, f"HTTP {status} (server reachable; access blocked/limited)"

        return False, f"HTTP {status}"

    except requests.Timeout:
        return False, "timeout"

    except requests.ConnectionError:
        return False, "connection_error"

    except requests.RequestException as error:
        return False, type(error).__name__


# ============================================================
# ROLE MATCHING
# ============================================================

def get_role_aliases(job_role):
    normalized_role = normalize_text(job_role)

    family = ROLE_ALIASES.get(normalized_role)

    if not family:
        return {
            "direct": [normalized_role],
            "related": [],
            "adjacent": [],
        }

    return {
        key: [normalize_text(x) for x in values]
        for key, values in family.items()
    }


def title_contains_alias(title_text, alias):
    if not alias:
        return False

    pattern = (
        r"(?<![a-z0-9])"
        + re.escape(alias)
        + r"(?![a-z0-9])"
    )

    return bool(re.search(pattern, title_text))


def get_role_match_level(title, job_role, description=""):
    """
    Determine role match from the job title.

    If the title is generic/unhelpful, inspect the description
    for the actual role.
    """
    title_text = normalize_text(title)
    description_text = normalize_text(description)

    aliases = get_role_aliases(job_role)

    # First check the title.
    if title_text:
        for alias in aliases["direct"]:
            if title_contains_alias(title_text, alias):
                return "DIRECT"

        for alias in aliases["related"]:
            if title_contains_alias(title_text, alias):
                return "RELATED"

        for alias in aliases["adjacent"]:
            if title_contains_alias(title_text, alias):
                return "ADJACENT"

    # Generic titles should fall back to the description.
    generic_titles = {
        "teams",
        "team",
        "job",
        "position",
        "role",
        "career",
        "careers",
        "opportunity",
        "opening",
        "hiring",
    }

    if title_text in generic_titles and description_text:
        for alias in aliases["direct"]:
            if title_contains_alias(description_text, alias):
                return "DIRECT"

        for alias in aliases["related"]:
            if title_contains_alias(description_text, alias):
                return "RELATED"

        for alias in aliases["adjacent"]:
            if title_contains_alias(description_text, alias):
                return "ADJACENT"

    return "NONE"


def role_matches_title(title, job_role, description=""):
    return get_role_match_level(
        title,
        job_role,
        description,
    ) in ("DIRECT", "RELATED")


def role_similarity_score(title, job_role, description=""):
    level = get_role_match_level(
        title,
        job_role,
        description,
    )

    return {
        "DIRECT": 1.0,
        "RELATED": 0.75,
        "ADJACENT": 0.4,
        "NONE": 0.0,
    }.get(level, 0.0)


# ============================================================
# SENIORITY MATCHING
# ============================================================

SENIORITY_LEVELS = {
    "INTERN": 0,
    "JUNIOR": 1,
    "ENTRY": 1,
    "MID": 2,
    "SENIOR": 3,
    "LEAD": 4,
    "MANAGER": 5,
}


def get_job_seniority(title, description):
    """Detect job seniority, prioritizing an explicit job title."""
    title_text = normalize_text(title)
    description_text = normalize_text(description)

    def detect(text):
        if re.search(r"\b(intern|internship|trainee)\b", text):
            return "INTERN"
        if re.search(r"\b(lead|principal|staff)\b", text):
            return "LEAD"
        if re.search(r"\b(manager|head|director)\b", text):
            return "MANAGER"
        if re.search(r"\b(senior|sr)\b", text):
            return "SENIOR"
        if re.search(r"\b(junior|jr|entry level|entry-level)\b", text):
            return "JUNIOR"
        if re.search(r"\b(mid|mid-level|mid level)\b", text):
            return "MID"
        return None

    # Explicit title information is more reliable than arbitrary words
    # appearing later in a long description.
    title_level = detect(title_text)
    if title_level:
        return title_level

    generic_titles = {
        "teams", "team", "job", "position", "role", "career",
        "careers", "opportunity", "opening", "hiring",
    }

    if title_text in generic_titles:
        description_level = detect(description_text)
        if description_level:
            return description_level

    return "MID"


def get_candidate_seniority(experience_years):
    """Estimate candidate seniority from years of experience."""
    try:
        years = float(experience_years)
    except (TypeError, ValueError):
        return "MID"

    if years < 1:
        return "INTERN"
    if years < 2:
        return "JUNIOR"
    if years < 5:
        return "MID"
    if years < 8:
        return "SENIOR"
    return "LEAD"


def get_seniority_match(job_seniority, candidate_seniority):
    job_level = SENIORITY_LEVELS.get(job_seniority, 2)
    candidate_level = SENIORITY_LEVELS.get(candidate_seniority, 2)

    if job_level == candidate_level:
        return "MATCH"
    if job_level > candidate_level:
        return "MISMATCH"
    return "OVERQUALIFIED"


# ============================================================
# SKILL MATCHING
# ============================================================

def get_matched_skills(title, description, skills):
    title_text = normalize_text(title)
    description_text = normalize_text(description)

    full_text = f"{title_text} {description_text}"

    matched_skills = []

    for skill in skills:
        skill_text = normalize_text(skill)

        if not skill_text:
            continue

        # Normalize common technology spellings.
        alternatives = [skill_text]

        if skill_text == "aws":
            alternatives += ["amazon web services"]

        elif skill_text == "react":
            alternatives += ["reactjs", "react js"]

        elif skill_text == "javascript":
            alternatives += ["javascript", "js"]

        elif skill_text == "css":
            alternatives += ["css3"]

        elif skill_text == "sql":
            alternatives += ["structured query language"]

        found = False

        for alternative in alternatives:
            pattern = (
                r"(?<![a-z0-9])"
                + re.escape(alternative)
                + r"(?![a-z0-9])"
            )

            if re.search(pattern, full_text):
                found = True
                break

        if found:
            matched_skills.append(skill)

    return matched_skills


# ============================================================
# RELEVANCE
# ============================================================

def get_relevance(title, description, job_role, skills):
    role_level = get_role_match_level(
        title,
        job_role,
        description,
    )

    matched_skills = get_matched_skills(
        title,
        description,
        skills,
    )

    skill_count = len(matched_skills)

    if role_level in ("DIRECT", "RELATED") and skill_count >= 2:
        classification = "STRONG"

    elif role_level in ("DIRECT", "RELATED") and skill_count == 1:
        classification = "MODERATE"

    elif role_level in ("DIRECT", "RELATED"):
        classification = "ROLE_MATCH"

    elif skill_count > 0:
        classification = "SKILL_ONLY"

    else:
        classification = "NOT_RELEVANT"

    return {
        "classification": classification,
        "relevant": role_level in ("DIRECT", "RELATED"),
        "matched_skills": matched_skills,
        "skill_count": skill_count,
        "role_match": role_level in ("DIRECT", "RELATED"),
        "role_level": role_level,
    }


# ============================================================
# EXPERIENCE MATCHING
# ============================================================

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def extract_number(value):
    value = str(value).lower().strip()

    if value in NUMBER_WORDS:
        return float(NUMBER_WORDS[value])

    try:
        return float(value)
    except ValueError:
        return None


def get_experience_match(description, candidate_years):
    """Match explicit experience requirements and common seniority wording."""
    if not description:
        return "UNKNOWN", ""

    text = normalize_text(description)
    try:
        candidate_years = float(candidate_years)
    except (TypeError, ValueError):
        candidate_years = None

    # Internship is an explicit lower-level requirement.
    if re.search(r"\b(intern|internship|trainee)\b", text):
        if candidate_years is not None and candidate_years >= 1:
            return "MISMATCH", "Internship"
        return "MATCH", "Internship"

    # Ranges: 2-4 years / 2 to 4 years.
    range_pattern = (
        r"\b(\d+(?:\.\d+)?)\s*(?:-|to|–)\s*"
        r"(\d+(?:\.\d+)?)\s*(?:years?|yrs?)"
    )
    match = re.search(range_pattern, text)
    if match:
        minimum = float(match.group(1))
        maximum = float(match.group(2))
        if candidate_years is None:
            return "UNKNOWN", f"{minimum:g}-{maximum:g} years"
        return (
            "MATCH" if minimum <= candidate_years <= maximum else "MISMATCH",
            f"{minimum:g}-{maximum:g} years",
        )

    # Minimums: 3+ years, 3 years of experience, at least 3 years.
    minimum_patterns = [
        r"\b(\d+(?:\.\d+)?)\s*\+\s*(?:years?|yrs?)",
        r"\b(\d+(?:\.\d+)?)\s*(?:years?|yrs?)\s*(?:of\s+)?experience\b",
        r"(?:minimum|at least|required|requires|need|needs).{0,60}?"
        r"(\d+(?:\.\d+)?)\s*(?:years?|yrs?)",
    ]

    for pattern in minimum_patterns:
        match = re.search(pattern, text)
        if match:
            required = float(match.group(1))
            if candidate_years is None:
                return "UNKNOWN", f"{required:g}+ years"
            return (
                "MATCH" if candidate_years >= required else "MISMATCH",
                f"{required:g}+ years",
            )

    # Descriptive seniority.
    if re.search(r"\b(lead|principal|staff|manager|senior|sr)\b", text):
        if candidate_years is None:
            return "UNKNOWN", "Senior/lead role"
        return (
            "MATCH" if candidate_years >= 5 else "MISMATCH",
            "Senior/lead role",
        )

    if re.search(r"\b(mid|mid-level|mid level)\b", text):
        if candidate_years is None:
            return "UNKNOWN", "Mid-level"
        return (
            "MATCH" if 2 <= candidate_years < 5 else "MISMATCH",
            "Mid-level",
        )

    return "UNKNOWN", ""


# ============================================================
# LOCATION MATCHING
# ============================================================

COUNTRY_TERMS = {
    "uk": [
        "uk",
        "gb",
        "united kingdom",
        "england",
        "great britain",
    ],
    "gb": [
        "uk",
        "gb",
        "united kingdom",
        "england",
        "great britain",
    ],
    "germany": [
        "germany",
        "de",
        "deutschland",
    ],
    "de": [
        "germany",
        "de",
        "deutschland",
    ],
    "us": [
        "us",
        "usa",
        "united states",
        "united states of america",
    ],
}


def get_location_match(title, description, scenario):
    requested_location = scenario.get("location", "").strip()

    if not requested_location:
        return "UNKNOWN", ""

    parts = [x.strip() for x in requested_location.split(",")]

    city = normalize_text(parts[0]) if parts else ""

    country_code = normalize_text(
        scenario.get("country", "")
    )

    country_name = (
        normalize_text(parts[-1])
        if parts
        else ""
    )

    text = normalize_text(
        f"{title} {description}"
    )

    # Remote is useful even when city is not mentioned.
    remote_terms = [
        "remote",
        "work from home",
        "working remotely",
        "fully remote",
        "remote working",
        "remote position",
    ]

    if any(term in text for term in remote_terms):
        return "REMOTE", "Remote role"

    # Exact city.
    if city and city in text:
        return "EXACT_CITY", f"City match: {parts[0]}"

    # Same country.
    terms = COUNTRY_TERMS.get(
        country_code,
        [country_name] if country_name else [],
    )

    for term in terms:
        if term and term in text:
            return "SAME_COUNTRY", "Same country, different city"

    # If country is not mentioned, do not call it mismatch.
    return "UNKNOWN", "Location not stated clearly"


# ============================================================
# LINK QUALITY
# ============================================================

def get_link_quality(result):
    link = result.get("apply_link", "")

    if not has_apply_link(link):
        return "MISSING", 0

    status = result.get("link_status", "")

    if result.get("link_reachable") is True:
        return "USABLE", 5

    if "403" in status or "401" in status or "429" in status:
        return "BLOCKED", 3

    if status in ("timeout", "connection_error"):
        return "UNVERIFIED", 3

    return "UNVERIFIED", 3


# ============================================================
# FINAL SCORING
# ============================================================

def calculate_final_score(
    result,
    scenario,
    platform,
):
    title = result.get("title", "")
    description = result.get("description", "")

    relevance = get_relevance(
        title,
        description,
        scenario["job_role"],
        scenario["skills"],
    )

    experience, required_experience = get_experience_match(
        description,
        scenario["experience_years"],
    )

    location, location_reason = get_location_match(
        title,
        description,
        scenario,
    )

    candidate_seniority = get_candidate_seniority(
        scenario["experience_years"]
    )

    job_seniority = get_job_seniority(
        title,
        description,
    )

    seniority_match = get_seniority_match(
        job_seniority,
        candidate_seniority,
    )

    role_level = relevance["role_level"]
    skill_count = relevance["skill_count"]
    total_skills = len(scenario["skills"])

    # ROLE: 35 points
    role_points = {
        "DIRECT": 35,
        "RELATED": 28,
        "ADJACENT": 12,
        "NONE": 0,
    }.get(role_level, 0)

    # SKILLS: 30 points
    if total_skills:
        skill_points = round(
            30 * skill_count / total_skills
        )
    else:
        skill_points = 0

    # EXPERIENCE: 15 points
    if experience == "MATCH":
        experience_points = 15
    elif experience == "UNKNOWN":
        experience_points = 8
    else:
        experience_points = 0

    # LOCATION: 10 points
    location_points = {
        "EXACT_CITY": 10,
        "REMOTE": 10,
        "SAME_COUNTRY": 6,
        "UNKNOWN": 4,
        "MISMATCH": 0,
    }.get(location, 0)

    # FRESHNESS: 5 points
    date_value = result.get("date")

    if is_fresh(date_value):
        freshness_points = 5
    elif date_value:
        freshness_points = 0
    else:
        freshness_points = 2

    # APPLY LINK: 5 points
    link_quality, link_points = get_link_quality(result)

    # Seniority penalty.
    seniority_penalty = 0

    if seniority_match == "MISMATCH":
        seniority_penalty = 15
    elif seniority_match == "OVERQUALIFIED":
        seniority_penalty = 12

    raw_score = (
        role_points
        + skill_points
        + experience_points
        + location_points
        + freshness_points
        + link_points
        - seniority_penalty
    )

    # Classification safeguards.
    if role_level == "NONE" and skill_count > 0:
        final_score = min(raw_score, 59)
        final_classification = "SKILL MATCH ONLY"

    elif role_level == "NONE":
        final_score = min(raw_score, 39)
        final_classification = "NOT RELEVANT"

    elif role_level == "ADJACENT":
        final_score = min(raw_score, 64)
        final_classification = (
            "CHECK" if final_score >= 45
            else "NOT RELEVANT"
        )

    elif experience == "MISMATCH":
        final_score = min(raw_score, 69)
        final_classification = (
            "CHECK" if final_score >= 50
            else "NOT RELEVANT"
        )

    elif seniority_match == "MISMATCH":
        final_score = min(raw_score, 69)
        final_classification = (
            "CHECK" if final_score >= 50
            else "NOT RELEVANT"
        )

    elif raw_score >= 80:
        final_score = raw_score
        final_classification = "APPLY"

    elif raw_score >= 65:
        final_score = raw_score
        final_classification = "CHECK"

    elif role_level in ("DIRECT", "RELATED"):
        final_score = raw_score
        final_classification = "CHECK"

    else:
        final_score = raw_score
        final_classification = "NOT RELEVANT"

    # Match reason.
    reason_parts = []

    if role_level == "DIRECT":
        reason_parts.append("Direct role match")
    elif role_level == "RELATED":
        reason_parts.append("Related role match")
    elif role_level == "ADJACENT":
        reason_parts.append("Adjacent role")
    else:
        reason_parts.append("No role match")

    if total_skills:
        reason_parts.append(
            f"{skill_count}/{total_skills} skills matched"
        )

    if experience == "MATCH":
        reason_parts.append("Experience matches")
    elif experience == "MISMATCH":
        reason_parts.append("Experience requirement not met")
    else:
        reason_parts.append("Experience unknown")

    reason_parts.append(
        f"Job seniority: {job_seniority}"
    )
    reason_parts.append(
        f"Candidate seniority: {candidate_seniority}"
    )

    if seniority_match == "MATCH":
        reason_parts.append("Seniority matches")
    elif seniority_match == "MISMATCH":
        reason_parts.append("Seniority mismatch")
    else:
        reason_parts.append("Candidate may be overqualified")

    if location_reason:
        reason_parts.append(location_reason)

    if is_fresh(date_value):
        reason_parts.append(
            f"Within {FRESHNESS_DAYS} days"
        )

    if link_quality == "BLOCKED":
        reason_parts.append(
            "Application link blocked by automated check"
        )
    elif link_quality == "MISSING":
        reason_parts.append(
            "Application link missing"
        )

    return {
        "role_level": role_level,
        "role_similarity_score": role_similarity_score(
            title,
            scenario["job_role"],
            description,
        ),
        "matched_skills": relevance["matched_skills"],
        "skill_count": skill_count,
        "classification": relevance["classification"],
        "relevant": relevance["relevant"],
        "experience_match": experience,
        "required_experience": required_experience,
        "location_match": location,
        "location_reason": location_reason,
        "link_quality": link_quality,
        "job_seniority": job_seniority,
        "candidate_seniority": candidate_seniority,
        "seniority_match": seniority_match,
        "seniority_penalty": seniority_penalty,
        "role_points": role_points,
        "skill_points": skill_points,
        "experience_points": experience_points,
        "location_points": location_points,
        "freshness_points": freshness_points,
        "link_points": link_points,
        "final_score": final_score,
        "final_classification": final_classification,
        "match_reason": "; ".join(reason_parts),
    }


# ============================================================
# SCORE ALL RESULTS
# ============================================================

def score_results(results, scenario, platform):
    total = len(results)

    with_apply_link = 0
    reachable_apply_links = 0
    fresh = 0
    relevant = 0
    strong = 0
    moderate = 0
    role_only = 0
    skill_only = 0

    experience_match = 0
    experience_mismatch = 0
    experience_unknown = 0

    location_exact = 0
    location_remote = 0
    location_country = 0
    location_unknown = 0

    apply_classification = 0
    check_classification = 0

    for result in results:

        link = result.get("apply_link")

        if has_apply_link(link):
            with_apply_link += 1

            if CHECK_APPLY_LINK_REACHABILITY:
                reachable, status = check_apply_link(link)

                result["link_reachable"] = reachable
                result["link_status"] = status

                if reachable:
                    reachable_apply_links += 1
            else:
                result["link_reachable"] = False
                result["link_status"] = "not_checked"

        else:
            result["link_reachable"] = False
            result["link_status"] = "missing_or_invalid"

        if is_fresh(result.get("date")):
            fresh += 1

        final = calculate_final_score(
            result,
            scenario,
            platform,
        )

        result["final"] = final

        if final["relevant"]:
            relevant += 1

        if final["classification"] == "STRONG":
            strong += 1
        elif final["classification"] == "MODERATE":
            moderate += 1
        elif final["classification"] == "ROLE_MATCH":
            role_only += 1
        elif final["classification"] == "SKILL_ONLY":
            skill_only += 1

        if final["experience_match"] == "MATCH":
            experience_match += 1
        elif final["experience_match"] == "MISMATCH":
            experience_mismatch += 1
        else:
            experience_unknown += 1

        location = final["location_match"]

        if location == "EXACT_CITY":
            location_exact += 1
        elif location == "REMOTE":
            location_remote += 1
        elif location == "SAME_COUNTRY":
            location_country += 1
        else:
            location_unknown += 1

        if final["final_classification"] == "APPLY":
            apply_classification += 1
        elif final["final_classification"] == "CHECK":
            check_classification += 1

    if platform == "Jooble":
        freshness_definition = "Updated within 30 days"
    else:
        freshness_definition = "Posted within 30 days"

    return {
        "total": total,
        "with_apply_link": with_apply_link,
        "reachable_apply_links": reachable_apply_links,
        "fresh": fresh,
        "relevant": relevant,
        "strong": strong,
        "moderate": moderate,
        "role_only": role_only,
        "skill_only": skill_only,
        "experience_match": experience_match,
        "experience_mismatch": experience_mismatch,
        "experience_unknown": experience_unknown,
        "location_exact": location_exact,
        "location_remote": location_remote,
        "location_country": location_country,
        "location_unknown": location_unknown,
        "apply_classification": apply_classification,
        "check_classification": check_classification,
        "freshness_definition": freshness_definition,
    }


# ============================================================
# JOOBLE
# ============================================================

def test_jooble(scenario):
    if not JOOBLE_API_KEY:
        raise RuntimeError(
            "NOT CONFIGURED: Jooble API key is missing."
        )

    url = f"https://jooble.org/api/{JOOBLE_API_KEY}"

    body = {
        "keywords": build_query(
            scenario["job_role"],
            scenario["skills"],
        ),
        "location": scenario["location"],
        "page": "1",
    }

    response = requests.post(
        url,
        json=body,
        headers={"Content-Type": "application/json"},
        timeout=API_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    results = []

    for job in data.get("jobs", []):
        updated_date = parse_datetime(
            job.get("updated")
        )

        results.append({
            "title": job.get("title", ""),
            "description": job.get("snippet", ""),
            "apply_link": job.get("link", ""),
            "date": updated_date,
        })

    return results


# ============================================================
# JSEARCH
# ============================================================

def test_jsearch(scenario):
    if not JSEARCH_API_KEY:
        raise RuntimeError(
            "NOT CONFIGURED: JSearch API key is missing."
        )

    url = f"https://{JSEARCH_HOST}/search-v2"

    city = scenario["location"].split(",")[0].strip()

    query = (
        f"{build_query(scenario['job_role'], scenario['skills'])} "
        f"in {city}"
    )

    params = {
        "query": query,
        "page": "1",
        "num_pages": "1",
        "country": scenario.get("country", "us"),
    }

    if scenario.get("language"):
        params["language"] = scenario["language"]

    headers = {
        "X-RapidAPI-Key": JSEARCH_API_KEY,
        "X-RapidAPI-Host": JSEARCH_HOST,
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=API_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if data.get("status") not in (None, "OK"):
        print(
            f"JSearch API status: {data.get('status')}"
        )

    jobs = data.get("data", [])

    if isinstance(jobs, dict):
        jobs = jobs.get("jobs", [])

    if not isinstance(jobs, list):
        jobs = []

    results = []

    for job in jobs:
        posted_date = parse_datetime(
            job.get("job_posted_at_datetime_utc")
        )

        results.append({
            "title": job.get("job_title", ""),
            "description": job.get("job_description", ""),
            "apply_link": job.get("job_apply_link", ""),
            "date": posted_date,
        })

    return results


# ============================================================
# ADZUNA
# ============================================================

def adzuna_is_configured():
    invalid_values = {
        "",
        "your_actual_adzuna_id",
        "your_actual_adzuna_key",
        "***REDACTED***",
        "your_adzuna_app_id",
        "your_adzuna_app_key",
    }

    return (
        ADZUNA_APP_ID not in invalid_values
        and ADZUNA_APP_KEY not in invalid_values
    )


def test_adzuna(scenario):
    if not adzuna_is_configured():
        raise RuntimeError(
            "NOT CONFIGURED: "
            "Adzuna API credentials unavailable."
        )

    country = scenario.get("country", "gb")

    url = (
        "https://api.adzuna.com/"
        "v1/api/jobs/"
        f"{country}/search/1"
    )

    city = scenario["location"].split(",")[0].strip()

    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "what": build_query(
            scenario["job_role"],
            scenario["skills"],
        ),
        "where": city,
        "max_days_old": FRESHNESS_DAYS * 2,
        "results_per_page": 20,
    }

    response = requests.get(
        url,
        params=params,
        timeout=API_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    results = []

    for job in data.get("results", []):
        posted_date = parse_datetime(
            job.get("created")
        )

        results.append({
            "title": job.get("title", ""),
            "description": job.get("description", ""),
            "apply_link": job.get("redirect_url", ""),
            "date": posted_date,
        })

    return results


# ============================================================
# SERPAPI
# ============================================================

def test_serpapi(scenario):
    if not SERPAPI_API_KEY:
        raise RuntimeError("NOT CONFIGURED: SerpAPI key is missing.")

    url = "https://serpapi.com/search"

    params = {
        "engine": "google_jobs",
        "q": build_query(scenario["job_role"], scenario["skills"]),
        "location": scenario["location"],
        "api_key": SERPAPI_API_KEY,
    }

    response = requests.get(url, params=params, timeout=API_TIMEOUT)
    response.raise_for_status()
    data = response.json()

    results = []
    for job in data.get("jobs_results", []):
        posted_date = parse_datetime(job.get("detected_extensions", {}).get("posted_at"))
        apply_link = ""
        apply_options = job.get("apply_options", [])
        if apply_options:
            apply_link = apply_options[0].get("link", "")

        results.append({
            "title": job.get("title", ""),
            "description": job.get("description", ""),
            "apply_link": apply_link,
            "date": posted_date,
        })

    return results


# ============================================================
# ERROR CLEANING
# ============================================================

def clean_error(error):
    message = str(error)

    secrets = [
        JOOBLE_API_KEY,
        JSEARCH_API_KEY,
        ADZUNA_APP_ID,
        ADZUNA_APP_KEY,
    ]

    for secret in secrets:
        if secret:
            message = message.replace(
                secret,
                "***REDACTED***",
            )

    return message


# ============================================================
# DETAILED JOB ROWS
# ============================================================

def create_job_detail_rows(results, scenario, platform, test_number):
    rows = []

    for result in results:
        title = result.get("title", "")
        description = result.get("description", "")

        final = result.get("final")

        if not final:
            final = calculate_final_score(
                result,
                scenario,
                platform,
            )

        date_value = result.get("date")

        rows.append({
            "Platform": platform,
            "Test #": test_number,
            "Job Role": scenario["job_role"],
            "Skills": ", ".join(scenario["skills"]),
            "Experience (yrs)": scenario["experience_years"],
            "Location": scenario["location"],

            "Job Title": title,

            "Description Preview": (
                str(description)
                .replace("\n", " ")
                .replace("\r", " ")
                [:1000]
            ),

            "Posted / Updated": (
                date_value.isoformat()
                if date_value
                else ""
            ),

            "Fresh <30 Days": (
                "YES" if is_fresh(date_value) else "NO"
            ),

            "Days Old": days_old(date_value),

            "Apply Link": result.get("apply_link", ""),

            "Link Reachable": (
                "YES"
                if result.get("link_reachable") is True
                else "NO"
            ),

            "Link Status": result.get(
                "link_status",
                "",
            ),

            "Link Quality": final["link_quality"],

            "Result Location": final["location_match"],

            "Location Reason": final["location_reason"],

            "Role Match": (
                "YES"
                if final["role_level"] in (
                    "DIRECT",
                    "RELATED",
                )
                else "NO"
            ),

            "Role Similarity Score": (
                final["role_similarity_score"]
            ),

            "Matched Skills": ", ".join(
                final["matched_skills"]
            ),

            "Skill Count": final["skill_count"],

            "Classification": final["classification"],

            "Relevant": (
                "YES"
                if final["relevant"]
                else "NO"
            ),

            "Experience Match": final["experience_match"],

            "Required Experience": (
                final["required_experience"]
            ),

            "Role Level": final["role_level"],

            "Job Seniority": final["job_seniority"],
            "Candidate Seniority": final["candidate_seniority"],
            "Seniority Match": final["seniority_match"],
            "Seniority Penalty": final["seniority_penalty"],

            "Role Points": final["role_points"],
            "Skill Points": final["skill_points"],
            "Experience Points": final["experience_points"],
            "Location Points": final["location_points"],
            "Freshness Points": final["freshness_points"],
            "Link Points": final["link_points"],

            "Total Skills Requested": len(
                scenario["skills"]
            ),

            "Freshness": (
                "YES"
                if is_fresh(date_value)
                else "NO"
            ),

            "Final Score": final["final_score"],

            "Final Classification": (
                final["final_classification"]
            ),

            "Match Reason": final["match_reason"],
        })

    return rows


# ============================================================
# SUMMARY
# ============================================================

def create_summary(csv_rows):
    platforms = {}

    for row in csv_rows:
        platform = row["Platform"]
        platforms.setdefault(platform, []).append(row)

    summary_rows = []

    for platform, rows in platforms.items():
        tested_rows = [
            row for row in rows
            if row["# Results Returned"] != "N/A"
        ]

        if not tested_rows:
            summary_rows.append({
                "Platform": platform,
                "Tests Completed": 0,
                "Average Results Returned": "N/A",
                "Apply Link Availability": "N/A",
                "Freshness": "N/A",
                "Relevance": "N/A",
                "Relevant Job Rate": "N/A",
                "Apply Recommendations": "N/A",
                "Check Recommendations": "N/A",
                "Status": "Not Tested",
                "Notes": "API credentials unavailable.",
            })
            continue

        total_results = sum(
            int(row["# Results Returned"])
            for row in tested_rows
        )

        total_relevant = sum(
            int(row["# Relevant Matches"])
            for row in tested_rows
        )

        total_apply = sum(
            int(row["# APPLY"])
            for row in tested_rows
        )

        total_check = sum(
            int(row["# CHECK"])
            for row in tested_rows
        )

        total_fresh = sum(
            int(row["# Fresh <30 Days"])
            for row in tested_rows
        )

        average_results = (
            total_results / len(tested_rows)
        )

        relevant_rate = (
            total_relevant / total_results * 100
            if total_results
            else 0
        )

        freshness_rate = (
            total_fresh / total_results * 100
            if total_results
            else 0
        )

        apply_rate = (
            total_apply / total_results * 100
            if total_results
            else 0
        )

        if relevant_rate >= 80:
            relevance_quality = "Strong"
        elif relevant_rate >= 50:
            relevance_quality = "Good"
        else:
            relevance_quality = "Needs Review"

        if freshness_rate >= 70:
            freshness_quality = "Good"
        elif freshness_rate >= 40:
            freshness_quality = "Mixed"
        else:
            freshness_quality = "Low"

        if apply_rate >= 30:
            apply_quality = "Strong"
        elif apply_rate > 0:
            apply_quality = "Some"
        else:
            apply_quality = "None"

        summary_rows.append({
            "Platform": platform,
            "Tests Completed": len(tested_rows),
            "Average Results Returned": round(
                average_results,
                1,
            ),
            "Apply Link Availability": apply_quality,
            "Freshness": freshness_quality,
            "Relevance": relevance_quality,
            "Relevant Job Rate": f"{relevant_rate:.1f}%",
            "Apply Recommendations": total_apply,
            "Check Recommendations": total_check,
            "Status": "Tested",
            "Notes": "",
        })

    return summary_rows


# ============================================================
# MAIN RUNNER
# ============================================================

def run_all():
    platforms = {
        "Jooble": test_jooble,
        "JSearch": test_jsearch,
        "SerpAPI": test_serpapi,
    }

    csv_rows = []
    detailed_job_rows = []

    for test_number, scenario in enumerate(
        TEST_SCENARIOS,
        1,
    ):
        print()
        print("=" * 70)
        print(f"TEST SCENARIO {test_number}")
        print(f"Role: {scenario['job_role']}")
        print(
            f"Skills: {', '.join(scenario['skills'])}"
        )
        print(
            f"Experience: "
            f"{scenario['experience_years']} years"
        )
        print(
            f"Location: {scenario['location']}"
        )
        print("=" * 70)

        # Accumulate this scenario's job rows across all platforms so
        # ranking/top-10 (added below) considers every source together,
        # not just whichever platform happened to run last.
        scenario_job_rows = []

        for platform, function in platforms.items():
            print()
            print(f"--- {platform} ---")

            row = {
                "Platform": platform,
                "Test #": test_number,
                "Job Role": scenario["job_role"],
                "Skills": ", ".join(
                    scenario["skills"]
                ),
                "Experience (yrs)": scenario[
                    "experience_years"
                ],
                "Location": scenario["location"],

                "# Results Returned": "N/A",
                "# With Apply Link": "N/A",
                "# Reachable Apply Links": "N/A",
                "# Fresh <30 Days": "N/A",

                "# Relevant Matches": "N/A",
                "# Strong Relevant": "N/A",
                "# Moderate Relevant": "N/A",
                "# Role Match Only": "N/A",
                "# Skill Only": "N/A",

                "# APPLY": "N/A",
                "# CHECK": "N/A",

                "# Experience MATCH": "N/A",
                "# Experience MISMATCH": "N/A",
                "# Experience UNKNOWN": "N/A",

                "Freshness Definition": "N/A",
                "Notes / Issues": "",
            }

            try:
                results = function(scenario)

                scores = score_results(
                    results,
                    scenario,
                    platform,
                )

                detail_rows = create_job_detail_rows(
                    results,
                    scenario,
                    platform,
                    test_number,
                )

                scenario_job_rows.extend(detail_rows)

                print(
                    f"Results returned: "
                    f"{scores['total']}"
                )

                print(
                    f"Relevant: "
                    f"{scores['relevant']}"
                )

                print(
                    f"APPLY: "
                    f"{scores['apply_classification']}"
                )

                print(
                    f"CHECK: "
                    f"{scores['check_classification']}"
                )

                print(
                    f"Fresh: "
                    f"{scores['fresh']}"
                )

                print(
                    f"Experience MATCH: "
                    f"{scores['experience_match']}"
                )

                print(
                    f"Experience MISMATCH: "
                    f"{scores['experience_mismatch']}"
                )

                print(
                    f"Experience UNKNOWN: "
                    f"{scores['experience_unknown']}"
                )

                row.update({
                    "# Results Returned": scores["total"],
                    "# With Apply Link": scores[
                        "with_apply_link"
                    ],
                    "# Reachable Apply Links": scores[
                        "reachable_apply_links"
                    ],
                    "# Fresh <30 Days": scores["fresh"],

                    "# Relevant Matches": scores[
                        "relevant"
                    ],
                    "# Strong Relevant": scores[
                        "strong"
                    ],
                    "# Moderate Relevant": scores[
                        "moderate"
                    ],
                    "# Role Match Only": scores[
                        "role_only"
                    ],
                    "# Skill Only": scores[
                        "skill_only"
                    ],

                    "# APPLY": scores[
                        "apply_classification"
                    ],
                    "# CHECK": scores[
                        "check_classification"
                    ],

                    "# Experience MATCH": scores[
                        "experience_match"
                    ],
                    "# Experience MISMATCH": scores[
                        "experience_mismatch"
                    ],
                    "# Experience UNKNOWN": scores[
                        "experience_unknown"
                    ],

                    "Freshness Definition": scores[
                        "freshness_definition"
                    ],
                })

                if scores["total"] == 0:
                    row["Notes / Issues"] = (
                        "API succeeded but "
                        "returned 0 jobs."
                    )

                elif (
                    scores["with_apply_link"] > 0
                    and scores["reachable_apply_links"] == 0
                    and CHECK_APPLY_LINK_REACHABILITY
                ):
                    row["Notes / Issues"] = (
                        "Apply URLs were present, "
                        "but automated reachability "
                        "checks were blocked/unverified. "
                        "This does not prove the URLs "
                        "are broken."
                    )

            except RuntimeError as error:
                message = clean_error(error)
                print(message)
                row["Notes / Issues"] = message

            except requests.HTTPError as error:
                message = clean_error(error)
                print(f"API ERROR: {message}")
                row["Notes / Issues"] = (
                    f"API ERROR: {message}"
                )

            except requests.RequestException as error:
                message = clean_error(error)
                print(f"REQUEST ERROR: {message}")
                row["Notes / Issues"] = (
                    f"REQUEST ERROR: {message}"
                )

            except Exception as error:
                message = clean_error(error)
                print(
                    f"ERROR: "
                    f"{type(error).__name__}: "
                    f"{message}"
                )
                row["Notes / Issues"] = (
                    f"ERROR: "
                    f"{type(error).__name__}: "
                    f"{message}"
                )

            csv_rows.append(row)

        # ====================================================
        # RANKING + TOP 10 (added)
        #
        # Sort this scenario's combined jobs (across all platforms)
        # by the existing Final Score, descending, and keep only the
        # top 10. Final Score itself is unchanged - this only decides
        # ordering and which rows get written out.
        # ====================================================
        scenario_job_rows.sort(
            key=lambda r: r["Final Score"],
            reverse=True,
        )

        detailed_job_rows.extend(scenario_job_rows[:10])

    # ========================================================
    # RESULTS.CSV
    # ========================================================

    results_fields = [
        "Platform",
        "Test #",
        "Job Role",
        "Skills",
        "Experience (yrs)",
        "Location",
        "# Results Returned",
        "# With Apply Link",
        "# Reachable Apply Links",
        "# Fresh <30 Days",
        "# Relevant Matches",
        "# Strong Relevant",
        "# Moderate Relevant",
        "# Role Match Only",
        "# Skill Only",
        "# APPLY",
        "# CHECK",
        "# Experience MATCH",
        "# Experience MISMATCH",
        "# Experience UNKNOWN",
        "Freshness Definition",
        "Notes / Issues",
    ]

    with open(
        "results.csv",
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=results_fields,
        )
        writer.writeheader()
        writer.writerows(csv_rows)

    # ========================================================
    # SUMMARY.CSV
    # ========================================================

    summary_rows = create_summary(csv_rows)

    summary_fields = [
        "Platform",
        "Tests Completed",
        "Average Results Returned",
        "Apply Link Availability",
        "Freshness",
        "Relevance",
        "Relevant Job Rate",
        "Apply Recommendations",
        "Check Recommendations",
        "Status",
        "Notes",
    ]

    with open(
        "summary.csv",
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=summary_fields,
        )
        writer.writeheader()
        writer.writerows(summary_rows)

    # ========================================================
    # JOB_DETAILS.CSV
    # ========================================================

    detail_fields = [
        "Platform",
        "Test #",
        "Job Role",
        "Skills",
        "Experience (yrs)",
        "Location",
        "Job Title",
        "Description Preview",
        "Posted / Updated",
        "Fresh <30 Days",
        "Days Old",
        "Apply Link",
        "Link Reachable",
        "Link Status",
        "Link Quality",
        "Result Location",
        "Location Reason",
        "Role Match",
        "Role Similarity Score",
        "Matched Skills",
        "Skill Count",
        "Classification",
        "Relevant",
        "Experience Match",
        "Required Experience",
        "Role Level",
        "Job Seniority",
        "Candidate Seniority",
        "Seniority Match",
        "Seniority Penalty",
        "Role Points",
        "Skill Points",
        "Experience Points",
        "Location Points",
        "Freshness Points",
        "Link Points",
        "Total Skills Requested",
        "Freshness",
        "Final Score",
        "Final Classification",
        "Match Reason",
    ]

    with open(
        "job_details.csv",
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=detail_fields,
        )
        writer.writeheader()
        writer.writerows(detailed_job_rows)

    # ========================================================
    # FINAL TERMINAL OUTPUT
    # ========================================================

    print()
    print("=" * 70)
    print("DONE")
    print(
        f"{len(csv_rows)} test rows written to results.csv"
    )
    print(
        f"{len(summary_rows)} rows written to summary.csv"
    )
    print(
        f"{len(detailed_job_rows)} job rows written "
        f"to job_details.csv"
    )
    print("=" * 70)
    print()
    print("IMPORTANT:")
    print("Open job_details.csv first.")
    print(
        "It contains the final score, classification, "
        "role level, skills, experience and location "
        "reason for every job."
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    run_all()