-- Cached candidate profile: single source of truth per resume.
-- One row per resume; profile_data is produced by exactly one LLM call
-- per resume upload and reused by /chat, /chat-with-resume and /job-matches.
--
-- Run as a superuser (the DB owner), NOT the app role — the app role
-- typically lacks CREATE on schema public:
--   psql -U postgres -d skillgap_db -f backend/migrations.sql
--
-- NOTE: app.py also runs the CREATE TABLE IF NOT EXISTS at startup, but on
-- locked-down servers (Postgres 15+) that fails silently with
-- "permission denied for schema public", so run this file explicitly.

CREATE TABLE IF NOT EXISTS candidate_profiles (
    id SERIAL PRIMARY KEY,
    resume_id INTEGER UNIQUE NOT NULL,
    profile_data JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- The app role needs table privileges AND sequence privileges. Table grants
-- alone are NOT enough: every INSERT that omits `id` draws from the SERIAL
-- sequence, and without USAGE it fails with
-- "permission denied for sequence candidate_profiles_id_seq".
-- (Adjust the role name if your app user differs from .env's DB_USER.)
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE candidate_profiles TO skillgap_app;
GRANT USAGE, SELECT ON SEQUENCE candidate_profiles_id_seq TO skillgap_app;

-- Optional hardening so future SERIAL columns don't repeat this problem:
-- run once as postgres, uncommented:
-- ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
--     GRANT USAGE, SELECT ON SEQUENCES TO skillgap_app;

-- ============================================================
-- saved_jobs — user shortlist ("save job" feature)
-- One row per (user, job). job_data stores the full job object
-- exactly as returned by /job-matches (title, description,
-- apply_link, score, classification, ...). apply_link is lifted
-- into its own column so the UNIQUE constraint can back the
-- ON CONFLICT upsert in app.py's POST /save-job: re-saving a job
-- bumps it to the top (job_data + saved_at refreshed) instead of
-- inserting a duplicate row.
--
-- The UNIQUE (user_id, apply_link) constraint is REQUIRED for that
-- upsert — don't drop it. ON DELETE CASCADE cleans up shortlists
-- when a user is removed.
-- ============================================================

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
