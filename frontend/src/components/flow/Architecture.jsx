import { Fragment, useEffect, useState } from "react";
import { api } from "../../api/client.js";
import { useCached } from "../../hooks/useCached.js";
import { timeAgo } from "../../lib/format.js";
import "../../styles/architecture.css";

const PURPOSE = "Keep plant utilities reliable and efficient. Monitor compressed air, steam, chilled water, cooling, HVAC, water and gas, and detect abnormal use or conditions that threaten production or raise cost.";

const STEP_MS = 3000;       // how long each step stays on screen before the flow moves on by itself
const WHO = { system: "System", agent: "AI agent", person: "A person" };
const num = (v) => (v == null ? "…" : Number(v).toLocaleString());
const pct = (v) => (v == null ? "…" : `${v.toFixed(1)}%`);

/** Architecture: one flow that plays through by itself. Click a step, or use Back and Next, to jump. */
export default function Architecture({ onGo }) {
  const st = useCached("dataStatus", api.dataStatus, 60_000, { pollMs: 30_000 });
  const pl = useCached("plant-summary-30", () => api.plantSummary(30), 60_000, { pollMs: 60_000 });

  const datasets = st.data?.datasets || [];
  const loaded = datasets.filter((d) => d.rows > 0);
  const totalRows = st.data ? datasets.reduce((a, x) => a + (x.rows || 0), 0) : null;
  const uploads = datasets.map((d) => d.last_upload?.uploaded_at).filter(Boolean).sort();
  const lastUpload = uploads.length ? uploads[uploads.length - 1] : null;

  const d = pl.data;
  const utils = d?.utilities?.by_utility || [];
  const readings = d ? utils.reduce((a, u) => a + (u.readings || 0), 0) : null;
  const alarms = d ? utils.reduce((a, u) => a + Object.values(u.alarms || {}).reduce((x, y) => x + y, 0), 0) : null;
  const utilitiesWithAlarms = d ? utils.filter((u) => Object.keys(u.alarms || {}).length).length : null;
  const avail = readings ? utils.reduce((a, u) => a + u.availability_pct * u.readings, 0) / readings : null;
  const pressureVar = utils.length ? utils.reduce((a, u) => a + u.pressure_variation_pct, 0) / utils.length : null;
  const wf = d?.workflow;
  const bs = wf?.by_status || {};
  const open = d ? (bs.OPEN || 0) + (bs.ACKNOWLEDGED || 0) : null;
  const resolved = d ? bs.RESOLVED || 0 : null;
  const verified = d ? bs.VERIFIED || 0 : null;
  const owners = Object.entries(wf?.open_by_owner || {}).map(([o, n]) => `${o}: ${n}`).join(" · ");
  const hrs = (v) => (v == null ? "…" : `${v.toFixed(1)} h`);

  const steps = [
    { key: "sources", lane: 1, kind: "system", title: "Sources",
      metric: st.data ? `${loaded.length} of ${datasets.length} datasets` : "Reading…",
      what: "CSV files are uploaded on the Data connectors page. The file type is recognised from its header, so file names do not matter. Live SCADA, BMS and PLC feeds are not connected yet.",
      stats: [[st.data ? `${loaded.length}/${datasets.length}` : "…", "datasets loaded"], ["Not connected", "SCADA, BMS, PLC"]],
      go: "connectors", cta: "Open Data connectors" },
    { key: "neon", lane: 1, kind: "system", title: "Neon DB",
      metric: totalRows == null ? "Reading…" : `${num(totalRows)} rows`,
      what: "Each row is checked, bad rows are skipped and reported, and an upload is saved as one transaction. Uploading the same file twice is safe, because rows that are already stored are skipped.",
      stats: [[num(totalRows), "rows stored"], [lastUpload ? timeAgo(lastUpload) : "None yet", "last upload"], ["PostgreSQL", "hosted on Neon"]],
      go: "connectors", cta: "Upload data" },
    { key: "backend", lane: 1, kind: "system", title: "Backend",
      metric: "FastAPI",
      what: "The backend reads the stored rows and computes every figure with code: statistical tests on usage and alarm clusters. The language model never does the maths, so numbers are repeatable.",
      stats: [["By code", "every number computed"], [num(readings), "utility readings in view"], ["In memory", "rows cached for speed"]],
      go: "monitor", cta: "Open Plant overview" },
    { key: "agent", lane: 1, kind: "agent", title: "AI agent",
      metric: "12 tools · advisory",
      what: "A LangChain agent on Domo picks a tool, reads its result and explains it in plain words. It has no tool that changes setpoints or operates equipment, and it refuses such requests.",
      stats: [["12", "tools it can use"], ["5", "tool calls max per question"], ["0", "tools that act on equipment"]],
      go: "flow", cta: "Open Agent activity" },
    { key: "detect", lane: 2, kind: "agent", title: "Detect",
      metric: d ? `${num(alarms)} alarms` : "Reading…",
      what: "Each utility is compared with its own earlier history, and alarm clusters are tested too. When nothing is abnormal, the agent says so instead of guessing.",
      stats: [[num(readings), "readings checked"], [num(alarms), "alarms in the period"], [num(utilitiesWithAlarms), "utilities with alarms"]],
      go: "flow", cta: "Open Agent activity" },
    { key: "alert", lane: 2, kind: "agent", title: "Alert",
      metric: open == null ? "Reading…" : `${open} open`,
      what: "The monitoring scan raises an advisory alert for each real finding. The same issue is raised only once, and each alert carries a recommended action for the people who own it.",
      stats: [[num(open), "open alerts"], ["Advisory", "recommends, never acts"], ["Once", "no duplicate alerts"]],
      go: "issues", cta: "Open Issues" },
    { key: "assign", lane: 2, kind: "person", title: "Assign",
      metric: owners || "No open issues",
      what: "Every open issue has one owner. A person assigns or changes the owner on the Issues page.",
      stats: [[num(open), "open issues"], [owners || "None to assign", "owners right now"]],
      go: "issues", cta: "Open Issues" },
    { key: "resolve", lane: 2, kind: "person", title: "Resolve",
      metric: resolved == null ? "Reading…" : `${resolved} resolved`,
      what: "The owner acknowledges the issue, carries out the corrective action and writes a note. The plant's certified operators do the actual fix.",
      stats: [[num(resolved), "resolved, awaiting proof"], [hrs(wf?.avg_hours_to_acknowledge), "average to acknowledge"], [hrs(wf?.avg_hours_to_resolve), "average to resolve"]],
      go: "issues", cta: "Open Issues" },
    { key: "verify", lane: 2, kind: "agent", title: "Verify",
      metric: verified == null ? "Reading…" : `${verified} verified`,
      what: "An issue only becomes verified when the telemetry shows a return to normal. Nobody can mark it verified by hand.",
      stats: [[num(verified), "verified so far"], ["Telemetry", "is the only proof"]],
      go: "issues", cta: "Open Issues" },
    { key: "monitor", lane: 2, kind: "agent", title: "Monitor",
      metric: avail == null ? "Reading…" : `${pct(avail)} available`,
      what: "Six success measures refresh every minute. Any new abnormal reading sends the flow back to Detect, so the loop never stops.",
      stats: [[pct(avail), "utility availability"], [pct(pressureVar), "pressure variation"], ["Every minute", "refresh rate"]],
      go: "monitor", cta: "Open Plant overview" },
  ];

  const total = steps.length;
  const [step, setStep] = useState(0);
  // The flow moves on by itself. Choosing a step restarts the timer, then playing continues from there.
  useEffect(() => {
    const t = setTimeout(() => setStep((s) => (s + 1) % total), STEP_MS);
    return () => clearTimeout(t);
  }, [step, total]);

  const s = steps[step];
  const row = (items, offset, lead) => (
    <div className="arch-row" role="group">
      {lead}
      {items.map((x, i) => {
        const idx = offset + i;
        return (
          <Fragment key={x.key}>
            {i > 0 && <span className={`arch-link${step === idx ? " on" : ""}`} aria-hidden="true"><i className="arch-dot" /></span>}
            <button type="button" className="arch-node" data-kind={x.kind} aria-current={step === idx ? "step" : undefined}
                    aria-label={`Step ${idx + 1}: ${x.title}`} onClick={() => setStep(idx)}>
              <span className="arch-no">{idx + 1}</span>
              <span className="arch-title">{x.title}</span>
              <span className="arch-metric">{x.metric}</span>
            </button>
          </Fragment>
        );
      })}
    </div>
  );

  return (
    <div className="page flow-page-arch">
      <header className="page-head">
        <div>
          <h2>How it works</h2>
          <p className="muted">How the data moves, and what happens when the agent finds a problem.</p>
        </div>
      </header>
      <section className="card purpose" aria-label="Purpose">
        <p className="eyebrow">Purpose</p>
        <p>{PURPOSE}</p>
        <p className="small muted">The agent advises only. It never changes setpoints or operates valves or pumps; certified operators do that.</p>
      </section>

      <section className="card arch-flow" aria-label="How it works" style={{ "--arch-ms": `${STEP_MS}ms` }}>
        <div className="arch-diagram">
          <div>
            <p className="arch-lane-label">How the data moves</p>
            {row(steps.slice(0, 4), 0, (
              <>
                <div className="arch-src-off" title="Live feeds are not connected in this build">SCADA, BMS, PLC<br />not connected</div>
                <span className="arch-link dash" aria-hidden="true" />
              </>
            ))}
          </div>

          <div className={`arch-elbow${step === 4 ? " on" : ""}`} aria-hidden="true"><i /><span>When the agent finds a problem</span><i /></div>

          <div>
            <p className="arch-lane-label arch-only-narrow">What happens next</p>
            {row(steps.slice(4), 4)}
            <div className={`arch-return${step === 9 ? " on" : ""}`}>A new abnormal reading starts the loop again at Detect</div>
          </div>

          <div className="arch-legend" aria-hidden="true">
            <span><i data-kind="system" />System</span>
            <span><i data-kind="agent" />The agent does it</span>
            <span><i data-kind="person" />A person does it</span>
            <em>Plays by itself · click a step to jump</em>
          </div>

          <div className="arch-timer" aria-hidden="true">
            {steps.map((x, i) => (
              <button type="button" key={x.key} tabIndex={-1} className={`arch-seg${i < step ? " done" : ""}${i === step ? " cur" : ""}`} onClick={() => setStep(i)}>
                <i key={i === step ? `p${step}` : "x"} />
              </button>
            ))}
          </div>
        </div>

        <aside className="arch-detail" key={`d${step}`} aria-live="polite">
          <span className="arch-count">Step {step + 1} of {total}</span>
          <div className="arch-headline">
            <h3>{s.title}</h3>
            <span className="arch-badge" data-kind={s.kind}>{WHO[s.kind]}</span>
          </div>
          <p className="arch-what">{s.what}</p>
          <div className="arch-stats">
            {s.stats.map(([v, label]) => (
              <div className="arch-stat" key={label}><b className={String(v).length > 9 ? "long" : undefined}>{v}</b><span>{label}</span></div>
            ))}
          </div>
          <div className="arch-actions">
            <button type="button" className="btn ghost xs" onClick={() => setStep((step + total - 1) % total)}>Back</button>
            <button type="button" className="btn ghost xs" onClick={() => setStep((step + 1) % total)}>Next</button>
            {s.go && <button type="button" className="btn primary xs" onClick={() => onGo(s.go)}>{s.cta}</button>}
          </div>
        </aside>
      </section>
    </div>
  );
}
