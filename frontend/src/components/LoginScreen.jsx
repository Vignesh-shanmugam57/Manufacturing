import { useState } from "react";
import { api } from "../api/client.js";
import { IconBell, IconCheck, IconGauge, IconMoon, IconScan, IconShield, IconSun } from "./icons.jsx";
import { Logo } from "./Logo.jsx";

const ROLES = ["Utilities engineer", "Maintenance", "Facilities", "Operations", "Plant management", "Other"];

const POINTS = [
  { icon: <IconGauge width={18} height={18} />, title: "Monitor", text: "Compressed air, chilled and process water, HVAC and nitrogen, all in one health board." },
  { icon: <IconScan width={18} height={18} />, title: "Detect", text: "Abnormal consumption, unstable pressure and leak indicators, found from the data." },
  { icon: <IconBell width={18} height={18} />, title: "Alert", text: "Facilities and maintenance get a clear, advisory alert with an owner." },
  { icon: <IconCheck width={18} height={18} />, title: "Verify", text: "The return to normal is confirmed by telemetry, never by hand." },
];

export default function LoginScreen({ onLogin, theme, onToggleTheme }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState(ROLES[0]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onLogin(await api.login(email.trim(), name.trim(), role));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login login-split">
      <button className="icon-btn login-theme" onClick={onToggleTheme} aria-label="Toggle dark mode">
        {theme === "light" ? <IconMoon /> : <IconSun />}
      </button>

      <aside className="login-brand" aria-label="About the agent">
        <Logo onDark height={50} />
        <div className="login-pitch">
          <p className="login-kicker">Utilities Management Agent</p>
          <h2>Keep plant utilities reliable and efficient.</h2>
          <ul className="login-points">
            {POINTS.map((p) => (
              <li key={p.title}>
                <span className="login-point-icon" aria-hidden="true">{p.icon}</span>
                <div><strong>{p.title}</strong><span>{p.text}</span></div>
              </li>
            ))}
          </ul>
        </div>
        <p className="login-foot"><IconShield width={15} height={15} /> Advisory only: the agent never changes setpoints or operates equipment.</p>
      </aside>

      <form className="login-card" onSubmit={submit} aria-labelledby="login-title">
        <div className="login-card-head">
          <h1 id="login-title">Sign in</h1>
          <p className="muted">Use your work email. Your conversations with the agent are saved to your account.</p>
        </div>
        <label className="field">
          <span>Work email</span>
          <input type="email" required autoComplete="email" value={email} placeholder="name@company.com"
                 onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="field">
          <span>Full name</span>
          <input required autoComplete="name" value={name} placeholder="Jordan Smith" maxLength={120}
                 onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="field">
          <span>Role</span>
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((r) => <option key={r}>{r}</option>)}
          </select>
        </label>
        {error && <div className="form-error" role="alert">{error}</div>}
        <button className="btn primary block" disabled={busy}>{busy ? "Signing in…" : "Continue"}</button>
        <p className="login-note"><IconShield width={14} height={14} /> New here? Your account is created the first time you continue.</p>
      </form>
    </main>
  );
}
