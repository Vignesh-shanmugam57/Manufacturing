import { useState } from "react";
import { api } from "../api/client.js";
import { useCached } from "../hooks/useCached.js";
import { invalidate } from "../lib/cache.js";
import { formatDateTime, timeAgo, utilityLabel } from "../lib/format.js";
import StatusPill from "./StatusPill.jsx";
import { SAMPLE_ALERTS } from "./sampleAlerts.js";
import { IconBell, IconCheck, IconScan, IconShield, IconTool, Spinner } from "./icons.jsx";

// An alert moves OPEN -> ACKNOWLEDGED -> RESOLVED by people, and VERIFIED only when telemetry confirms the return
// to normal. The progress line on each card shows where it is and when each step happened.
const STEPS = [
  { key: "OPEN", label: "Raised", at: "created_at" },
  { key: "ACKNOWLEDGED", label: "Acknowledged", at: "acknowledged_at" },
  { key: "RESOLVED", label: "Resolved", at: "resolved_at" },
  { key: "VERIFIED", label: "Verified", at: "verified_at" },
];
const STEP_INDEX = { OPEN: 0, ACKNOWLEDGED: 1, RESOLVED: 2, VERIFIED: 3 };
// Who can own an issue. The owner is recorded on the issue, with the name of the person who assigned it.
const TEAMS = ["Maintenance team", "Facilities team", "Utilities engineer", "Instrument technician", "Safety officer", "Production team"];

function Details({ details }) {
  if (!details) return null;
  let parsed = null;
  if (details.trim().startsWith("{")) {
    try { parsed = JSON.parse(details); } catch { parsed = null; }
  }
  if (!parsed) return <p className="small muted">{details}</p>;
  const evidence = Object.entries(parsed.evidence || {}).filter(([, v]) => v !== null && typeof v !== "object");
  return (
    <details className="alert-details">
      <summary>Evidence</summary>
      {parsed.likely_cause && <p className="small"><strong>Likely cause:</strong> {parsed.likely_cause}</p>}
      <dl className="evidence">
        {evidence.map(([k, v]) => (<div key={k}><dt>{k.replace(/_/g, " ")}</dt><dd>{String(v)}</dd></div>))}
      </dl>
    </details>
  );
}

function Lifecycle({ alert }) {
  const idx = STEP_INDEX[alert.status] ?? 0;
  return (
    <ol className={`life${alert.status === "VERIFIED" ? " final" : ""}`} aria-label="Alert progress">
      {STEPS.map((s, i) => (
        <li key={s.key} className={i < idx ? "done" : i === idx ? "now" : ""}>
          <span className="life-dot" aria-hidden="true">{i <= idx && <IconCheck width={11} height={11} />}</span>
          <span className="life-label">{s.label}</span>
          <span className="life-time">{i <= idx && alert[s.at] ? formatDateTime(alert[s.at]) : "-"}</span>
        </li>
      ))}
    </ol>
  );
}

function AlertCard({ alert, onChanged }) {
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");
  const [resolving, setResolving] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [owner, setOwner] = useState(alert.assigned_to || "");

  async function act(kind, fn) {
    setBusy(kind);
    setError("");
    try {
      const res = await fn();
      if (kind === "verify") setResult(res);
      await onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  }

  const s = alert.status;
  const sample = !!alert.sample;
  return (
    <article className={`card alert-card al-card sev-${alert.severity.toLowerCase()}`} aria-label={alert.title}>
      <header className="al-head">
        <span className="al-icon" aria-hidden="true"><IconBell width={18} height={18} /></span>
        <div className="al-titles">
          <h3 className="alert-title">{alert.title}</h3>
          <p className="al-meta">
            <span className="al-chip strong">{utilityLabel(alert.utility_type)}</span>
            {alert.plant_id && <span className="al-chip">{alert.plant_id}</span>}
            {alert.zone && <span className="al-chip">{alert.zone}</span>}
            <span className="al-chip">Assigned to <strong>{alert.assigned_to}</strong></span>
            <span className="al-id">{sample ? "Sample, not stored" : `#${alert.id} · ${alert.source}`} · {timeAgo(alert.created_at)}</span>
          </p>
        </div>
        <div className="al-pills">
          <StatusPill value={alert.severity} />
          <StatusPill value={s} />
          {sample && <span className="sample-tag">Sample</span>}
        </div>
      </header>

      <Lifecycle alert={alert} />

      {alert.recommendation && (
        <div className="al-rec">
          <span className="al-rec-icon" aria-hidden="true"><IconTool width={16} height={16} /></span>
          <div><strong>Recommended action</strong><p>{alert.recommendation}</p></div>
        </div>
      )}
      <Details details={alert.details} />
      {alert.status_note && <p className="small muted al-note">Note: {alert.status_note}</p>}

      {resolving && (
        <form className="resolve" onSubmit={(e) => {
          e.preventDefault();
          setResolving(false);
          act("resolve", () => api.setAlertStatus(alert.id, "RESOLVED", note));
        }}>
          <input autoFocus value={note} maxLength={1000} placeholder="What was done? (optional)"
                 aria-label="Resolution note" onChange={(e) => setNote(e.target.value)} />
          <button className="btn primary xs">Mark resolved</button>
          <button type="button" className="btn ghost xs" onClick={() => setResolving(false)}>Cancel</button>
        </form>
      )}

      {!sample && (
        <div className="assign-row">
          <label className="small muted">
            Owner{" "}
            <select value={owner} onChange={(e) => setOwner(e.target.value)} aria-label="Assign to">
              {[...new Set([alert.assigned_to, ...TEAMS].filter(Boolean))].map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
          <button className="btn ghost xs" disabled={!!busy || !owner || owner === alert.assigned_to}
                  onClick={() => act("assign", () => api.assignAlert(alert.id, owner))}>
            {busy === "assign" && <Spinner size={12} />} Assign
          </button>
        </div>
      )}
      {!sample && <div className="alert-actions">
        {s === "OPEN" && (
          <button className="btn ghost xs" disabled={!!busy}
                  onClick={() => act("ack", () => api.setAlertStatus(alert.id, "ACKNOWLEDGED"))}>
            {busy === "ack" && <Spinner size={12} />} Acknowledge
          </button>
        )}
        {(s === "OPEN" || s === "ACKNOWLEDGED") && !resolving && (
          <button className="btn ghost xs" disabled={!!busy} onClick={() => setResolving(true)}>
            {busy === "resolve" && <Spinner size={12} />} Resolve…
          </button>
        )}
        {s !== "VERIFIED" && (
          <button className="btn ghost xs" disabled={!!busy} onClick={() => act("verify", () => api.verifyAlert(alert.id))}>
            {busy === "verify" && <Spinner size={12} />} Verify with telemetry
          </button>
        )}
        {(s === "RESOLVED" || s === "VERIFIED") && (
          <button className="btn ghost xs" disabled={!!busy} onClick={() => act("reopen", () => api.setAlertStatus(alert.id, "OPEN"))}>
            Reopen
          </button>
        )}
      </div>}
      {sample && <p className="small muted al-note">Sample alert for demonstration. It is not stored, so it cannot be acknowledged, resolved or verified.</p>}
      {result && (
        <p className={`verify-result ${result.normal ? "ok" : "not-ok"}`} role="status">{result.message}</p>
      )}
      {error && <p className="form-error" role="alert">{error}</p>}
    </article>
  );
}

function Stat({ label, value, caption, tone = "neutral" }) {
  return (
    <div className={`dkpi tone-${tone}`}>
      <div className="dkpi-top"><span className="dkpi-label">{label}</span></div>
      <div className="dkpi-value">{value}</div>
      <div className="dkpi-cap">{caption}</div>
    </div>
  );
}

export default function AlertsPanel({ onAlertsChanged }) {
  const [filter, setFilter] = useState("open");
  // Both lists are live (re-checked every 15 s). "alerts-all" is shared with the dashboard and the agent flow.
  const openQ = useCached("alerts-open", () => api.alerts("open"), 30_000, { pollMs: 15_000 });
  const allQ = useCached("alerts-all", () => api.alerts("all"), 30_000, { pollMs: 15_000 });
  const [scanning, setScanning] = useState(false);
  const [scan, setScan] = useState(null);
  const [scanError, setScanError] = useState("");

  // One source of truth, so the tiles, the tabs and the list always agree: the full list. The server caps it at
  // 50 rows, so only when more than that exist does the Open tab fall back to its own request.
  // Sample alerts sit beside the live ones, so the page is never empty. Their cards say Sample and are read-only, and
  // each tile says how many of its alerts are samples.
  const byNewest = (a, b) => new Date(b.created_at) - new Date(a.created_at);
  const isOpen = (a) => a.status === "OPEN" || a.status === "ACKNOWLEDGED";
  const complete = !!allQ.data && allQ.data.count < 50;
  const liveAll = allQ.data?.alerts || [];
  const everything = allQ.data ? [...liveAll, ...SAMPLE_ALERTS].sort(byNewest) : [];
  const liveOpen = complete ? liveAll.filter(isOpen) : (openQ.data?.alerts ?? null);
  const openList = liveOpen === null ? null : [...liveOpen, ...SAMPLE_ALERTS.filter(isOpen)].sort(byNewest);
  const list = filter === "open" ? openList : (allQ.data ? everything : null);
  const q = filter === "open" && !complete ? openQ : allQ;
  const count = (s) => everything.filter((a) => a.status === s).length;
  const note = (s) => {
    const n = SAMPLE_ALERTS.filter((a) => a.status === s).length;
    return n ? ` · ${n} sample` : "";
  };
  const shown = list || [];
  const firstLoad = list === null && q.loading;

  const reloadBoth = () => Promise.all([openQ.reload(), allQ.reload()]);
  const changed = async () => {
    invalidate();            // the other cached views (dashboard, flow, badge) are now out of date
    await reloadBoth();
    onAlertsChanged?.();
  };

  async function runScan() {
    setScanning(true); setScan(null); setScanError("");
    try {
      setScan(await api.scan());
      await changed();
    } catch (e) {
      setScanError(e.message);
    } finally {
      setScanning(false);
    }
  }

  return (
    <div className="page alerts-page">
      <header className="page-head">
        <div>
          <h2>Assign issues</h2>
          <p className="muted">Each problem the agent finds has one owner. Assign it, acknowledge it, record the corrective action, then the agent verifies recovery from telemetry.</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" onClick={runScan} disabled={scanning}>
            {scanning ? <Spinner /> : <IconScan width={16} height={16} />} Run monitoring scan
          </button>
        </div>
      </header>

      {scan && (
        <div className="banner" role="status">
          {scan.created_count === 0 && scan.already_open_count === 0
            ? "Scan complete: nothing abnormal needs an alert."
            : <>Scan raised <strong>{scan.created_count}</strong> new alert{scan.created_count === 1 ? "" : "s"}
                {scan.already_open_count > 0 && <> ({scan.already_open_count} already open)</>}.</>}
        </div>
      )}
      {(scanError || q.error) && <div className="chat-error" role="alert">{scanError || q.error}</div>}

      {allQ.data ? (
        <section className="dkpis al-stats" aria-label="Alert summary">
          <Stat label="Open" value={count("OPEN")} caption={`waiting for a person${note("OPEN")}`} tone={count("OPEN") ? "warn" : "ok"} />
          <Stat label="Acknowledged" value={count("ACKNOWLEDGED")} caption={`someone is looking at it${note("ACKNOWLEDGED")}`} />
          <Stat label="Resolved" value={count("RESOLVED")} caption={`fixed, waiting for the data check${note("RESOLVED")}`} />
          <Stat label="Verified" value={count("VERIFIED")} caption={`confirmed back to normal by data${note("VERIFIED")}`} tone="ok" />
        </section>
      ) : (
        <div className="dkpis al-stats" aria-hidden="true">{[0, 1, 2, 3].map((i) => <div key={i} className="skel skel-kpi" />)}</div>
      )}

      <div className="al-toolbar">
        <div className="segmented" role="tablist" aria-label="Alert filter">
          {[["open", "Open", openList ? openList.length : null], ["all", "All", allQ.data ? everything.length : null]].map(([f, label, n]) => (
            <button key={f} role="tab" aria-selected={filter === f} className={filter === f ? "active" : ""}
                    onClick={() => setFilter(f)}>{label}<span className="tab-count">{n ?? "·"}</span></button>
          ))}
        </div>
        {q.refreshing && <span className="small muted al-updating"><Spinner size={12} /> Updating…</span>}
      </div>

      {firstLoad && <div className="skel skel-block" aria-label="Loading alerts" />}

      {list !== null && shown.length === 0 && (
        <div className="empty-state card clear">
          <span className="clear-icon" aria-hidden="true"><IconShield width={28} height={28} /></span>
          <h3>{filter === "open" ? "No open alerts" : "No alerts yet"}</h3>
          <p className="muted">
            {filter === "open"
              ? "All clear: nothing abnormal needs attention right now, and every utility is within its own normal pattern."
              : "The agent has not raised any alert so far."}
            {" "}A monitoring scan checks the latest data and raises an alert only when something real is found.
          </p>
          <button className="btn ghost" onClick={runScan} disabled={scanning}>
            {scanning ? <Spinner /> : <IconScan width={16} height={16} />} Run monitoring scan
          </button>
        </div>
      )}

      <div className="alerts">
        {shown.map((a) => <AlertCard key={`${a.id}-${a.status}`} alert={a} onChanged={changed} />)}
      </div>
    </div>
  );
}
