# Dynamic Chatbot & Job Matching Integration
An AI career-assistant web app: resume-grounded skill-gap analysis against a
target role, plus live job matching and ranking across three job platforms
(Jooble, JSearch, SerpAPI). Built with a FastAPI backend, React (Vite)
frontend, and PostgreSQL.

## Repository structure

```
backend/    FastAPI backend, job matcher, database layer
frontend/   React (Vite) frontend
docs/       Design docs / PRDs for individual features
```

## Backend — production code (`backend/`)

These files make up the live application path. This is what's actually
running in production:

| File | Purpose |
|---|---|
| `app.py` | FastAPI entrypoint — all live endpoints: `/chat`, `/chat-with-resume`, `/job-matches`, `/save-job`, `/saved-jobs/{user_id}`, `/generate-ats-resume`, `/my-analyses/{user_id}`, plus login/register |
| `job_search.py` | Live job-matching pipeline — fetches from Jooble, JSearch, and SerpAPI, unifies the candidate profile (cached per resume), applies the relevance and seniority-gap filters, and returns the ranked top 10 |
| `submission_small_test_v2.py` | Core job matching & ranking engine — scores every job on Role/Skills/Experience/Location/Freshness/Apply-Link, with seniority-mismatch penalties and APPLY/CHECK/SKILL MATCH ONLY/NOT RELEVANT classification. Reused by `job_search.py`; also runnable standalone as a CLI test harness (`__main__`) |
| `parser.py` | Resume text extraction (PDF/DOCX/TXT) |
| `auth.py` | Login / registration (passlib + bcrypt) |
| `db.py` | PostgreSQL connection helper (`get_connection()`, used by every DB-backed feature) |
| `docx_builder.py` | ATS resume `.docx` generation |
| `ats_prompt.py` | Prompt used for ATS resume content generation |
| `migrations.sql` | Database schema — source of truth for all tables (`users`, `resumes`, `chart_results`, `candidate_profiles`, `saved_jobs`) |
| `requirements.txt` | Python dependencies |

## Backend — R&D / debug scripts (`backend/`)

These were used during development and testing — not part of the live
request path, and not required for the app to run:

| File | Purpose |
|---|---|
| `debug_pipeline.py` | Monkeypatches internal fetch functions to print SerpAPI queries for debugging |
| `debug_breakdown.py` | Standalone script for inspecting scoring breakdowns during matcher testing |
| `debug_job_search.py` | Standalone script for testing `job_search.py`'s pipeline in isolation |
| `debug_multisource.py` | Standalone script used to verify the three-platform fetch + relevance/seniority filter gates end-to-end during development |
| `python debug_breakdown.py` | Stray file from a shell typo — safe to delete, not real code |

## Frontend (`frontend/src/`)

| File | Purpose |
|---|---|
| `App.jsx` | Main app — chat flow, routing between chart types, resume upload |
| `login.jsx` | Login/registration UI |
| `JobMatchesCard.jsx` | Renders ranked job results, Save button |
| `SavedJobsCard.jsx` | Renders saved/shortlisted jobs, Remove button |
| `GapAnalysisCard.jsx` | Skill-gap chart (current vs target role) |
| `ExperienceGapCard.jsx` | Experience-gap chart |
| `TopSkillsCard.jsx` | Top-skills chart |
| `main.jsx`, `App.css`, `index.css` | App entrypoint and styling |

## Docs (`docs/`)

| File | Purpose |
|---|---|
| `PRD_saved_jobs.md` | Design doc for the save/shortlist-jobs feature — schema, endpoints, decisions made and why |

## Known limitations (documented, not yet fixed)

- JSearch and SerpAPI's relative date formats ("5 days ago") don't parse
  through the current date-parsing pipeline, so freshness/expiry filtering
  is fully reliable only for Jooble listings.
- The matcher's experience-requirement extraction can occasionally misread
  a stray phrase in a job description (e.g. "mentored by a senior lead") as
  the job's own required experience level — a display-accuracy issue, not
  a scoring bug.
- `SavedJobsCard`'s remove/delete success check has the same fragile
  string-comparison pattern the Save button had before its fix — not yet
  applied to the remove handler.

## Setup

**Backend:**
```bash
cd backend
pip install -r requirements.txt
# create a .env with: JOOBLE_API_KEY, JSEARCH_API_KEY, SERPAPI_KEY,
# DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
psql -U <superuser> -d <db_name> -f migrations.sql
uvicorn app:app --reload
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```
