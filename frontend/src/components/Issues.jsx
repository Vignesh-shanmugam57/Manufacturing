import { useEffect, useMemo, useState } from "react";
import { twinApi } from "../api/client.js";
import { useTwinResource } from "../lib/twin.js";
import "../styles/issues.css";

const SEVERITIES = ["ALL", "CRITICAL", "MAJOR", "WARNING"];
const STATUS_OPEN_ACTIONS = {
  ack: ["OPEN"], investigate: ["ACKNOWLEDGED", "ASSIGNED"], fix: ["ACKNOWLEDGED", "ASSIGNED", "INVESTIGATING"],
  verify: ["CORRECTIVE_ACTION"], reopen: ["CORRECTIVE_ACTION", "VERIFIED"], assign: ["OPEN", "ACKNOWLEDGED", "ASSIGNED", "INVESTIGATING"],
};

/** 2h 14m, 3d 5h, 11m 04s. */
function dur(sec) {
  if (sec == null) return "-";
  const s0 = Math.max(0, Math.floor(sec));
  const d = Math.floor(s0 / 86400), h = Math.floor((s0 % 86400) / 3600), m = Math.floor((s0 % 3600) / 60), s = s0 % 60;
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m ${String(s).padStart(2, "0")}s`;
}
const short = (sec) => (sec < 60 ? "0m" : sec < 3600 ? `${Math.round(sec / 60)}m` : sec < 86400 ? `${Math.floor(sec / 3600)}h ${Math.round((sec % 3600) / 60)}m` : `${Math.floor(sec / 86400)}d ${Math.floor((sec % 86400) / 3600)}h`);
const when = (ts) => {
  if (!ts) return "";
  const d = new Date(ts);
  const t = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return d.toDateString() === new Date().toDateString() ? t : `${d.toLocaleDateString([], { day: "numeric", month: "short" })} ${t}`;
};
const firstSentence = (t) => (t || "").split(/(?<=\.)\s/)[0];

function useNow(ms = 1000) {
  const [n, setN] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setN(Date.now()), ms); return () => clearInterval(t); }, [ms]);
  return n;
}

/** How long it has been open right now: the server's age at the last refresh plus the time since. */
function live(i, drift) {
  const age = i.open ? (i.time.age_s ?? 0) + drift : i.time.age_s;
  const unack = i.open && i.status === "OPEN" ? (i.time.unacknowledged_for_s ?? i.time.age_s ?? 0) + drift : null;
  const ackLate = unack != null && unack > (i.time.ack_target_s ?? 1800);
  const overdue = i.open && age != null && age > (i.time.resolve_target_s ?? Infinity);
  return { age, unack, ackLate, overdue };
}

function IssueRow({ i, selected, onSelect, drift }) {
  const l = live(i, drift);
  const who = i.who;
  return (
    <button type="button" className="iss-row" data-sev={i.severity} aria-pressed={selected} onClick={() => onSelect(i.id)}>
      <span className="iss-sev" aria-hidden="true" />
      <span className="iss-main">
        <span className="iss-t1">
          <span className="iss-title">{i.title}</span>
          <span className="iss-pill">{i.stage}</span>
          {i.open && i.flags.escalated && <span className="iss-pill bad">Escalated</span>}
          {l.ackLate && <span className="iss-pill bad">Not acknowledged for {dur(l.unack)}</span>}
          {l.overdue && <span className="iss-pill bad">Overdue</span>}
        </span>
        <span className="iss-meta">
          <span>Where: <b>{i.where.zone} / {i.where.equipment_name}</b></span>
          <span>{i.what.actual} (expected {i.what.expected})</span>
        </span>
        <span className="iss-meta">
          <span>
            <i className={`iss-dot${who.on_shift_now === false ? " off" : ""}`} />
            {who.name ? <><b>{who.name}</b>{who.role ? `, ${who.role}` : ""}{who.phone_ext ? `, ext ${who.phone_ext}` : ""}{i.open && who.on_shift_now === false ? " (shift ended)" : ""}</> : "Nobody assigned"}
          </span>
        </span>
        <span className="iss-do"><b>Do:</b> {firstSentence(i.todo)}</span>
      </span>
      <span className={`iss-timer${l.ackLate || l.overdue ? " late" : ""}`}>
        <b>{dur(l.age)}</b>
        <span>{i.open ? "open for" : "time to close"}{i.open && i.time.ack_target_s ? <><br />target {Math.round(i.time.ack_target_s / 60)} min to acknowledge</> : null}</span>
      </span>
    </button>
  );
}

function IssueDetail({ id, people, onChanged, onGo }) {
  const res = useTwinResource(`/issues/${id}`);
  const d = res.data;
  const nowMs = useNow();
  const fetchedAt = useMemo(() => Date.now(), [d]);          // eslint-disable-line react-hooks/exhaustive-deps
  const [note, setNote] = useState("");
  const [assignee, setAssignee] = useState("");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => { setNote(""); setAssignee(""); setErr(""); }, [id]);

  if (!d) return <aside className="card iss-detail"><p className="muted">{res.error || "Loading…"}</p></aside>;
  const l = live(d, (nowMs - fetchedAt) / 1000);
  const st = d.status;
  const can = (k) => STATUS_OPEN_ACTIONS[k].includes(st);
  const sorted = [...people].sort((a, b) => Number(b.on_shift_now) - Number(a.on_shift_now) || a.name.localeCompare(b.name));
  const suggestion = d.open && d.who.on_shift_now === false
    ? people.find((p) => p.on_shift_now && p.team === d.who.team && p.name !== d.who.name) || people.find((p) => p.on_shift_now && p.team === "Utilities engineer")
    : null;

  async function act(action, extra = {}) {
    setBusy(action); setErr("");
    try {
      await twinApi.post(`/alerts/${id}/actions`, { action, ...extra });
      setNote("");
      await res.reload();
      onChanged();
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  }

  return (
    <aside className="card iss-detail" aria-label={`Issue ${d.code}`}>
      <div>
        <p className="eyebrow">{d.code} · {d.utility_label} · {d.severity[0] + d.severity.slice(1).toLowerCase()}</p>
        <h3>{d.title}</h3>
        <p className="small" style={{ marginTop: 6 }}>
          <span className="iss-pill">{d.stage}</span>{" "}
          {d.open ? <>open for <b>{dur(l.age)}</b></> : <>closed after <b>{dur(d.time.age_s)}</b></>}
          {d.time.time_to_ack_s != null && <> · acknowledged after {dur(d.time.time_to_ack_s)}</>}
        </p>
      </div>

      <div className="iss-sec">
        <h4>What happened</h4>
        <p><b>{d.what.actual}</b> (expected {d.what.expected})</p>
        <p>{d.what.probable_cause}</p>
        <p>{d.what.impact}</p>
        {d.evidence.length > 1 && (
          <p className="small muted">Also: {d.evidence.slice(1).map((e) => `${e.label.toLowerCase()} ${e.value} ${e.unit}`.trim()).join("; ")}.</p>
        )}
      </div>

      <div className="iss-sec">
        <h4>What to do</h4>
        <p>{d.todo}</p>
        {d.resolution && <p><b>Fix recorded:</b> {d.resolution}</p>}
      </div>

      <div className="iss-sec">
        <h4>Where and who</h4>
        <p><b>{d.where.zone}</b>, {d.where.equipment_name}{d.where.consumers.length ? <><br />Supplies: {d.where.consumers.join(", ")}</> : null}</p>
        <p>
          <i className={`iss-dot${d.who.on_shift_now === false ? " off" : ""}`} />
          {d.who.name ? <><b>{d.who.name}</b>{d.who.role ? `, ${d.who.role}` : ""}<br />{d.who.phone_ext ? `Ext ${d.who.phone_ext} · ` : ""}{d.who.shift ? `shift ${d.who.shift} (${d.who.shift_hours})` : ""}</> : "Nobody assigned yet"}
        </p>
        {d.notifications?.length > 0 && <p className="small muted">Notified: {[...new Set(d.notifications.map((n) => n.recipient))].join(", ")}</p>}
        {suggestion && (
          <p className="iss-suggest">
            This shift has ended. On shift now: <b>{suggestion.name}</b> ({suggestion.role}, ext {suggestion.phone_ext}).{" "}
            <button type="button" className="btn ghost xs" disabled={!!busy} onClick={() => act("assign", { assignee: suggestion.name })}>Reassign</button>
          </p>
        )}
        <button type="button" className="btn ghost xs" onClick={() => onGo("map", d.where.equipment_id)}>Show on plant map</button>
      </div>

      {d.open && (
        <div className="iss-sec iss-acts">
          {can("ack") && <button type="button" className="btn primary xs" disabled={!!busy} onClick={() => act("acknowledge")}>Acknowledge</button>}
          {can("investigate") && <button type="button" className="btn ghost xs" disabled={!!busy} onClick={() => act("investigate")}>Start investigating</button>}
          {can("verify") && <button type="button" className="btn primary xs" disabled={!!busy} onClick={() => act("verify")}>Verify with telemetry</button>}
          {can("assign") && (
            <>
              <select value={assignee} onChange={(e) => setAssignee(e.target.value)} aria-label="Reassign to">
                <option value="">Reassign to…</option>
                {sorted.map((p) => <option key={p.id} value={p.name}>{p.name} ({p.role}{p.on_shift_now ? ", on shift" : ""})</option>)}
              </select>
              <button type="button" className="btn ghost xs" disabled={!assignee || !!busy} onClick={() => act("assign", { assignee })}>Assign</button>
            </>
          )}
          <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add a note, or describe the fix that was done" aria-label="Note" />
          <button type="button" className="btn ghost xs" disabled={!note.trim() || !!busy} onClick={() => act("comment", { comment: note })}>Add note</button>
          {can("fix") && <button type="button" className="btn ghost xs" disabled={!note.trim() || !!busy} onClick={() => act("corrective_action", { comment: note })}>Record the fix</button>}
          {can("reopen") && <button type="button" className="btn ghost xs" disabled={!!busy} onClick={() => act("reopen")}>Reopen</button>}
          {err && <p className="iss-err" role="alert">{err}</p>}
        </div>
      )}
      {!d.open && can("reopen") && (
        <div className="iss-sec iss-acts">
          <button type="button" className="btn ghost xs" disabled={!!busy} onClick={() => act("reopen")}>Reopen</button>
          {err && <p className="iss-err" role="alert">{err}</p>}
        </div>
      )}

      <div className="iss-sec">
        <h4>Timeline</h4>
        <ol className="iss-tl">
          {d.timeline.map((e, k) => (
            <li key={k}><em>+{short(e.after_start_s ?? 0)}</em><span>{e.detail}<small>{e.actor} · {when(e.ts)}</small></span></li>
          ))}
        </ol>
      </div>
    </aside>
  );
}

/** Issues: every utility problem, where it is, who has to go, how long it has been open and what to do. */
export default function Issues({ onGo }) {
  const [tab, setTab] = useState("open");
  const [sev, setSev] = useState("ALL");
  const [zone, setZone] = useState("");
  const [selId, setSelId] = useState(null);
  const list = useTwinResource(tab === "open" ? "/issues?status=open" : "/issues?status=closed&limit=40", 30000);
  const sum = useTwinResource("/issues/summary", 30000);
  const ppl = useTwinResource("/people");
  const nowMs = useNow();
  const fetchedAt = useMemo(() => Date.now(), [list.data]);       // eslint-disable-line react-hooks/exhaustive-deps

  const rows = list.data?.issues || [];
  const zones = [...new Set(rows.map((r) => r.where.zone))].sort();
  const shown = rows.filter((r) => (sev === "ALL" || r.severity === sev) && (!zone || r.where.zone === zone));
  const ids = shown.map((r) => r.id).join(",");
  useEffect(() => { if (!shown.some((r) => r.id === selId)) setSelId(shown[0]?.id ?? null); }, [ids]);   // eslint-disable-line react-hooks/exhaustive-deps

  const s = sum.data;
  const changed = () => { list.reload(); sum.reload(); ppl.reload(); };
  const tile = (value, label, hot) => <div className={`iss-tile${hot ? " hot" : ""}`}><b>{value}</b><span>{label}</span></div>;

  return (
    <div className="page iss-page">
      <header className="page-head">
        <div>
          <h2>Issues</h2>
          <p className="muted">What is wrong, where, who has to go, how long it has been open and what to do.</p>
        </div>
      </header>

      <section className="iss-tiles" aria-label="Summary">
        {tile(s ? s.open : "…", "Open issues")}
        {tile(s ? s.needs_attention : "…", "Need attention", s && s.needs_attention > 0)}
        {tile(s ? s.unacknowledged : "…", "Not acknowledged")}
        {tile(s ? s.overdue : "…", "Overdue", s && s.overdue > 0)}
        {tile(s ? dur(s.avg_time_to_acknowledge_s) : "…", "Average time to acknowledge (30 days)")}
        {tile(s ? dur(s.avg_time_to_resolve_s) : "…", "Average time to close (30 days)")}
      </section>

      <div className="iss-bar">
        <div className="iss-seg" role="group" aria-label="Open or closed">
          <button type="button" aria-pressed={tab === "open"} onClick={() => setTab("open")}>Open</button>
          <button type="button" aria-pressed={tab === "closed"} onClick={() => setTab("closed")}>Closed</button>
        </div>
        {SEVERITIES.map((x) => (
          <button type="button" key={x} className="iss-chip" aria-pressed={sev === x} onClick={() => setSev(x)}>
            {x === "ALL" ? "All severities" : x[0] + x.slice(1).toLowerCase()}
          </button>
        ))}
        <select value={zone} onChange={(e) => setZone(e.target.value)} aria-label="Zone">
          <option value="">All zones</option>
          {zones.map((z) => <option key={z} value={z}>{z}</option>)}
        </select>
        <span className="iss-sort">{tab === "open" ? "Needs attention first, then most severe, then oldest" : "Most recently closed first"}</span>
      </div>

      <div className="iss-layout">
        <div className="iss-list" role="list">
          {list.loading && !list.data && <p className="iss-empty">Loading issues…</p>}
          {list.error && !list.data && <p className="iss-empty">The issues could not be loaded: {list.error}</p>}
          {list.data && shown.length === 0 && <p className="iss-empty card">{tab === "open" ? "No open issues. Everything is within its limits." : "No closed issues match."}</p>}
          {shown.map((i) => <IssueRow key={i.id} i={i} selected={i.id === selId} onSelect={setSelId} drift={(nowMs - fetchedAt) / 1000} />)}
        </div>
        {selId != null && <IssueDetail key={selId} id={selId} people={ppl.data?.people || []} onChanged={changed} onGo={onGo} />}
      </div>
    </div>
  );
}
