import { useEffect, useState } from "react";
import { LEVELS, useTwinResource } from "../lib/twin.js";
import AgentFlow from "./AgentFlow.jsx";
import "../styles/agentactivity.css";

const when = (ts) => {
  const d = new Date(ts);
  const t = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return d.toDateString() === new Date().toDateString() ? t : `${d.toLocaleDateString([], { day: "numeric", month: "short" })} ${t}`;
};
const cap = (s) => (s ? s[0] + s.slice(1).toLowerCase() : "");
const SEV_LEVEL = { WARNING: 1, MAJOR: 2, CRITICAL: 3 };

/** How the agent worked out one issue: every step it took, with the readings behind it. */
function Reasoning({ id, onGo }) {
  const res = useTwinResource(`/issues/${id}`);
  const d = res.data;
  if (!d) return <section className="card aa-card"><p className="aa-empty">{res.error || "Loading…"}</p></section>;
  const steps = d.analysis?.steps || [];
  return (
    <section className="card aa-card" aria-label={`How the agent worked out ${d.code}`}>
      <div className="aa-head">
        <h3>How the agent worked out {d.code}</h3>
        <span className={`lvl lvl-${SEV_LEVEL[d.severity] ?? 1}`}><span className="lvl-dot" />{cap(d.severity)}</span>
      </div>
      <p className="aa-note" style={{ color: "var(--text-primary)", fontWeight: 650 }}>{d.title}</p>
      {steps.length === 0 ? <p className="aa-empty">No analysis was recorded for this issue.</p> : (
        <ol className="aa-steps">
          {steps.map((s) => (
            <li key={s.key}>
              <span className={`aa-n${s.ok === null || s.ok === undefined ? " wait" : ""}`} aria-hidden="true">{s.ok === null || s.ok === undefined ? "…" : "✓"}</span>
              <div><b>{s.title}</b><p>{s.detail}</p></div>
            </li>
          ))}
        </ol>
      )}
      {d.evidence?.length > 0 && (
        <table className="aa-table">
          <thead><tr><th>Evidence</th><th>Now</th><th>Expected</th><th>Level</th></tr></thead>
          <tbody>
            {d.evidence.map((e) => (
              <tr key={e.tag}><td>{e.equipment}: {e.label}</td><td>{e.value} {e.unit}</td><td>{e.expected}</td><td>{LEVELS[e.level] || "Normal"}</td></tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="aa-note">Rules decide what is abnormal, so the same readings always give the same answer. The AI model only explains it in the chat. Nothing here operates equipment.</p>
      {onGo && <div><button type="button" className="btn ghost xs" onClick={() => onGo("issues")}>Open the Issues page</button></div>}
    </section>
  );
}

/** Agent activity: what the agent did, and why. The older analysis of the stored history is the second tab. */
export default function AgentActivity({ onAlertsChanged, onGo }) {
  const [tab, setTab] = useState("activity");
  const [sel, setSel] = useState(null);
  const res = useTwinResource("/agent/activity?days=7&limit=60");
  const d = res.data;
  const feed = d?.feed || [];
  useEffect(() => { if (feed.length && !feed.some((f) => f.issue_id === sel)) setSel(feed[0].issue_id); }, [feed.length]);     // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="page aa-page">
      <header className="page-head">
        <div>
          <h2>Agent activity</h2>
          <p className="muted">What the agent did, and why: each detection, hand-off, escalation and verification, with the steps behind it.</p>
        </div>
      </header>

      <div className="aa-tabs" role="group" aria-label="View">
        <button type="button" aria-pressed={tab === "activity"} onClick={() => setTab("activity")}>Agent activity</button>
        <button type="button" aria-pressed={tab === "history"} onClick={() => setTab("history")}>History analysis</button>
      </div>

      {tab === "activity" ? (
        <>
          <section className="aa-tiles" aria-label="Today">
            <div className="aa-tile"><b>{d ? d.today.detected : "…"}</b><span>detected today</span></div>
            <div className="aa-tile"><b>{d ? d.today.handed_off : "…"}</b><span>sent to the person on shift</span></div>
            <div className="aa-tile"><b>{d ? d.today.escalated : "…"}</b><span>escalated when not acknowledged</span></div>
            <div className="aa-tile"><b>{d ? d.today.verified : "…"}</b><span>verified from the readings</span></div>
            <div className="aa-tile"><b>{d ? d.actions_on_equipment : "…"}</b><span>actions on equipment, ever</span></div>
          </section>

          <div className="aa-grid">
            <section className="card aa-card" aria-label="What the agent did">
              <h3>What the agent did <span className="muted small" style={{ fontWeight: 500 }}>last 7 days</span></h3>
              {res.error && !d && <p className="aa-empty">{res.error}</p>}
              {d && feed.length === 0 && <p className="aa-empty">The agent has not recorded any actions in the last 7 days.</p>}
              <ul className="aa-feed">
                {feed.map((f, i) => (
                  <li key={`${f.issue_id}-${f.ts}-${i}`}>
                    <button type="button" aria-pressed={f.issue_id === sel} onClick={() => setSel(f.issue_id)}>
                      <time>{when(f.ts)}</time><i className={`aa-dot ${f.kind}`} />
                      <div><b>{f.title}</b><span>{f.text}</span></div>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
            {sel != null ? <Reasoning key={sel} id={sel} onGo={onGo} /> : <section className="card aa-card"><p className="aa-empty">Choose an action to see how the agent worked it out.</p></section>}
          </div>
        </>
      ) : <AgentFlow onAlertsChanged={onAlertsChanged} />}
    </div>
  );
}
