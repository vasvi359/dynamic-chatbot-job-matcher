import { useState, useRef, useEffect } from "react";
import axios from "axios";

function Eye({ mouse, originRef, size = 20 }) {
  const [pupil, setPupil] = useState({ x: 0, y: 0 });

  useEffect(() => {
    if (!originRef.current) return;
    const rect = originRef.current.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;

    const dx = mouse.x - cx;
    const dy = mouse.y - cy;
    const dist = Math.min(Math.hypot(dx, dy) / 18, size * 0.28);
    const angle = Math.atan2(dy, dx);

    setPupil({
      x: Math.cos(angle) * dist,
      y: Math.sin(angle) * dist,
    });
  }, [mouse, originRef, size]);

  return (
    <div className="lp-eye" style={{ width: size, height: size }}>
      <div
        className="lp-pupil"
        style={{ transform: `translate(${pupil.x}px, ${pupil.y}px)` }}
      />
    </div>
  );
}

function Mascot({ className, mouse, shape, eyeSize, eyeGap }) {
  const ref = useRef(null);

  return (
    <div ref={ref} className={`lp-mascot ${className}`}>
      <div className={`lp-mascot-body lp-shape-${shape}`}>
        <div className="lp-eyes-row" style={{ gap: eyeGap }}>
          <Eye mouse={mouse} originRef={ref} size={eyeSize} />
          <Eye mouse={mouse} originRef={ref} size={eyeSize} />
        </div>
      </div>
    </div>
  );
}

function MascotHero() {
  const [mouse, setMouse] = useState({ x: 0, y: 0 });

  useEffect(() => {
    const handleMove = (e) => setMouse({ x: e.clientX, y: e.clientY });
    window.addEventListener("mousemove", handleMove);
    return () => window.removeEventListener("mousemove", handleMove);
  }, []);

  return (
    <div className="lp-hero">
      <div className="lp-eyebrow">CAREER INTELLIGENCE</div>

      <h1 className="lp-headline">
        Know exactly
        <br />
        how far you are.
      </h1>

      <p className="lp-sub">
        Upload a resume. Get real, calculated gaps — not guesses.
      </p>

      <div className="lp-mascots">
        <Mascot
          className="lp-mascot-1"
          mouse={mouse}
          shape="round"
          eyeSize={26}
          eyeGap="10px"
        />

        <Mascot
          className="lp-mascot-2"
          mouse={mouse}
          shape="tall"
          eyeSize={18}
          eyeGap="7px"
        />

        <Mascot
          className="lp-mascot-3"
          mouse={mouse}
          shape="wide"
          eyeSize={22}
          eyeGap="12px"
        />
      </div>
    </div>
  );
}

export default function Login({ onLogin }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const endpoint = mode === "login" ? "/login" : "/register";

      const res = await axios.post(`http://127.0.0.1:8000${endpoint}`, {
        email,
        password,
      });

      onLogin(res.data.user_id, res.data.email);
    } catch (err) {
      setError(err.response?.data?.detail || "Something went wrong. Try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="lp-page">
      <div className="lp-left">
        <MascotHero />
      </div>

      <div className="lp-right">
        <div className="lp-card">
          <div className="lp-tabs">
            <button
              type="button"
              className={`lp-tab ${mode === "login" ? "lp-tab-active" : ""}`}
              onClick={() => setMode("login")}
            >
              Log in
            </button>

            <button
              type="button"
              className={`lp-tab ${
                mode === "register" ? "lp-tab-active" : ""
              }`}
              onClick={() => setMode("register")}
            >
              Register
            </button>

            <div
              className={`lp-tab-indicator ${
                mode === "register" ? "lp-tab-indicator-right" : ""
              }`}
            />
          </div>

          <form onSubmit={handleSubmit} className="lp-form">
            <h2 className="lp-form-title">
              {mode === "login" ? "Welcome back" : "Create your account"}
            </h2>

            <p className="lp-form-sub">
              {mode === "login"
                ? "Log in to pick up where you left off."
                : "Takes a few seconds — no card required."}
            </p>

            <label className="lp-field">
              <span className="lp-field-label">Email</span>

              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                required
              />
            </label>

            <label className="lp-field">
              <span className="lp-field-label">Password</span>

              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
              />
            </label>

            {error && <div className="lp-error">{error}</div>}

            <button type="submit" className="lp-submit" disabled={loading}>
              {loading
                ? "Please wait…"
                : mode === "login"
                ? "Log in"
                : "Create account"}
            </button>

            <div className="lp-switch">
              {mode === "login" ? (
                <>
                  No account?{" "}
                  <span onClick={() => setMode("register")}>
                    Register here
                  </span>
                </>
              ) : (
                <>
                  Already have one?{" "}
                  <span onClick={() => setMode("login")}>Log in</span>
                </>
              )}
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}