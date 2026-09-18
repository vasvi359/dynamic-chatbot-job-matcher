import { useState } from "react";
import axios from "axios";

const BACKEND_URL = "http://127.0.0.1:8000";

function JobMatchesCard({ data, userId }) {
  const jobs = data?.jobs || [];

  // Save-state per job, keyed by the same dedupe key the backend uses
  // (apply_link, falling back to title): "saving" | "saved" | "error".
  const [saveStates, setSaveStates] = useState({});

  const handleSave = async (job) => {
    const key = job.apply_link || job.title;
    setSaveStates((prev) => ({ ...prev, [key]: "saving" }));

    try {
      await axios.post(`${BACKEND_URL}/save-job`, {
        user_id: userId,
        job,
      });
      // Success = HTTP 2xx. Don't inspect the reply string: axios only
      // resolves here for 2xx responses (it throws otherwise), so reaching
      // this line means the save went through regardless of the exact reply
      // text. Network errors / non-2xx land in the catch below.
      setSaveStates((prev) => ({ ...prev, [key]: "saved" }));
    } catch (err) {
      console.error("Save job failed:", err);
      setSaveStates((prev) => ({ ...prev, [key]: "error" }));
    }
  };

  return (
    <div className="job-matches-card">
      <h3>Top Job Matches</h3>
      <p>Ranked using your resume profile and the existing job-matching score.</p>
      {jobs.length === 0 ? (
        <p>No matching jobs were returned.</p>
      ) : (
        jobs.map((job, index) => {
          const key = job.apply_link || job.title;
          const saveState = saveStates[key];
          return (
            <div className="job-match" key={`${job.title}-${index}`}>
              <div className="job-match-header">
                <strong>{index + 1}. {job.title}</strong>
                <span>{job.score}/100</span>
              </div>
              <div className="job-match-meta">
                {job.classification} · {job.experience_match} · {job.location_match}
              </div>
              {job.matched_skills?.length > 0 && (
                <div>Matched skills: {job.matched_skills.join(", ")}</div>
              )}
              {job.required_experience && <div>Experience: {job.required_experience}</div>}
              <div className="job-actions">
                {job.apply_link && (
                  <a href={job.apply_link} target="_blank" rel="noreferrer">Apply / View job</a>
                )}
                {userId && (
                  <button
                    type="button"
                    className={`save-btn ${saveState === "saved" ? "saved" : ""}`}
                    onClick={() => handleSave(job)}
                    disabled={saveState === "saving" || saveState === "saved"}
                    title="Save this job to your shortlist"
                  >
                    {saveState === "saving"
                      ? "Saving…"
                      : saveState === "saved"
                      ? "✓ Saved"
                      : saveState === "error"
                      ? "⚠ Retry"
                      : "💾 Save"}
                  </button>
                )}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}

export default JobMatchesCard;
