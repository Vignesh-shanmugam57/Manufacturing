import { useEffect, useMemo, useState } from "react";
import { api, connApi, twinApi } from "../api/client.js";
import { useCached } from "../hooks/useCached.js";
import { formatDateTime, number, timeAgo } from "../lib/format.js";
import DataPanel from "./DataPanel.jsx";
import { IconBolt, IconDatabase, IconFlow, IconGrid, IconPlug, IconTool, IconUpload, Spinner } from "./icons.jsx";
import "../styles/connectors.css";

const ICONS = { plug: IconPlug, antenna: IconPlug, building: IconGrid, database: IconDatabase, api: IconFlow, tool: IconTool, factory: IconTool, file: IconUpload, bolt: IconBolt };
const HOW = [
  ["Choose your system", "Pick the database, application or file you already have."],
  ["Enter the details and test", "Use a read-only account. The app checks it can reach the system and shows a sample."],
  ["Choose what to pull", "Pick the table or file, and where the data should go. Fields are matched for you."],
  ["It pulls on a schedule", "Every minute to every hour, or when you press Pull now. Nothing is ever written back."],
];

function Icon({ name }) {
  const C = ICONS[name] || IconPlug;
  return <C aria-hidden="true" />;
}

function rowsTable(columns, rows) {
  if (!rows?.length) return null;
  const cols = columns.slice(0, 7);
  return (
    <div className="cx-sample">
      <table className="cx-table">
        <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>{rows.slice(0, 5).map((r, i) => <tr key={i}>{cols.map((c) => <td key={c}>{String(r[c] ?? "")}</td>)}</tr>)}</tbody>
      </table>
      {columns.length > cols.length && <p className="cx-note">and {columns.length - cols.length} more columns</p>}
    </div>
  );
}

/** Connect a system in four steps: connection, test, what to pull, schedule. */
function Wizard({ kind, targets, schedules, onClose, onSaved }) {
  const fields = kind.fields;
  const isDb = kind.source_mode;
  const [step, setStep] = useState(1);
  const [vals, setVals] = useState(() => Object.fromEntries(fields.map((f) => [f.key, f.default ?? ""])));
  const [name, setName] = useState(kind.label);
  const [test, setTest] = useState(null);
  const [preview, setPreview] = useState(null);
  const [src, setSrc] = useState({ mode: "table", table: "", query: "", cursor_column: "" });
  const [target, setTarget] = useState(kind.kind === "demo_gateway" ? "utility" : "");
  const [map, setMap] = useState({ fields: [], columns: {}, missing: [] });
  const [schedule, setSchedule] = useState(300);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [done, setDone] = useState(null);

  useEffect(() => {
    const h = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  const secretKeys = useMemo(() => new Set(fields.filter((f) => f.secret).map((f) => f.key)), [fields]);
  const config = useMemo(() => Object.fromEntries(Object.entries(vals).filter(([k, v]) => !secretKeys.has(k) && v !== "")), [vals, secretKeys]);
  const secrets = useMemo(() => Object.fromEntries(Object.entries(vals).filter(([k, v]) => secretKeys.has(k) && v !== "")), [vals, secretKeys]);
  const missing = fields.filter((f) => f.required && !String(vals[f.key] ?? "").trim());
  const columns = (isDb ? preview?.columns : test?.columns) || [];
  const source = isDb ? { mode: src.mode, ...(src.mode === "table" ? { table: src.table } : { query: src.query }), ...(src.cursor_column ? { cursor_column: src.cursor_column } : {}) } : null;
  const sourceChosen = !isDb || (src.mode === "table" ? !!src.table : !!src.query.trim());
  const targetFields = targets.find((t) => t.key === target);

  async function run(label, fn) {
    setBusy(label); setErr("");
    try { return await fn(); } catch (e) { setErr(e.message); return null; } finally { setBusy(""); }
  }

  const doTest = () => run("test", async () => { setTest(null); setTest(await connApi.post("/test", { kind: kind.kind, config, secrets })); });
  const doPreview = () => run("preview", async () => {
    const r = await connApi.post("/test", { kind: kind.kind, config, secrets, source });
    setPreview(r);
    if (!r.ok) setErr(r.message);
  });
  const remap = (t, cols) => run("map", async () => { if (t && cols.length) setMap(await connApi.post("/suggest-mapping", { target: t, columns: cols })); });
  useEffect(() => { if (step === 3) remap(target, columns); }, [target, columns.join("|"), step]);        // eslint-disable-line react-hooks/exhaustive-deps

  const setCol = (field, col) => setMap((m) => {
    const columnsMap = { ...m.columns };
    if (col) columnsMap[field] = col; else delete columnsMap[field];
    return { ...m, columns: columnsMap, missing: m.fields.filter((f) => !columnsMap[f]) };
  });

  const canNext = step === 1 ? missing.length === 0 && !!name.trim()
    : step === 2 ? !!test?.ok
    : step === 3 ? !!target && sourceChosen && columns.length > 0 && map.missing.length === 0 && map.fields.length > 0
    : true;

  async function save() {
    const res = await run("save", () => connApi.post("", { kind: kind.kind, name: name.trim(), config, secrets, source, target, mapping: { columns: map.columns }, schedule_s: schedule, run_now: true }));
    if (res) { setDone(res.run); onSaved(); }
  }

  const labels = ["Connection", "Test", "What to pull", "Schedule"];
  return (
    <div className="cx-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="cx-modal" role="dialog" aria-modal="true" aria-label={`Connect ${kind.label}`}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
          <h3>Connect {kind.label}</h3>
          <button type="button" className="btn ghost xs" onClick={onClose}>{done ? "Close" : "Cancel"}</button>
        </div>

        {done ? (
          <>
            <div className={`cx-res ${done.ok ? "ok" : "bad"}`} role="status">
              {done.ok ? "Connected and saved. " : "Saved, but the first pull did not work. "}{done.message}
            </div>
            <p className="cx-note">The connection is in your list. It will pull {schedules.find((s) => s.seconds === schedule)?.label.toLowerCase()}.</p>
          </>
        ) : (
          <>
            <div className="cx-steps" aria-label="Steps">{labels.map((l, i) => <span key={l} className={`cx-step${i + 1 === step ? " on" : i + 1 < step ? " done" : ""}`}>{i + 1}. {l}</span>)}</div>

            {step === 1 && (
              <>
                {!kind.available && <p className="cx-banner">This kind of system needs a driver that is added per project, once there is a server to connect to. You can fill in the form to see how it works.</p>}
                {kind.available && !kind.verified && <p className="cx-banner">The driver is installed. It has not yet been tested against a live server in this build, so run the test in the next step.</p>}
                <div className="cx-form">
                  <label className="wide">Name<input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} /></label>
                  {fields.map((f) => (
                    <label key={f.key}>
                      {f.label}{f.required ? "" : " (optional)"}
                      {f.type === "select" ? (
                        <select value={vals[f.key]} onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })}>{f.options.map((o) => <option key={o} value={o}>{o}</option>)}</select>
                      ) : (
                        <input type={f.type === "password" ? "password" : f.type === "number" ? "number" : "text"} value={vals[f.key]} placeholder={f.placeholder || ""}
                               autoComplete="off" onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })} />
                      )}
                      {f.help && <small>{f.help}</small>}
                    </label>
                  ))}
                </div>
                {fields.length === 0 && <p className="cx-note">Nothing to enter. This source is built in.</p>}
                <p className="cx-note">Use an account that can only read. Passwords are stored encrypted and are never shown again.</p>
              </>
            )}

            {step === 2 && (
              <>
                <p className="cx-note">Check that the app can reach the system and read from it. Nothing is saved yet.</p>
                <div><button type="button" className="btn primary xs" disabled={!!busy} onClick={doTest}>{busy === "test" ? <Spinner size={12} /> : null} Test connection</button></div>
                {test && <div className={`cx-res ${test.ok ? "ok" : "bad"}`} role="status">{test.message}</div>}
                {test?.ok && rowsTable(test.columns, test.sample)}
              </>
            )}

            {step === 3 && (
              <>
                {isDb && (
                  <div className="cx-form">
                    <label>Read from
                      <select value={src.mode} onChange={(e) => { setSrc({ ...src, mode: e.target.value }); setPreview(null); }}>
                        <option value="table">A table</option><option value="query">A query (SELECT only)</option>
                      </select>
                    </label>
                    {src.mode === "table" ? (
                      <label>Table
                        <select value={src.table} onChange={(e) => { setSrc({ ...src, table: e.target.value, cursor_column: "" }); setPreview(null); }}>
                          <option value="">Choose a table…</option>{(test?.tables || []).map((t) => <option key={t} value={t}>{t}</option>)}
                        </select>
                      </label>
                    ) : (
                      <label className="wide">Query<textarea value={src.query} placeholder="SELECT * FROM scada_readings" onChange={(e) => { setSrc({ ...src, query: e.target.value }); setPreview(null); }} /></label>
                    )}
                    <div style={{ display: "flex", alignItems: "flex-end" }}>
                      <button type="button" className="btn ghost xs" disabled={!sourceChosen || !!busy} onClick={doPreview}>{busy === "preview" ? <Spinner size={12} /> : null} Preview rows</button>
                    </div>
                    {preview?.ok && (
                      <label>Only read new rows using
                        <select value={src.cursor_column} onChange={(e) => setSrc({ ...src, cursor_column: e.target.value })}>
                          <option value="">Read everything each time</option>{preview.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                        <small>A time or id column that only grows, so each pull reads just what is new.</small>
                      </label>
                    )}
                  </div>
                )}
                {isDb && preview?.ok && rowsTable(preview.columns, preview.sample)}
                {columns.length > 0 && (
                  <>
                    <div className="cx-form">
                      <label>Send the data to
                        <select value={target} onChange={(e) => setTarget(e.target.value)}>
                          <option value="">Choose…</option>{targets.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                        </select>
                        {targetFields && <small>{targetFields.purpose}</small>}
                      </label>
                    </div>
                    {target && map.fields.length > 0 && (
                      <>
                        <p className="cx-note">Each field of the destination is matched to a column of the source. Fix any that are not matched.</p>
                        <table className="cx-table">
                          <thead><tr><th>Destination field</th><th>Source column</th><th /></tr></thead>
                          <tbody>
                            {map.fields.map((f) => (
                              <tr key={f}>
                                <td>{f}</td>
                                <td><select value={map.columns[f] || ""} onChange={(e) => setCol(f, e.target.value)}><option value="">Not matched</option>{columns.map((c) => <option key={c} value={c}>{c}</option>)}</select></td>
                                <td><span className={`cx-pill ${map.columns[f] ? "ok" : "warn"}`}>{map.columns[f] ? "Matched" : "Needed"}</span></td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </>
                    )}
                  </>
                )}
                {columns.length === 0 && !isDb && <p className="cx-note">Run the test in step 2 first, so the app can see the columns.</p>}
              </>
            )}

            {step === 4 && (
              <div className="cx-form">
                <label>How often
                  <select value={schedule} onChange={(e) => setSchedule(Number(e.target.value))}>{schedules.map((s) => <option key={s.seconds} value={s.seconds}>{s.label}</option>)}</select>
                  <small>Rows that are already stored are skipped, so a pull can always be repeated safely.</small>
                </label>
                <div className="wide cx-banner">
                  <b>{name}</b> reads {isDb ? (src.mode === "table" ? `the table ${src.table}` : "your query") : kind.label} and sends it to <b>{targetFields?.label}</b>.
                  It pulls once right now, then {schedules.find((s) => s.seconds === schedule)?.label.toLowerCase()}.
                </div>
              </div>
            )}

            {err && <div className="cx-res bad" role="alert">{err}</div>}
            <div className="cx-nav">
              <button type="button" className="btn ghost xs" disabled={step === 1 || !!busy} onClick={() => { setErr(""); setStep(step - 1); }}>Back</button>
              {step < 4
                ? <button type="button" className="btn primary xs" disabled={!canNext || !!busy} onClick={() => { setErr(""); setStep(step + 1); }}>Next</button>
                : <button type="button" className="btn primary xs" disabled={!!busy} onClick={save}>{busy === "save" ? <Spinner size={12} /> : null} Save and pull now</button>}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function History({ conn, onClose }) {
  const q = useCached(`conn-runs-${conn.id}`, () => connApi.get(`/${conn.id}/runs`), 5_000);
  useEffect(() => {
    const h = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="cx-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="cx-modal" role="dialog" aria-modal="true" aria-label={`History of ${conn.name}`}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><h3>{conn.name}: recent pulls</h3><button type="button" className="btn ghost xs" onClick={onClose}>Close</button></div>
        {!q.data ? <p className="cx-note">Loading…</p> : (
          <table className="cx-table">
            <thead><tr><th>When</th><th>Result</th><th className="num">Read</th><th className="num">Stored</th></tr></thead>
            <tbody>{q.data.runs.map((r) => <tr key={r.id}><td>{formatDateTime(r.started_at)}<br /><small className="muted">{r.trigger}</small></td><td>{r.ok ? "" : "Failed. "}{r.message}</td><td className="num">{number(r.rows_read)}</td><td className="num">{number(r.rows_stored)}</td></tr>)}</tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function ConnectionCard({ c, onChanged, onHistory }) {
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState(null);
  const [confirm, setConfirm] = useState(false);
  const state = !c.enabled ? "paused" : c.status;
  async function go(label, fn) {
    setBusy(label);
    try { await fn(); await onChanged(); } catch (e) { setResult({ ok: false, message: e.message }); } finally { setBusy(""); }
  }
  return (
    <article className="card cx-conn" aria-label={c.name}>
      <div>
        <h4><i className={`cx-dot ${state}`} />{c.name}<span className="cx-pill">{c.enabled ? (c.status === "OK" ? "Connected" : c.status === "ERROR" ? "Problem" : "Not pulled yet") : "Paused"}</span></h4>
        <p className="cx-meta"><b>{c.kind_label}</b> to <b>{c.target_label}</b> · {c.schedule_label}{c.next_run_at && c.enabled ? ` · next pull ${timeAgo(c.next_run_at).includes("ago") ? "due" : "soon"}` : ""}</p>
        <p className="cx-meta">{c.last_run_at ? <>Last pull {timeAgo(c.last_run_at)}: {number(c.last_rows_read)} read, {number(c.last_rows_stored)} new</> : "Not pulled yet"}</p>
        {(result || c.last_message) && <p className={`cx-msg${(result ? !result.ok : c.status === "ERROR") ? " bad" : ""}`}>{result ? result.message : c.last_message}</p>}
      </div>
      <div className="cx-acts">
        <button type="button" className="btn primary xs" disabled={!!busy} onClick={() => go("pull", async () => setResult(await connApi.post(`/${c.id}/pull`)))}>{busy === "pull" ? <Spinner size={12} /> : null} Pull now</button>
        <button type="button" className="btn ghost xs" disabled={!!busy} onClick={() => go("toggle", () => connApi.patch(`/${c.id}`, { enabled: !c.enabled }))}>{c.enabled ? "Pause" : "Resume"}</button>
        <button type="button" className="btn ghost xs" onClick={() => onHistory(c)}>History</button>
        {confirm
          ? <button type="button" className="btn danger xs" disabled={!!busy} onClick={() => go("del", () => connApi.del(`/${c.id}`))}>Confirm remove</button>
          : <button type="button" className="btn ghost xs" onClick={() => { setConfirm(true); setTimeout(() => setConfirm(false), 4000); }}>Remove</button>}
      </div>
    </article>
  );
}

/** Connect your own data: choose a system, test it, say what to pull, and let it pull on a schedule. Read only. */
export default function Connectors({ onDataChanged }) {
  const cat = useCached("connector-catalog", () => connApi.get("/catalog"), 300_000);
  const list = useCached("connectors", () => connApi.get(""), 5_000, { pollMs: 8_000 });
  const st = useCached("dataStatus", api.dataStatus, 60_000, { pollMs: 30_000 });
  const [wizard, setWizard] = useState(null);
  const [history, setHistory] = useState(null);
  const [mock, setMock] = useState({ busy: "", msg: "" });

  const kinds = cat.data?.kinds || [];
  const conns = list.data?.connectors || [];
  const datasets = st.data?.datasets || [];
  const refresh = async () => { await list.reload(); st.reload(); onDataChanged?.(); };

  async function mockAction(kind) {
    setMock({ busy: kind, msg: "" });
    try {
      const r = kind === "seed" ? await twinApi.post("/mock/seed") : await twinApi.del("/mock");
      setMock({ busy: "", msg: kind === "seed" ? `Created ${r.people} people and ${r.closed_incidents + r.open_incidents} incidents.` : "Mock team and incidents removed." });
    } catch (e) { setMock({ busy: "", msg: e.message }); }
  }

  return (
    <div className="page cx-page">
      <header className="page-head">
        <div>
          <h2>Data connectors</h2>
          <p className="muted">Connect the systems you already have. The app reads from them directly and keeps its figures up to date. It only reads; it never writes to your systems.</p>
        </div>
      </header>

      <section className="card cx-how" aria-label="How connecting works">
        <p className="cx-h" style={{ marginBottom: 10 }}>How connecting works</p>
        <ol>{HOW.map(([t, d]) => <li key={t}><b>{t}</b><span>{d}</span></li>)}</ol>
        <p className="cx-safe">Read-only by design: SQL is limited to SELECT, web calls are GET only, passwords are stored encrypted, and every pull skips rows that are already stored.</p>
      </section>

      <section aria-label="Your connections">
        <p className="cx-h" style={{ marginBottom: 8 }}>Your connections</p>
        <div className="cx-list">
          {conns.length === 0 && (
            <div className="card cx-empty">
              <span>Nothing is connected yet. Try the built-in demo source to see it work in a minute, or connect one of your own systems below.</span>
              {kinds.find((k) => k.kind === "demo_gateway") && <button type="button" className="btn primary xs" onClick={() => setWizard(kinds.find((k) => k.kind === "demo_gateway"))}>Connect the demo gateway</button>}
            </div>
          )}
          {conns.map((c) => <ConnectionCard key={c.id} c={c} onChanged={refresh} onHistory={setHistory} />)}
        </div>
      </section>

      <section className="cx-cat" aria-label="Connect a system">
        <p className="cx-h">Connect a system</p>
        {(cat.data?.categories || []).map((g) => (
          <div key={g} className="cx-cat">
            <p className="muted small" style={{ margin: "6px 0 0", fontWeight: 650 }}>{g}</p>
            <div className="cx-cards">
              {kinds.filter((k) => k.category === g).map((k) => (
                <article key={k.kind} className="card cx-card">
                  <b><Icon name={k.icon} />{k.label}</b>
                  <p>{k.blurb}</p>
                  <span className={`cx-pill ${k.verified ? "ok" : k.available ? "" : "warn"}`}>{k.verified ? "Available now" : k.available ? "Driver installed" : "Added per project"}</span>
                  <button type="button" className="btn ghost xs" onClick={() => setWizard(k)}>Connect</button>
                </article>
              ))}
            </div>
          </div>
        ))}
        <p className="muted small">Not on the list? New connectors are added per project, for any system that exposes a database, an API or files.</p>
      </section>

      <details className="card cx-details">
        <summary>Stored data and file upload <small>{datasets.length ? `${datasets.length} datasets, ${number(datasets.reduce((n, d) => n + (d.rows || 0), 0))} rows` : ""}</small></summary>
        <div className="cx-body">
          <table className="cx-table">
            <thead><tr><th>Dataset</th><th className="num">Rows</th><th>Covers</th><th>Last upload</th></tr></thead>
            <tbody>{datasets.map((d) => <tr key={d.dataset}><td>{d.label}</td><td className="num">{number(d.rows)}</td><td>{d.first_ts ? `${formatDateTime(d.first_ts)} to ${formatDateTime(d.last_ts)}` : "Reference data"}</td><td>{d.last_upload ? timeAgo(d.last_upload.uploaded_at) : "-"}</td></tr>)}</tbody>
          </table>
          <DataPanel embedded onDataChanged={() => { st.reload(); onDataChanged?.(); }} />
        </div>
      </details>

      <details className="card cx-details">
        <summary>Mock data for the proof of concept <small>team roster and incident history</small></summary>
        <div className="cx-body">
          <p className="cx-note">The team roster and the incident history are generated. Re-create them before a demo so the timers and shifts look current.</p>
          <div className="cx-acts" style={{ justifyContent: "flex-start" }}>
            <button type="button" className="btn primary xs" disabled={!!mock.busy} onClick={() => mockAction("seed")}>{mock.busy === "seed" ? <Spinner size={12} /> : null} Re-create mock data (about 20 s)</button>
            <button type="button" className="btn ghost xs" disabled={!!mock.busy} onClick={() => { if (window.confirm("Remove the mock team and incident history?")) mockAction("clear"); }}>Remove mock data</button>
          </div>
          {mock.msg && <p className="cx-note" role="status">{mock.msg}</p>}
        </div>
      </details>

      {wizard && cat.data && <Wizard key={wizard.kind} kind={wizard} targets={cat.data.targets} schedules={cat.data.schedules} onClose={() => setWizard(null)} onSaved={refresh} />}
      {history && <History conn={history} onClose={() => setHistory(null)} />}
    </div>
  );
}
