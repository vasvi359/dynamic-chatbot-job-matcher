from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from openai import OpenAI
from dotenv import load_dotenv
from parser import extract_text
from db import get_connection
from auth import router as auth_router
from ats_prompt import ATS_SYSTEM_PROMPT
from docx_builder import build_ats_docx
from job_search import find_and_rank_jobs, get_or_create_profile
from datetime import datetime
import os
import json
import shutil

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI()


def ensure_candidate_profiles_table():
    """One-time idempotent migration for the profile cache (mirrors auth.py's
    CREATE TABLE IF NOT EXISTS pattern)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_profiles (
            id SERIAL PRIMARY KEY,
            resume_id INTEGER UNIQUE NOT NULL,
            profile_data JSONB NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    conn.commit()
    cur.close()
    conn.close()


def ensure_saved_jobs_table():
    """One-time idempotent migration for the saved-jobs shortlist (same
    fail-safe pattern as ensure_candidate_profiles_table)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_jobs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            job_data JSONB NOT NULL,
            apply_link TEXT NOT NULL DEFAULT '',
            saved_at TIMESTAMP DEFAULT NOW(),
            UNIQUE (user_id, apply_link)
        )
        """
    )
    conn.commit()
    cur.close()
    conn.close()


try:
    ensure_candidate_profiles_table()
except Exception as e:
    # Fail-safe: a DB issue at startup must not crash the app; endpoints
    # surface real errors when actually called.
    print(f"[startup] candidate_profiles table creation failed: {type(e).__name__}: {e}")

try:
    ensure_saved_jobs_table()
except Exception as e:
    # Same fail-safe as above.
    print(f"[startup] saved_jobs table creation failed: {type(e).__name__}: {e}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = [".pdf", ".docx", ".txt"]

SYSTEM_PROMPT = """
You are an AI Career Assistant. You help with resume analysis, skill gaps,
job matching, and career roadmaps.

You have THREE possible chart types you can use to answer career-related
questions. Pick whichever ONE fits the user's question best, based on the
resume/skills information given to you. IMPORTANT: if a target role is
provided ALONGSIDE resume/skills content, always use "skill_gap" — only
use "top_skills" when the user is asking specifically about their
strengths with NO target role mentioned at all. Only generate a chart if real
skills/experience/resume content was actually provided — if the user only
gave a role name with no info about themselves, ask them for that info
instead (see the "text" response shape below).

CHART TYPE 1 — "top_skills"
{
  "type": "chart",
  "chart_type": "top_skills",
  "reply": "<one short sentence introducing this>",
  "data": { "allSkills": ["<every distinct skill/tool/technology mentioned anywhere in the resume, however many there are>"] }
}

CHART TYPE 2 — "skill_gap"
{
  "type": "chart",
  "chart_type": "skill_gap",
  "reply": "<one short sentence introducing this>",
  "data": {
    "currentRole": "<string, their current role from the resume>",
    "targetRole": "<string, the role they're aiming for>",
    "resumeSkills": ["<every real skill/tool/technology found in the resume>"],
    "currentRoleRequiredSkills": ["<typical skills required for their CURRENT role>"],
    "targetRoleRequiredSkills": ["<typical skills required for the TARGET role>"],
    "missingSkills": ["<up to 5 skills present in targetRoleRequiredSkills but NOT in resumeSkills>"]
  }
}

CHART TYPE 3 — "experience_gap"
{
  "type": "chart",
  "chart_type": "experience_gap",
  "reply": "<one short sentence introducing this>",
  "data": {
    "roleName": "<string. If the user's message explicitly names a target role, use that EXACT role name. If NO role is mentioned in the user's message, use the EXACT current/most recent job title as written in the resume — do not invent or guess a different role.>",
    "experienceEntries": [
      {"startDate": "<YYYY-MM, your best estimate from the resume>", "endDate": "<YYYY-MM or 'present'>"}
    ],
    "requiredYears": <number, typical years required for this specific roleName>
  }
}

FOR ANY OTHER QUESTION, respond instead with:
{ "type": "text", "reply": "<your plain English answer here>" }

Do not wrap JSON inside markdown. Do not write ```json.
Always return pure JSON only, matching exactly one of the shapes above.
"""


def run_ai(user_content: str):
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )
    reply = response.choices[0].message.content
    try:
        return json.loads(reply)
    except Exception:
        return {"type": "text", "reply": reply}


def calculate_match_percentage(resume_skills, required_skills):
    if not required_skills:
        return 0

    resume_lower = [s.lower().strip() for s in resume_skills]
    matched = 0

    for req_skill in required_skills:
        req_lower = req_skill.lower().strip()
        if any(req_lower in r or r in req_lower for r in resume_lower):
            matched += 1

    return round((matched / len(required_skills)) * 100)


def apply_real_skill_gap_math(result: dict):
    if result.get("type") == "chart" and result.get("chart_type") == "skill_gap":
        d = result.get("data", {})
        d["currentMatch"] = calculate_match_percentage(
            d.get("resumeSkills", []), d.get("currentRoleRequiredSkills", [])
        )
        d["targetMatch"] = calculate_match_percentage(
            d.get("resumeSkills", []), d.get("targetRoleRequiredSkills", [])
        )
    return result


def calculate_years_from_entries(entries):
    if not entries:
        return 0

    total_months = 0
    now = datetime.now()

    for entry in entries:
        try:
            start = datetime.strptime(entry["startDate"], "%Y-%m")
        except (ValueError, KeyError, TypeError):
            continue

        end_str = str(entry.get("endDate", "")).lower()
        if end_str == "present" or not end_str:
            end = now
        else:
            try:
                end = datetime.strptime(entry["endDate"], "%Y-%m")
            except ValueError:
                end = now

        months = (end.year - start.year) * 12 + (end.month - start.month)
        if months > 0:
            total_months += months

    return round(total_months / 12, 1)


def apply_real_experience_math(result: dict):
    if result.get("type") == "chart" and result.get("chart_type") == "experience_gap":
        d = result.get("data", {})
        d["currentYears"] = calculate_years_from_entries(d.get("experienceEntries", []))
    return result


def compute_missing_skills(resume_skills: list, target_role_required_skills: list) -> list:
    """Up to 5 skills required by the target role but absent from the resume
    (mirrors the skill_gap chart's own extraction rule)."""
    resume_lower = [s.lower().strip() for s in (resume_skills or [])]
    missing = []
    for skill in target_role_required_skills or []:
        s = str(skill).strip()
        s_lower = s.lower()
        if s_lower and not any(s_lower in r or r in s_lower for r in resume_lower):
            missing.append(s)
        if len(missing) >= 5:
            break
    return missing


def apply_unified_profile(result: dict, profile: dict):
    """Override target-role-dependent chart fields with the canonical profile
    so the chat pipeline's own extraction is no longer the source of truth.
    Chart math functions are applied BEFORE this, so currentMatch/targetMatch
    are recomputed against the unified skills."""
    if result.get("type") != "chart":
        return result

    d = result.get("data", {})

    if result.get("chart_type") == "skill_gap":
        d["resumeSkills"] = profile.get("skills", [])
        d["currentRole"] = profile.get("current_role", "")
        d["currentMatch"] = calculate_match_percentage(
            d.get("resumeSkills", []), d.get("currentRoleRequiredSkills", [])
        )
        d["targetMatch"] = calculate_match_percentage(
            d.get("resumeSkills", []), d.get("targetRoleRequiredSkills", [])
        )
        d["missingSkills"] = compute_missing_skills(
            d.get("resumeSkills", []), d.get("targetRoleRequiredSkills", [])
        )

    elif result.get("chart_type") == "experience_gap":
        if not d.get("roleName"):
            d["roleName"] = profile.get("current_role", "")

    return result


def rank_top_skills(resume_text: str, all_skills: list, top_n: int = 5):
    if not all_skills:
        return []

    resume_lower = resume_text.lower()
    counts = []

    for skill in all_skills:
        skill_lower = skill.lower().strip()
        count = resume_lower.count(skill_lower)
        counts.append((skill, count))

    counts.sort(key=lambda x: x[1], reverse=True)
    return [skill for skill, count in counts[:top_n]]


def apply_real_top_skills_ranking(result: dict, resume_text: str):
    if result.get("type") == "chart" and result.get("chart_type") == "top_skills":
        d = result.get("data", {})
        d["skills"] = rank_top_skills(resume_text, d.get("allSkills", []))
    return result


def get_cached_chart(cur, resume_id: int, chart_type: str, target_role: str = None):
    if target_role:
        cur.execute(
            """
            SELECT result_data FROM chart_results
            WHERE resume_id = %s AND chart_type = %s AND target_role = %s
            ORDER BY created_at DESC LIMIT 1
            """,
            (resume_id, chart_type, target_role),
        )
    else:
        cur.execute(
            """
            SELECT result_data FROM chart_results
            WHERE resume_id = %s AND chart_type = %s AND target_role IS NULL
            ORDER BY created_at DESC LIMIT 1
            """,
            (resume_id, chart_type),
        )
    row = cur.fetchone()
    if not row:
        return None

    cached_result = row["result_data"]
    cached_result["reply"] = "Here's your previously saved result (no new AI call needed)."
    return cached_result


def save_chart_result(cur, conn, resume_id: int, chart_type: str, target_role, result: dict):
    cur.execute(
        "INSERT INTO chart_results (resume_id, chart_type, target_role, result_data) VALUES (%s, %s, %s, %s)",
        (resume_id, chart_type, target_role, json.dumps(result)),
    )
    conn.commit()


def is_top_skills_query(message: str) -> bool:
    keywords = ["top skill", "best skill", "my skills", "top skills", "strongest skill"]
    lowered = message.lower()
    return any(k in lowered for k in keywords)


def is_experience_gap_query(message: str) -> bool:
    lowered = message.lower()
    if "exper" in lowered and "gap" in lowered:
        return True
    keywords = ["years of experience", "enough experience", "experience comparison", "experience required"]
    return any(k in lowered for k in keywords)


def detect_intended_chart_type(message: str) -> str:
    if is_experience_gap_query(message):
        return "experience_gap"
    if is_top_skills_query(message):
        return "top_skills"
    return "skill_gap"


def normalize_role(role: str) -> str:
    if not role:
        return ""
    qualifiers = ["senior", "junior", "lead", "principal", "staff", "associate", "sr", "jr"]
    words = role.lower().split()
    filtered = [w for w in words if w not in qualifiers]
    return "".join(filtered).strip()


def get_most_recent_role(cur, resume_id):
    cur.execute(
        "SELECT target_role FROM chart_results WHERE resume_id = %s AND target_role IS NOT NULL ORDER BY created_at DESC LIMIT 1",
        (resume_id,),
    )
    row = cur.fetchone()
    return row["target_role"] if row else None


def is_refresh_request(message: str) -> bool:
    keywords = ["refresh", "regenerate", "redo my", "recalculate", "update my analysis", "new analysis", "recheck"]
    lowered = message.lower()
    return any(k in lowered for k in keywords)


@app.get("/")
def home():
    return {"message": "Chatbot Backend is Running!"}


@app.post("/chat")
def chat(data: dict):
    user_message = data.get("message", "")
    user_id = data.get("user_id")
    resume_row = None
    conn = None
    cur = None

    if user_id:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            "SELECT id, extracted_text FROM resumes WHERE user_id = %s ORDER BY uploaded_at DESC LIMIT 1",
            (int(user_id),),
        )
        resume_row = cur.fetchone()

        if resume_row:
            force_refresh = is_refresh_request(user_message)

            cur.execute(
                "SELECT DISTINCT chart_type, target_role FROM chart_results WHERE resume_id = %s ORDER BY chart_type",
                (resume_row["id"],),
            )
            saved_combos = cur.fetchall()

            intended_type = detect_intended_chart_type(user_message)

            if not force_refresh:
                if intended_type == "top_skills":
                    cached = get_cached_chart(cur, resume_row["id"], "top_skills", None)
                    if cached:
                        cur.close()
                        conn.close()
                        return cached

                elif intended_type == "experience_gap":
                    matched_cached = None
                    for combo in saved_combos:
                        role = combo["target_role"]
                        if combo["chart_type"] == "experience_gap" and role and normalize_role(role) in normalize_role(user_message):
                            matched_cached = get_cached_chart(cur, resume_row["id"], "experience_gap", role)
                            break

                    if not matched_cached:
                        stripped = user_message.lower()
                        for kw in ["experience gap", "experince gap", "years of experience",
                                   "enough experience", "experience comparison", "experience required"]:
                            stripped = stripped.replace(kw, "")

                        if len(stripped.strip()) < 5:
                            inferred_role = get_most_recent_role(cur, resume_row["id"])
                            if inferred_role:
                                matched_cached = get_cached_chart(cur, resume_row["id"], "experience_gap", inferred_role)
                                if not matched_cached:
                                    user_message = f"experience gap for {inferred_role}"

                    if matched_cached:
                        cur.close()
                        conn.close()
                        return matched_cached

                else:  # skill_gap
                    for combo in saved_combos:
                        role = combo["target_role"]
                        if combo["chart_type"] == "skill_gap" and role and normalize_role(role) in normalize_role(user_message):
                            cached = get_cached_chart(cur, resume_row["id"], "skill_gap", role)
                            if cached:
                                cur.close()
                                conn.close()
                                return cached

            if force_refresh:
                for kw in ["refresh", "regenerate", "redo my", "recalculate",
                           "update my analysis", "new analysis", "recheck"]:
                    user_message = user_message.lower().replace(kw, "").strip()
                if not user_message:
                    inferred_role = get_most_recent_role(cur, resume_row["id"])
                    if inferred_role:
                        user_message = f"gap analysis for {inferred_role}"

            user_message = f"""
User's question: {user_message}

Their saved resume content (use this if relevant to answering):
{resume_row["extracted_text"]}
"""

    result = run_ai(user_message)
    result = apply_real_skill_gap_math(result)
    result = apply_real_experience_math(result)
    if resume_row:
        result = apply_real_top_skills_ranking(result, resume_row["extracted_text"])

    if resume_row and result.get("type") == "chart":
        profile = get_or_create_profile(resume_row["id"], resume_row["extracted_text"])
        result = apply_unified_profile(result, profile)

    if resume_row and result.get("type") == "chart":
        target_role = result.get("data", {}).get("targetRole") or result.get("data", {}).get("roleName")
        save_chart_result(cur, conn, resume_row["id"], result.get("chart_type"), target_role, result)

    if cur:
        cur.close()
    if conn:
        conn.close()

    return result


@app.post("/chat-with-resume")
async def chat_with_resume(
    user_id: int = Form(...),
    target_role: str = Form(...),
    file: UploadFile = File(...),
    force_refresh: bool = Form(False),
):
    extension = os.path.splitext(file.filename)[1].lower()

    if extension not in ALLOWED_EXTENSIONS:
        return {"type": "text", "reply": "Unsupported file type. Please upload a PDF, DOCX, or TXT resume."}

    file_path = os.path.join(UPLOAD_FOLDER, file.filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        resume_text = extract_text(file_path)

        if not resume_text.strip():
            return {"type": "text", "reply": "Couldn't extract any text from that file. Try a different resume file."}

        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            "SELECT id FROM resumes WHERE user_id = %s AND filename = %s ORDER BY uploaded_at DESC LIMIT 1",
            (user_id, file.filename),
        )
        existing_resume = cur.fetchone()
        resume_id = existing_resume["id"] if existing_resume else None

        if existing_resume:
            cur.execute("SELECT extracted_text FROM resumes WHERE id = %s", (existing_resume["id"],))
            old_text_row = cur.fetchone()
            old_text = old_text_row["extracted_text"] if old_text_row else ""
            if old_text.strip() != resume_text.strip():
                resume_id = None

        if resume_id and not force_refresh:
            cur.execute(
                "SELECT target_role FROM chart_results WHERE resume_id = %s AND chart_type = 'skill_gap'",
                (resume_id,),
            )
            saved_roles = [r["target_role"] for r in cur.fetchall()]
            for saved_role in saved_roles:
                if normalize_role(saved_role) == normalize_role(target_role):
                    cached = get_cached_chart(cur, resume_id, "skill_gap", saved_role)
                    if cached:
                        cur.close()
                        conn.close()
                        return cached

        if not resume_id:
            cur.execute(
                "INSERT INTO resumes (user_id, filename, extracted_text) VALUES (%s, %s, %s) RETURNING id",
                (user_id, file.filename, resume_text),
            )
            resume_id = cur.fetchone()["id"]
            conn.commit()

        combined_message = f"""
Target role: {target_role}

Resume content:
{resume_text}
"""
        result = run_ai(combined_message)
        result = apply_real_skill_gap_math(result)
        result = apply_real_experience_math(result)
        result = apply_real_top_skills_ranking(result, resume_text)

        if result.get("type") == "chart":
            profile = get_or_create_profile(resume_id, resume_text)
            result = apply_unified_profile(result, profile)
            save_chart_result(cur, conn, resume_id, result.get("chart_type"), target_role, result)

        cur.close()
        conn.close()

        return result

    except Exception as e:
        print(f"[chat-with-resume] error: {type(e).__name__}: {e}")
        return {"type": "text", "reply": f"Error processing resume: {str(e)}"}

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@app.post("/job-matches")
def job_matches(data: dict):
    user_id = data.get("user_id")
    target_role = str(data.get("target_role") or "").strip()

    if not user_id or not target_role:
        return {"type": "text", "reply": "user_id and target_role are required."}

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, extracted_text FROM resumes WHERE user_id = %s ORDER BY uploaded_at DESC LIMIT 1",
            (int(user_id),),
        )
        row = cur.fetchone()
        if not row or not row.get("extracted_text"):
            return {"type": "text", "reply": "Please upload your resume first."}

        resume_id = row["id"]
        resume_text = row["extracted_text"]
        profile = get_or_create_profile(resume_id, resume_text)
        return find_and_rank_jobs(resume_text, target_role, limit=10, profile=profile)
    except Exception as e:
        print(f"[job-matches] error: {type(e).__name__}: {e}")
        return {"type": "text", "reply": f"Job search error: {str(e)}"}
    finally:
        cur.close()
        conn.close()


@app.post("/generate-ats-resume")
async def generate_ats_resume(file: UploadFile = File(...)):
    extension = os.path.splitext(file.filename)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        return {"type": "text", "reply": "Unsupported file type. Please upload a PDF, DOCX, or TXT resume."}

    file_path = os.path.join(UPLOAD_FOLDER, file.filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        resume_text = extract_text(file_path)
        if not resume_text.strip():
            return {"type": "text", "reply": "Couldn't extract any text from that file."}

        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": ATS_SYSTEM_PROMPT},
                {"role": "user", "content": resume_text},
            ],
        )
        structured_data = json.loads(response.choices[0].message.content)

        output_path = os.path.join(UPLOAD_FOLDER, "ats_resume.docx")
        build_ats_docx(structured_data, output_path)

        return FileResponse(
            output_path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename="ATS_Resume.docx",
        )

    except Exception as e:
        return {"type": "text", "reply": f"Error generating ATS resume: {str(e)}"}

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@app.get("/my-analyses/{user_id}")
def get_my_analyses(user_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT r.id AS resume_id, r.filename, r.uploaded_at,
               c.chart_type, c.target_role, c.result_data, c.created_at
        FROM resumes r
        LEFT JOIN chart_results c ON c.resume_id = r.id
        WHERE r.user_id = %s
        ORDER BY r.uploaded_at DESC
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {"resumes": rows}


@app.post("/save-job")
def save_job(data: dict):
    user_id = data.get("user_id")
    job = data.get("job")

    if not user_id or not isinstance(job, dict) or not job:
        return {"type": "text", "reply": "user_id and job are required."}

    # Dedupe key is apply_link (the most stable identifier a listing has).
    # Fall back to the title only when a listing has no link at all, so two
    # link-less jobs don't collide on the empty string.
    apply_link = str(job.get("apply_link") or "").strip() or str(job.get("title") or "").strip()

    conn = get_connection()
    cur = conn.cursor()
    try:
        # Upsert on (user_id, apply_link): re-saving the same job bumps it
        # to the top of the list (fresh job_data + saved_at) rather than
        # inserting a duplicate row.
        cur.execute(
            """
            INSERT INTO saved_jobs (user_id, job_data, apply_link)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, apply_link)
            DO UPDATE SET job_data = EXCLUDED.job_data, saved_at = NOW()
            """,
            (int(user_id), json.dumps(job), apply_link),
        )
        conn.commit()
        return {"type": "text", "reply": "Job saved"}
    except Exception as e:
        return {"type": "text", "reply": f"Error saving job: {str(e)}"}
    finally:
        cur.close()
        conn.close()


@app.get("/saved-jobs/{user_id}")
def get_saved_jobs(user_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, job_data, saved_at FROM saved_jobs WHERE user_id = %s ORDER BY saved_at DESC, id DESC",
        (user_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    saved_jobs = []
    for row in rows:
        entry = dict(row["job_data"])
        entry["id"] = row["id"]  # row id, needed by DELETE /saved-jobs/{id}
        entry["saved_at"] = row["saved_at"].isoformat() if row["saved_at"] else None
        saved_jobs.append(entry)

    return {"saved_jobs": saved_jobs}


@app.delete("/saved-jobs/{job_id}")
def delete_saved_job(job_id: int, user_id: int):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM saved_jobs WHERE id = %s AND user_id = %s",
            (job_id, user_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return {"type": "text", "reply": "Saved job not found."}
        return {"type": "text", "reply": "Saved job removed"}
    except Exception as e:
        return {"type": "text", "reply": f"Error removing job: {str(e)}"}
    finally:
        cur.close()
        conn.close()