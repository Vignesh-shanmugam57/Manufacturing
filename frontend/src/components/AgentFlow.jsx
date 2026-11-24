import { useEffect, useRef, useState } from "react";
import { api, twinApi } from "../api/client.js";
import { cached, invalidate } from "../lib/cache.js";
import { formatDateTime, number, toolLabel, utilityLabel } from "../lib/format.js";
import StatusPill from "./StatusPill.jsx";
import { IconBell, IconCheck, IconDatabase, IconGauge, IconPlay, IconScan, IconTool, Spinner } from "./icons.jsx";

// The six steps of the Utilities Management Agent (from the agent blueprint), each tied to what the code really does
// and to the tools the agent can call.
const STAGES = [
  {
    id: "collect", icon: <IconDatabase />, title: "Collect telemetry",
    blurb: "Utility meter and equipment readings",
    does: "Collects utility meter and equipment telemetry: flow, pressure, temperature and alarms, plus machine state and downtime events.",
    how: "Every row is validated, bad rows are skipped and reported, repeats are ignored, and the rest is stored in PostgreSQL in one transaction.",
    tools: ["get_data_overview"],
    input: "Database and file import today. SCADA/BMS, PLC and IoT feeds are the next connectors.",
    output: "Clean, de-duplicated readings and a data-quality report.",
  },
  {
    id: "map", icon: <IconGauge />, title: "Map tags to the plant",
    blurb: "System, zone, equipment, consumers",
    does: "Maps each reading to its utility system, plant, zone and equipment, and links machines and lines that consume the utility.",
    how: "The identifiers inside the telemetry define every series (plant x utility x zone). The agent can read the schema and query it read-only.",
    tools: ["get_schema", "run_sql"],
    input: "Identifiers in the telemetry. A plant layout / asset register would add critical consumers.",
    output: "A series for each plant, utility and zone that the next steps analyse.",
  },
  {
    id: "detect", icon: <IconScan />, title: "Detect abnormal usage",
    blurb: "Operating envelope and anomaly detection",
    does: "Finds abnormal consumption, unstable pressure or temperature, leakage indicators and alarm clusters.",
    how: "Each series' last days are compared with its own earlier history (Welch z-test plus a minimum change: flow 10 %, pressure 5 %, temperature 10 %). Alarm clusters use an exact Poisson tail. All numbers come from code, never from the LLM.",
    tools: ["detect_abnormal_usage", "get_consumption_trends"],
    input: "Readings per series. Site-engineered limits are not loaded, so the envelope is the series' own history plus the plant's alarms.",
    output: "Ranked findings with evidence, likely cause and a recommendation.",
  },
  {
    id: "assess", icon: <IconTool />, title: "Assess impact and source",
    blurb: "Downtime link and likely source",
    does: "Judges whether a finding threatens production, and where it probably comes from.",
    how: "Tests whether downtime starts more often within 2 hours after utility alarms, and whether utility demand follows machine activity (idle machines, night load, zones that use more than their peers).",
    tools: ["get_downtime_correlation", "get_efficiency_recommendations"],
    input: "Machine telemetry and downtime events.",
    output: "Downtime verdict per utility and ranked efficiency actions with an owner.",
  },
  {
    id: "alert", icon: <IconBell />, title: "Alert facilities / maintenance",
    blurb: "Advisory alerts with an owner",
    does: "Raises an advisory alert for each real finding and assigns it to facilities or maintenance.",
    how: "A monitoring scan turns findings into de-duplicated alerts, so the same problem is never raised twice while it is open.",
    tools: ["run_monitoring_scan", "raise_alert", "list_alerts"],
    input: "Findings from the previous steps.",
    output: "Open alerts with severity, details and a recommended inspection.",
  },
  {
    id: "verify", icon: <IconCheck />, title: "Track and verify",
    blurb: "Return to normal, confirmed by data",
    does: "Tracks inspection through acknowledged and resolved, then checks that the utility really returned to normal.",
    how: "People set Acknowledged and Resolved. VERIFIED is set only by a telemetry check (default 48 hours), never by hand.",
    tools: ["verify_return_to_normal"],
    input: "Alert history and fresh telemetry.",
    output: "Alerts closed with evidence that the problem is gone.",
  },
];

const STATE_LABEL = { ready: "Ready", running: "Running", done: "Done", failed: "Stopped", wait: "Queued" };
// Who can own an issue. The owner is saved on the issue, with the name of the person who assigned it.
const TEAMS = ["Maintenance team", "Facilities team", "Utilities engineer", "Instrument technician", "Safety officer", "Production team"];
const MIN_STEP_MS = 900;      // pacing only, so each step is visible even when the answer is instant
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const read = (key, fn, force = false) => cached(key, fn, { force });
const optional = (p) => p.catch((e) => (e?.status === 400 ? null : Promise.reject(e)));
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const isOpen = (a) => a.status === "OPEN" || a.status === "ACKNOWLEDGED";
const clock = (d) => d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

// --------------------------------------------------------------------------- read-only analysis
// Steps 1-4 read the stored data and change nothing. They run when the page opens, and each result keeps the data
// the step looked at, so the UI can show it.
const ANALYSIS = [
  async (force) => {                                                       // 1 collect
    const st = await read("dataStatus", () => api.dataStatus(), force);
    const sets = st.datasets || [];
    const rows = sets.reduce((s, d) => s + (d.rows || 0), 0);
    if (!rows) throw new Error("No utility data is loaded yet, so there is nothing to analyse.");
    const last = sets.map((d) => d.last_ts).filter(Boolean).sort().pop();
    return {
      line: `${number(rows)} rows · latest reading ${formatDateTime(last)}`,
      note: `${number(rows)} rows from ${plural(sets.filter((d) => d.rows > 0).length, "dataset")}; the latest reading is ${formatDateTime(last)}.`,
      data: { datasets: sets.map((d) => ({ label: d.label, rows: d.rows || 0, first: d.first_ts, last: d.last_ts })) },
    };
  },
  async (force) => {                                                       // 2 map
    const ov = await read("overview", () => api.overview(), force);
    const utilities = ov.utility_types || [], zones = ov.zones || [], equipment = ov.utility_equipment || [];
    return {
      line: `${utilities.length} utilities · ${zones.length} zones · ${equipment.length} equipment`,
      note: `${plural(utilities.length, "utility", "utilities")} across ${plural(zones.length, "zone")}, ${plural(equipment.length, "piece")} of utility equipment and ${plural(ov.machines ?? 0, "machine")}.`,
      data: { utilities, zones, equipment: equipment.length, machines: ov.machines ?? 0, quality: ov.data_quality || [] },
    };
  },
  async (force) => {                                                       // 3 detect
    const ab = await read("anomalies-7", () => api.anomalies(7), force);
    return {
      line: `${number(ab.readings_in_window)} checked · ${ab.anomaly_count} abnormal`,
      note: ab.conclusion,
      data: {
        asOf: ab.as_of, window: ab.window, readings: ab.readings_in_window, tests: ab.tests_run, method: ab.method,
        found: ab.anomalies || [], count: ab.anomaly_count, alarms: ab.alarms_in_window,
      },
    };
  },
  async (force) => {                                                       // 4 assess
    const [corr, eff] = await Promise.all([
      optional(read("downtime-7", () => api.downtimeCorrelation(), force)),
      optional(read("efficiency", () => api.efficiency(), force)),
    ]);
    const byType = corr?.by_utility_type || [];
    const links = byType.filter((x) => x.verdict === "possible link");
    const recs = eff?.recommendations || [];
    return {
      line: `${plural(links.length, "downtime link")} · ${plural(recs.length, "suggestion")}`,
      note: [corr?.conclusion, eff?.conclusion].filter(Boolean).join(" ") || "No downtime or machine data to assess.",
      data: { byType, links, recs },
    };
  },
];

// Steps 5 and 6 show the live issues, the same ones as the Issues page. Nothing in this report writes anything.
const asAlert = (i) => ({ id: i.id, title: i.title, severity: i.severity, status: i.status, assigned_to: i.who?.name || "", source: "live" });
const VIEWS = [
  async () => {                                                            // 5 alert: open issues now
    const r = await twinApi.get("/issues?status=open");
    const open = (r.issues || []).map(asAlert);
    return {
      line: plural(open.length, "open issue"),
      note: "The live issues, as on the Issues page. The agent raises each one and hands it to the person on shift; assign and act on them there.",
      data: { open },
    };
  },
  async () => {                                                            // 6 verify: closed by the readings
    const [o, c] = await Promise.all([twinApi.get("/issues?status=open"), twinApi.get("/issues?status=closed&limit=40")]);
    const open = (o.issues || []).map(asAlert);
    const waiting = open.filter((a) => a.status === "CORRECTIVE_ACTION");
    const verified = (c.issues || []).map(asAlert);
    return {
      line: `${verified.length} closed recently · ${waiting.length} waiting for proof`,
      note: "An issue closes only when fresh readings stay inside their limits. Nobody can mark it verified by hand.",
      data: { waiting, verified, open },
    };
  },
];
const ACTIONS = [() => VIEWS[0](), () => VIEWS[1]()];                      // Run analysis only reads

// Step i of a run: analysis for 1-4, the writing actions for 5 and 6.
const runStep = (i) => (i < ANALYSIS.length ? ANALYSIS[i](true) : ACTIONS[i - ANALYSIS.length]());

function buildReport(res, seconds) {
  const [collect, map, detect, assess, alert, verify] = res;
  const found = detect.data.found;
  const links = assess.data.links;
  const open = verify.data.open.length;
  const bits = [
    found.length && plural(found.length, "abnormal pattern"),
    links.length && plural(links.length, "possible downtime link"),
    open && plural(open, "open alert"),
  ].filter(Boolean);
  // the live issues from this run: alerts the scan raised, plus the open ones, each once
  const seen = new Set();
  const issues = [...(alert.data.created || []), ...(verify.data.open || [])]
    .filter((a) => a.id && !seen.has(a.id) && seen.add(a.id))
    .slice(0, 10);
  return {
    ranAt: clock(new Date()),
    asOf: formatDateTime(detect.data.asOf),
    seconds,
    attention: bits.length > 0,
    headline: bits.length ? `Needs attention: ${bits.join(", ")}` : `All ${map.data.utilities.length} utilities are behaving normally`,
    steps: res.map((r, i) => ({ title: STAGES[i].title, line: r.line, note: r.note })),
    found,
    recs: assess.data.recs.slice(0, 5),
    raised: 0,
    issues,
  };
}

function Report({ r }) {
  return (
    <section className="card report" id="agent-report" aria-label="Agent report">
      <header className="report-head">
        <div>
          <p className="eyebrow">Agent report</p>
          <h3>{r.headline}</h3>
          <p className="small muted">Run at {r.ranAt} · data as of {r.asOf} · took {r.seconds} s</p>
        </div>
        <StatusPill value={r.attention ? "WARNING" : "NORMAL"} label={r.attention ? "Needs attention" : "All normal"} />
      </header>

      <ol className="report-steps">
        {r.steps.map((s, i) => (
          <li key={s.title}>
            <span className="report-no" aria-hidden="true"><IconCheck width={13} height={13} /></span>
            <div>
              <strong>{i + 1}. {s.title}</strong>
              <span className="report-line">{s.line}</span>
              {s.note && <span className="small muted">{s.note}</span>}
            </div>
          </li>
        ))}
      </ol>

      <div>
        <h4>Open issues</h4>
        {r.issues.length === 0 ? (
          <p className="small muted">No open issues. Everything is within its limits.</p>
        ) : (
          <ul className="res-list issue-list">
            {r.issues.map((x) => (
              <li key={x.id} className="issue-row">
                <StatusPill value={x.severity} />
                <div><strong>{x.title}</strong><span className="small muted">{String(x.status || "").replace(/_/g, " ").toLowerCase()} · owner: {x.assigned_to || "nobody yet"}</span></div>
              </li>
            ))}
          </ul>
        )}
        <p className="small muted">Assign and act on them on the Issues page.</p>
      </div>

      {r.found.length > 0 && (
        <div>
          <h4>Abnormal patterns</h4>
          <ul className="rec-list">
            {r.found.slice(0, 5).map((f, i) => (
              <li key={i}>
                <StatusPill value={f.severity} />
                <div><strong>{f.description}</strong><span className="small muted">{f.recommendation}</span></div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <h4>Recommended actions</h4>
        {r.recs.length === 0 ? (
          <p className="small muted">Nothing to do right now.</p>
        ) : (
          <ul className="rec-list">
            {r.recs.map((x, i) => (
              <li key={i}>
                <StatusPill value={x.priority} />
                <div>
                  <strong>{x.action}</strong>
                  <span className="small muted">Owner: {x.owner}{x.utility_type ? ` · ${utilityLabel(x.utility_type)}` : ""}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <p className="small muted report-foot">
        Flow is a relative load index because the units in the data differ, so no volumes or costs are calculated.
        The agent is advisory only and never operates equipment.
      </p>
    </section>
  );
}

// --------------------------------------------------------------------------- the data each step read
function Facts({ items }) {
  return (
    <dl className="res-facts">
      {items.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
    </dl>
  );
}

function AlertList({ alerts }) {
  if (!alerts.length) return <p className="small muted">None.</p>;
  return (
    <ul className="res-list">
      {alerts.slice(0, 8).map((a) => (
        <li key={a.id}>
          <StatusPill value={a.severity} />
          <div>
            <strong>{a.title}</strong>
            <span className="small muted">
              {(a.status || "").replace("_", " ").toLowerCase()}{a.assigned_to ? ` · ${a.assigned_to}` : ""}{a.source === "sample" ? " · sample" : ""}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

function StepResult({ index, r, analysing, running }) {
  if (!r) return <p className="small muted">{running ? "Working on this step now…" : analysing ? "Reading the stored data…" : "Nothing read yet."}</p>;
  if (r.error) return <p className="form-error">{r.error}</p>;
  const d = r.data;

  if (index === 0) return (
    <table className="res-table">
      <thead><tr><th>Dataset</th><th className="num">Rows</th><th>From</th><th>To</th></tr></thead>
      <tbody>
        {d.datasets.map((x) => (
          <tr key={x.label}><td>{x.label}</td><td className="num">{number(x.rows)}</td><td>{formatDateTime(x.first)}</td><td>{formatDateTime(x.last)}</td></tr>
        ))}
      </tbody>
    </table>
  );

  if (index === 1) return (
    <div className="res-stack">
      <div className="res-chips" aria-label="Utilities">
        {d.utilities.map((u) => <span key={u} className="tool-chip">{utilityLabel(u)}</span>)}
      </div>
      <Facts items={[["Zones", d.zones.join(", ") || "-"], ["Utility equipment", number(d.equipment)], ["Machines", number(d.machines)]]} />
      {d.quality.length > 0 && (
        <div>
          <h4>Data quality the analysis allows for</h4>
          <ul className="res-list">{d.quality.map((q, i) => <li key={i} className="small">{q}</li>)}</ul>
        </div>
      )}
    </div>
  );

  if (index === 2) {
    const alarms = d.alarms?.by_utility_type || {};
    return (
      <div className="res-stack">
        <Facts items={[
          ["Window", d.window ? `${formatDateTime(d.window.from)} to ${formatDateTime(d.window.to)}` : "-"],
          ["Readings checked", number(d.readings)],
          ["Statistical tests", number(d.tests)],
          ["Abnormal patterns", number(d.count)],
        ]} />
        <p className="small muted">{d.method}</p>
        <div>
          <h4>Alarms in the window</h4>
          {Object.keys(alarms).length === 0 ? <p className="small muted">No alarms in this window.</p> : (
            <div className="res-chips">
              {Object.entries(alarms).map(([u, n]) => <span key={u} className="tool-chip">{utilityLabel(u)}: <b>{number(n)}</b></span>)}
            </div>
          )}
        </div>
        <div>
          <h4>Abnormal patterns</h4>
          {d.found.length === 0 ? <p className="small">None. Every series is inside its own normal range.</p> : (
            <ul className="res-list">
              {d.found.slice(0, 8).map((f, i) => {
                const evidence = Object.entries(f.evidence || {}).filter(([, v]) => v !== null && typeof v !== "object");
                return (
                  <li key={i}>
                    <StatusPill value={f.severity} />
                    <div>
                      <strong>{f.description}</strong>
                      {f.likely_cause && <span className="small muted">{f.likely_cause}</span>}
                      {evidence.length > 0 && <span className="small muted">{evidence.slice(0, 5).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ")}</span>}
                      <span className="small">{f.recommendation}</span>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    );
  }

  if (index === 3) return (
    <div className="res-stack">
      <div>
        <h4>Downtime link by utility</h4>
        {d.byType.length === 0 ? <p className="small muted">No downtime or machine data to compare.</p> : (
          <table className="res-table">
            <thead><tr><th>Utility</th><th>Verdict</th><th className="num">Lift</th><th className="num">Z score</th></tr></thead>
            <tbody>
              {d.byType.map((x) => (
                <tr key={x.utility_type}>
                  <td>{utilityLabel(x.utility_type)}</td>
                  <td><span className={`res-badge ${x.verdict === "possible link" ? "warn" : "ok"}`}>{x.verdict}</span></td>
                  <td className="num">{x.lift ?? "-"}</td>
                  <td className="num">{x.z_score ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div>
        <h4>Efficiency suggestions</h4>
        {d.recs.length === 0 ? <p className="small muted">Nothing to suggest from the data.</p> : (
          <ul className="res-list">
            {d.recs.slice(0, 6).map((x, i) => (
              <li key={i}>
                <StatusPill value={x.priority} />
                <div><strong>{x.action}</strong><span className="small muted">Owner: {x.owner}</span></div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );

  if (index === 4) return (
    <div className="res-stack">
      {d.created ? (
        <>
          <p className="small">
            {d.created.length ? `${plural(d.created.length, "new alert")} raised by this run.` : "No new alert was needed."}
            {d.existing ? ` ${plural(d.existing, "finding")} already open.` : ""}
          </p>
          <AlertList alerts={d.created} />
        </>
      ) : (
        <>
          <p className="small muted">
            The live issues now, as on the Issues page.
          </p>
          <AlertList alerts={d.open} />
        </>
      )}
    </div>
  );

  // step 6
  if (d.waiting) return (
    <div className="res-stack">
      <Facts items={[["Verified", number(d.verified.length)], ["Waiting for a check", number(d.waiting.length)]]} />
      <AlertList alerts={d.waiting} />
    </div>
  );
  return (
    <div className="res-stack">
      {d.checks.length === 0 ? <p className="small muted">No resolved alert was waiting for a check.</p> : (
        <ul className="res-list">
          {d.checks.map((c) => (
            <li key={c.id}>
              <span className={`res-badge ${c.normal == null ? "" : c.normal ? "ok" : "bad"}`}>
                {c.normal == null ? "Not checked" : c.normal ? "Back to normal" : "Not back to normal"}
              </span>
              <div><strong>{c.title}</strong><span className="small muted">{c.message}</span></div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- the page
export default function AgentFlow({ onAlertsChanged }) {
  const [sel, setSel] = useState(0);
  const [run, setRun] = useState({ status: "idle", step: -1, lines: [], error: "" });
  const [report, setReport] = useState(null);
  const [res, setRes] = useState({});             // latest result per step: the read-only analysis, or the last run
  const [analysing, setAnalysing] = useState(true);
  const [analysedAt, setAnalysedAt] = useState(null);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    if (report) document.getElementById("agent-report")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [report]);

  // Opening the page analyses the stored data. This only reads: nothing is written until Run agent is pressed.
  useEffect(() => {
    let current = true;
    Promise.allSettled([...ANALYSIS, ...VIEWS].map((fn) => fn(false))).then((out) => {
      if (!current) return;
      setRes((prev) => {
        const next = { ...prev };
        out.forEach((o, i) => {
          if (next[i] === undefined) next[i] = o.status === "fulfilled" ? o.value : { error: o.reason?.message || "This step could not be read." };
        });
        return next;
      });
      setAnalysing(false);
      setAnalysedAt(new Date());
    });
    return () => { current = false; };
  }, []);

  async function runAgent() {
    if (run.status === "running") return;
    const started = Date.now();
    setReport(null);
    setRun({ status: "running", step: 0, lines: [], error: "" });
    const results = [];
    try {
      for (let i = 0; i < STAGES.length; i += 1) {
        if (!alive.current) return;
        setSel(i);
        setRun((r) => ({ ...r, step: i }));
        const t0 = Date.now();
        const out = await runStep(i);
        const rest = MIN_STEP_MS - (Date.now() - t0);
        if (rest > 0) await sleep(rest);
        if (!alive.current) return;
        results.push(out);
        setRes((prev) => ({ ...prev, [i]: out }));
        setRun((r) => ({ ...r, lines: [...r.lines, out.line] }));
      }
      invalidate();               // the scan and the checks may have changed alerts
      onAlertsChanged?.();
      setReport(buildReport(results, Math.round((Date.now() - started) / 100) / 10));
      setRun((r) => ({ ...r, status: "done", step: -1 }));
      setAnalysedAt(new Date());
    } catch (e) {
      if (alive.current) setRun((r) => ({ ...r, status: "error", error: e.message }));
    }
  }

  const running = run.status === "running";
  const doneCount = run.status === "done" ? STAGES.length : run.lines.length;
  // state of each card during and after a run
  const cardState = (i) => {
    if (run.status === "idle") return "";
    if (i < run.lines.length) return "done";
    if (run.status === "running" && i === run.step) return "running";
    if (run.status === "error" && i === run.lines.length) return "failed";
    return "wait";
  };
  const lineFor = (i) => (res[i]?.error ? "Unavailable" : res[i]?.line ?? (analysing ? "Reading…" : "…"));
  const stage = STAGES[sel];

  return (
    <div className="page flow-page">
      <header className="page-head">
        <div>
          <h2>Agent flow</h2>
          <p className="muted">
            Six steps from plant data to a verified action. The first four analyse the stored history; the last two show the
            live issues. Opening this page reads the data and writes nothing. Run analysis walks through all six steps and
            writes a short report. It never raises alerts or changes anything.
          </p>
          <p className="small muted">
            {analysing ? "Reading the stored data…" : analysedAt ? `Read at ${clock(analysedAt)} from the database. Read-only.` : ""}
          </p>
        </div>
        <div className="page-actions">
          <button className="btn primary" onClick={runAgent} disabled={running}>
            {running ? <Spinner /> : <IconPlay width={16} height={16} />}
            {running ? `Running… step ${run.step + 1} of ${STAGES.length}` : "Run analysis"}
          </button>
        </div>
      </header>

      {run.status === "error" && (
        <div className="chat-error" role="alert">Stopped at step {run.lines.length + 1}: {run.error}</div>
      )}

      <ol className="flow" aria-label="Agent steps">
        {STAGES.map((s, i) => {
          const state = cardState(i);
          const label = state || "ready";
          const shown = res[i];
          return (
            <li key={s.id} className={`stage${i === sel ? " on" : ""}${state ? ` ${state}` : ""}`}>
              <button onClick={() => setSel(i)} aria-current={i === sel ? "step" : undefined}>
                <span className="stage-no">{i + 1}</span>
                <span className={`stage-state ${label}`}>{STATE_LABEL[label]}</span>
                <span className="stage-icon">{state === "done" ? <IconCheck /> : s.icon}</span>
                <span className="stage-title">{s.title}</span>
                <span className="stage-blurb">{s.blurb}</span>
                <span className={`stage-live${state === "done" && !shown?.error ? " ok" : state === "failed" || shown?.error ? " bad" : ""}`}>
                  {state === "running" ? <><Spinner size={12} /> Working…</>
                    : state === "failed" ? "Stopped"
                    : state === "wait" ? "Waiting"
                    : lineFor(i)}
                  {!state && shown?.line && shown?.data?.sampled && <span className="sample-tag">incl. sample</span>}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      <div className="flow-progress" role="progressbar" aria-label="Steps finished" aria-valuemin={0}
           aria-valuemax={STAGES.length} aria-valuenow={doneCount}>
        <span style={{ width: `${(doneCount / STAGES.length) * 100}%` }} />
      </div>

      {report && <Report r={report} />}

      <section className="card stage-detail" aria-live="polite" aria-label={`Step ${sel + 1}: ${stage.title}`}>
        <header>
          <span className="stage-detail-no">Step {sel + 1} of {STAGES.length}</span>
          <h3>{stage.title}</h3>
        </header>
        <div className="step-result">
          <h4>What the agent read and found</h4>
          <StepResult index={sel} r={res[sel]} analysing={analysing} running={running && run.step === sel} />
        </div>
        <div className="detail-grid">
          <div><h4>What the agent does</h4><p>{stage.does}</p></div>
          <div><h4>How it works</h4><p>{stage.how}</p></div>
          <div><h4>Needs</h4><p>{stage.input}</p></div>
          <div><h4>Produces</h4><p>{stage.output}</p></div>
        </div>
        <div className="tool-chips">
          <h4>Tools it calls</h4>
          {stage.tools.map((t) => <span key={t} className="tool-chip" title={t}>{toolLabel(t)} <code>{t}</code></span>)}
        </div>
      </section>
    </div>
  );
}
