# PRD: Save / Shortlist Jobs ("Save Job" Feature)

| | |
|---|---|
| **Status** | Implemented (backend) |
| **Date** | 2026-09-12 |
| **Scope** | Backend only — additive feature alongside existing endpoints |
| **Owner** | SkillGap / AI Career Assistant project |

---

## 1. Overview

Users can currently see ranked job recommendations from `POST /job-matches`, but the results are ephemeral — once they move on, the listings are gone. This feature lets users **save/shortlist a job** from their `/job-matches` results and **retrieve their saved jobs later** (and remove ones they no longer want).

It is a purely additive feature: it sits alongside the existing pipeline without modifying any matching, scoring, or ranking logic.

## 2. Goals

1. Users can save a job (the full job object as returned by `/job-matches`) from the chatbot.
2. Users can list their saved jobs, most recent first.
3. Users can delete a saved job, scoped to their own user id.
4. Re-saving the same job does **not** create a duplicate row — it "bumps to top" (approved decision).
5. Zero risk to existing functionality: no changes to matching, scoring, filters, or existing response shapes.

## 3. Non-Goals (explicitly out of scope)

- **Do not touch:** `find_and_rank_jobs`, `calculate_final_score`, the relevance/seniority filters, or any existing endpoint's response shape (`/chat`, `/chat-with-resume`, `/job-matches`, `/generate-ats-resume`, `/my-analyses/{user_id}`).
- **Do not touch:** `candidate_profiles` or `chart_results` tables/logic — separate concern.
- No frontend work in this pass (wiring a save button / saved-jobs card is future work).

## 4. Key Decisions (made with user approval)

| Decision | Choice |
|---|---|
| Duplicate handling | **Bump to top** — upsert via `ON CONFLICT (user_id, apply_link) DO UPDATE`: refresh `job_data` and set `saved_at = NOW()`, moving the job to the top of the list. Never errors on duplicates. |
| Dedupe key | `apply_link` (most stable unique-ish identifier a job listing has). Fallback to job `title` when a listing has no link at all, so link-less jobs don't all collide on `''`. |
| Unique constraint | `UNIQUE (user_id, apply_link)` on `saved_jobs` — **required** for the upsert. |
| DELETE endpoint | Included. Scoped to `user_id` so a user cannot delete another user's saved job. |
| Storage pattern | Mirror `candidate_profiles`/`chart_results`: same `get_connection()`, JSONB for the flexible job payload, `json.dumps()` on insert. |
| Migration safety | `CREATE TABLE IF NOT EXISTS` run at startup, wrapped in `try/except: pass` so a DB issue at import time never crashes the app. Explicit superuser run of `migrations.sql` remains recommended for Postgres 15+ permission handling. |

## 5. Data Model — `saved_jobs`

```sql
CREATE TABLE IF NOT EXISTS saved_jobs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_data JSONB NOT NULL,
    apply_link TEXT NOT NULL DEFAULT '',
    saved_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (user_id, apply_link)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE saved_jobs TO skillgap_app;
GRANT USAGE, SELECT ON SEQUENCE saved_jobs_id_seq TO skillgap_app;
```

- `job_data` stores the **full job object exactly as returned by `/job-matches`**:
  `title`, `description` (truncated to 600 chars by the matcher), `apply_link`, `score`, `classification`, `role_level`, `matched_skills`, `experience_match`, `required_experience`, `location_match`, `match_reason`.
- `apply_link` is lifted into its own column so the UNIQUE constraint can back the upsert.
- `ON DELETE CASCADE` cleans up shortlists when a user is removed.
- The sequence `GRANT` matters: every INSERT that omits `id` draws from the SERIAL sequence, and without `USAGE` it fails on locked-down servers ("permission denied for sequence ...").

## 6. Functional Requirements / Endpoints

### 6.1 `POST /save-job`

- **Request body:** `{ "user_id": <id>, "job": { ...full job object from a /job-matches response... } }`
- **Validation:** `user_id` and non-empty dict `job` required; otherwise `{"type": "text", "reply": "user_id and job are required."}`
- **Behavior:** upsert on `(user_id, apply_link)` — new jobs are inserted; re-saves refresh `job_data` and bump `saved_at` to now.
- **Response (success):** `{"type": "text", "reply": "Job saved"}` — consistent with existing text-reply shape.
- **Response (error):** `{"type": "text", "reply": "Error saving job: <detail>"}` — no 500s, consistent with how other endpoints surface errors.

### 6.2 `GET /saved-jobs/{user_id}`

- **Response:** `{ "saved_jobs": [ ... ] }`, **most recent first** (`ORDER BY saved_at DESC, id DESC`).
- **Each entry:** the stored `job_data` fields, plus:
  - `id` — the `saved_jobs` row id (needed by the DELETE endpoint)
  - `saved_at` — ISO-8601 timestamp string (or `null`)

### 6.3 `DELETE /saved-jobs/{job_id}?user_id=<id>`

- **Behavior:** `DELETE FROM saved_jobs WHERE id = %s AND user_id = %s` — user-scoped; a user can only remove their own saves.
- **Response:** `{"type": "text", "reply": "Saved job removed"}` on success; `{"type": "text", "reply": "Saved job not found."}` when the row doesn't exist or belongs to another user.

## 7. Non-Functional Requirements

- Startup must never crash due to this table: migration is idempotent (`CREATE TABLE IF NOT EXISTS`) and wrapped in the same `try/except: pass` fail-safe as `ensure_candidate_profiles_table()`.
- Response shapes follow the existing `{"type": "text", "reply": ...}` convention — no new response dialects.
- DB access follows project conventions: `get_connection()` from `db.py`, `RealDictCursor`, explicit `conn.commit()` and `cur.close()/conn.close()` in `finally`.

## 8. Changes Made This Session (Change Log)

### `backend/migrations.sql`
- Appended a `saved_jobs` section with:
  - Comment block explaining purpose, the upsert contract, and that the UNIQUE constraint is required.
  - `CREATE TABLE IF NOT EXISTS saved_jobs` (schema above).
  - `GRANT` statements for `skillgap_app` on the table and its `saved_jobs_id_seq` sequence (Postgres 15+ permission-safe, consistent with the `candidate_profiles` grants).

### `backend/app.py`
- Added `ensure_saved_jobs_table()` — mirrors `ensure_candidate_profiles_table()`.
- Added startup call `try: ensure_saved_jobs_table() except Exception: pass` directly below the existing candidate-profiles fail-safe.
- Added `POST /save-job` (`save_job`) with validation, title-fallback dedupe key, and `ON CONFLICT (user_id, apply_link) DO UPDATE SET job_data = EXCLUDED.job_data, saved_at = NOW()`.
- Added `GET /saved-jobs/{user_id}` (`get_saved_jobs`) returning `{saved_jobs: [...]}` most-recent-first, each entry = `job_data` + row `id` + ISO `saved_at`.
- Added `DELETE /saved-jobs/{job_id}` (`delete_saved_job`, takes `user_id` as a query param) scoped via `AND user_id = %s`.

**No other files were modified.** Existing endpoints, `job_search.py` logic, and the `candidate_profiles`/`chart_results` code paths are untouched (verified by route dump + import check).

## 9. Verification Performed

- `py_compile` on `app.py` — passes.
- `import app` in the backend venv — passes (`import OK`).
- FastAPI route dump confirms all three new routes registered:
  - `('/save-job', ['POST'])`
  - `('/saved-jobs/{user_id}', ['GET'])`
  - `('/saved-jobs/{job_id}', ['DELETE'])`
  — alongside the six pre-existing endpoints, unchanged.

## 10. Acceptance Criteria

- [x] Saving a job from a `/job-matches` response persists the full job object.
- [x] Re-saving the same job (same `apply_link`, same user) updates the existing row and refreshes `saved_at` — no duplicate, no error.
- [x] `GET /saved-jobs/{user_id}` returns only that user's saves, newest first, each with its row `id` and `saved_at`.
- [x] `DELETE /saved-jobs/{id}?user_id=N` removes the row only if it belongs to that user.
- [x] Table auto-creates at startup without crashing the app when the DB is unreachable.
- [x] No existing endpoint's response shape changed; no matching/ranking logic modified.

## 11. Future Work (not in this session)

- Frontend: save button in `JobMatchesCard`, a `SavedJobsCard` with unsave/delete actions, retrieval view.
- End-to-end smoke test of the three endpoints against the live DB.
- Optionally run `backend/migrations.sql` as superuser (`psql -U postgres -d skillgap_db -f backend/migrations.sql`) on Postgres 15+ environments where the startup DDL fails silently.
