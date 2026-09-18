import { useState, useEffect, useCallback } from "react";
import axios from "axios";

const BACKEND_URL = "http://127.0.0.1:8000";

function SavedJobsCard({ userId }) {
  const [savedJobs, setSavedJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchSavedJobs = useCallback(async () => {
    try {
      const res = await axios.get(`${BACKEND_URL}/saved-jobs/${userId}`);
      setSavedJobs(res.data?.saved_jobs || []);
      setError("");
    } catch (err) {
      console.error("Fetching saved jobs failed:", err);
      setError("Couldn't load your saved jobs. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    fetchSavedJobs();
  }, [fetchSavedJobs]);

  // Optimistic remove: drop the row immediately, fire DELETE in the
  // background, restore the previous list only if the delete failed.
  const handleRemove = async (jobId) => {
    const prevJobs = savedJobs;
    setSavedJobs((prev) => prev.filter((j) => j.id !== jobId));

    try {
      await axios.delete(`${BACKEND_URL}/saved-jobs/${jobId}`, {
        params: { user_id: userId },
      });
      // Axios only resolves on 2xx — a resolved promise means the row is
      // gone (including "Saved job not found." = nothing left to remove).
      // No reply text matching.
    } catch (err) {
      console.error("Remove saved job failed:", err);
      setSavedJobs(prevJobs); // restore
    }
  };

  return (
    <div className="job-matches-card">
      <h3>💾 Saved Jobs</h3>
      <p>Your shortlisted jobs, most recent first.</p>

      {loading ? (
        <p>Loading saved jobs…</p>
      ) : error ? (
        <p className="saved-jobs-error">{error}</p>
      ) : savedJobs.length === 0 ? (
        <p>No saved jobs yet — hit 💾 Save on a job match to add one here.</p>
      ) : (
        savedJobs.map((job, index) => (
          <div className="job-match" key={job.id ?? `${job.title}-${index}`}>
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
            {job.saved_at && (
              <div className="saved-at">Saved: {new Date(job.saved_at).toLocaleString()}</div>
            )}
            <div className="job-actions">
              {job.apply_link && (
                <a href={job.apply_link} target="_blank" rel="noreferrer">Apply / View job</a>
              )}
              <button
                type="button"
                className="remove-btn"
                onClick={() => handleRemove(job.id)}
                title="Remove from saved jobs"
              >
                ✕ Remove
              </button>
            </div>
          </div>
        ))
      )}
    </div>
  );
}

export default SavedJobsCard;
