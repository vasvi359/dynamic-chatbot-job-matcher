export default function TopSkillsCard({ data }) {
  return (
    <div className="gap-card">
      <div className="gap-card-title">🏆 Your Top Skills</div>
      <div className="gap-card-note">Based on what you've shared.</div>
      <div className="skills-list">
        {data.skills.map((skill, i) => (
          <div key={i} className="skill-pill">
            {skill}
          </div>
        ))}
      </div>
    </div>
  );
}