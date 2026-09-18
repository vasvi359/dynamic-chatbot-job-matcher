function Bar({ label, value, max, color }) {
  const pct = Math.min(100, (value / max) * 100);
  return (
    <div className="exp-bar-row">
      <div className="exp-bar-label">
        {label}: <strong>{value} yrs</strong>
      </div>
      <div className="exp-bar-track">
        <div className="exp-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

export default function ExperienceGapCard({ data }) {
  const max = Math.max(data.currentYears, data.requiredYears) + 2;
  return (
    <div className="gap-card">
      <div className="gap-card-title">📊 Experience Comparison</div>
      <div className="gap-card-note">{data.roleName}</div>
      <Bar label="Your experience" value={data.currentYears} max={max} color="#5eead4" />
      <Bar label="Typically required" value={data.requiredYears} max={max} color="#5ee0f0" />
    </div>
  );
}