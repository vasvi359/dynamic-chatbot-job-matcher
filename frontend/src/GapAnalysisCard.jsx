function Ring({ pct, color }) {
  const r = 46, c = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(100, pct));
  const offset = c - (clamped / 100) * c;
  return (
    <svg width="120" height="120" viewBox="0 0 120 120">
      <circle cx="60" cy="60" r={r} fill="none" stroke="#1e3a32" strokeWidth="10" />
      <circle
        cx="60" cy="60" r={r} fill="none" stroke={color} strokeWidth="10"
        strokeLinecap="round" strokeDasharray={c} strokeDashoffset={offset}
        transform="rotate(-90 60 60)"
      />
      <text x="60" y="56" textAnchor="middle" fill="#eafaf5" fontSize="22" fontWeight="700">
        {clamped}%
      </text>
      <text x="60" y="74" textAnchor="middle" fill="#8fb3a9" fontSize="10">
        Match
      </text>
    </svg>
  );
}

export default function GapAnalysisCard({ data }) {
  return (
    <div className="gap-card">
      <div className="gap-card-title">✦ Your Gap Analysis</div>
      <div className="gap-card-note">
        Comparing your current profile against your target role.
      </div>

      <div className="gap-card-body">
        <div className="gauge-block">
          <div className="gauge-label">Current</div>
          <Ring pct={data.currentMatch} color="#5eead4" />
          <div className="gauge-role">{data.currentRole}</div>
        </div>

        <div className="gauge-block">
          <div className="gauge-label">Target</div>
          <Ring pct={data.targetMatch} color="#5ee0f0" />
          <div className="gauge-role">{data.targetRole}</div>
        </div>

        <div className="missing">
          <div className="missing-label">Top Missing Skills</div>
          <ul>
            {data.missingSkills.slice(0, 5).map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}