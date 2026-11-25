import { Fragment, useEffect, useState } from "react";
import { api } from "../../api/client.js";
import { useCached } from "../../hooks/useCached.js";
import { timeAgo } from "../../lib/format.js";
import { useTwin, useTwinResource } from "../../lib/twin.js";
import "../../styles/architecture.css";

const PURPOSE = "Keep plant utilities reliable and efficient. Monitor compressed air, steam, chilled water, cooling, HVAC, water and gas, and detect abnormal use or conditions that threaten production or raise cost.";

const STEP_MS = 3000;       // how long each step stays on screen before the flow moves on by itself
const WHO = { system: "System", agent: "AI agent", person: "A person" };
const AGENT_TOOLS = 14;     // the chat agent's tools (backend/app/agent/tools.py)
const num = (v) => (v == null ? "…" : Number(v).toLocaleString());
const mins = (sec) => (sec == null ? "…" : sec < 3600 ? `${Math.round(sec / 60)} min` : `${(sec / 3600).toFixed(1)} h`);

/** How it works: one flow that plays through by itself. Click a step, or use Back and Next, to jump. */
export default function Architecture({ onGo }) {
  const st = useCached("dataStatus", api.dataStatus, 60_000, { pollMs: 30_000 });
  const sum = useTwinResource("/issues/summary", 30000).data;
  const openList = useTwinResource("/issues?status=open", 30000).data?.issues;
  const ov = useTwinResource("/overview", 30000).data;
  const equipment = useTwin((x) => x.catalog?.equipment);

  const datasets = st.data?.datasets || [];
  const loaded = datasets.filter((d) => d.rows > 0);
  const totalRows = st.data ? datasets.reduce((a, x) => a + (x.rows || 0), 0) : null;
  const uploads = datasets.map((d) => d.last_upload?.uploaded_at).filter(Boolean).sort();
  const lastUpload = uploads.length ? uploads[uploads.length - 1] : null;

  const machines = equipment?.length ?? null;
  const sensors = equipment ? equipment.reduce((a, e) => a + e.sensors.length, 0) : null;
  const open = sum?.open ?? null;
  const holders = sum ? Object.keys(sum.open_by_person || {}).length : null;
  const unack = sum?.unacknowledged ?? null;
  const waiting = openList ? openList.filter((i) => i.status === "CORRECTIVE_ACTION").length : null;
  const utilities = ov?.utilities || null;
  const normal = utilities ? utilities.filter((u) => u.level === 0).length : null;

  const steps = [
    { key: "sources", lane: 1, kind: "system", title: "Sources",
      metric: "Simulator + connectors",
      what: "In this proof of concept the live readings come from a built-in simulator. Your own databases, REST APIs and CSV files connect on the Data connectors page, read only, and feed the stored history. Live SCADA, BMS and PLC feeds are not connected yet.",
      stats: [[num(machines), "pieces of equipment"], [num(sensors), "sensor readings"], ["Not connected", "SCADA, BMS, PLC"]],
      go: "connectors", cta: "Open Data connectors" },
    { key: "neon", lane: 1, kind: "system", title: "Database",
      metric: totalRows == null ? "Reading…" : `${num(totalRows)} rows`,
      what: "PostgreSQL on Neon holds the stored history, the issues with their timelines and the team roster. Each uploaded row is checked, bad rows are skipped and reported, and a row that is already stored is skipped.",
      stats: [[num(totalRows), "history rows stored"], [st.data ? `${loaded.length}/${datasets.length}` : "…", "datasets loaded"], [lastUpload ? timeAgo(lastUpload) : "None yet", "last upload"]],
      go: "connectors", cta: "Open Data connectors" },
    { key: "backend", lane: 1, kind: "system", title: "Backend",
      metric: "Monitoring engine",
      what: "A FastAPI backend runs the monitoring engine. It reads the equipment every second, keeps one set of facts about every issue, and pushes each change to the screens, so the list, the map and the overview agree.",
      stats: [["1 s", "between checks"], ["One", "source for every screen"], ["Live", "changes pushed to screens"]],
      go: "map", cta: "Open Plant map" },
    { key: "agent", lane: 1, kind: "agent", title: "AI chat",
      metric: `${AGENT_TOOLS} tools · advisory`,
      what: "Ask the agent is a LangChain agent on Domo. It picks a tool, reads the same issues, roster and history as the pages, and answers in plain words. It cannot raise or change an issue, and has no tool that operates equipment.",
      stats: [[String(AGENT_TOOLS), "tools that read"], ["0", "tools that change issues"], ["0", "tools that act on equipment"]],
      go: "flow", cta: "Open Agent activity" },
    { key: "detect", lane: 2, kind: "agent", title: "Detect",
      metric: sensors == null ? "Reading…" : `${sensors} readings`,
      what: "Every reading is compared with its engineering limits and seven known fault patterns. It has to stay abnormal for several checks before it counts. These are fixed rules, not the language model.",
      stats: [[num(sensors), "readings watched"], ["7", "fault patterns, plus limits"], ["1 s", "between checks"]],
      go: "map", cta: "Open Plant map" },
    { key: "alert", lane: 2, kind: "agent", title: "Alert",
      metric: open == null ? "Reading…" : `${open} open`,
      what: "Each problem is raised once as an issue, with the reading against what is expected, the zone and equipment, a probable cause worked out from the readings, and what to do.",
      stats: [[num(open), "open issues"], [num(sum?.needs_attention), "need attention"], ["Once", "no duplicate issues"]],
      go: "issues", cta: "Open Issues" },
    { key: "assign", lane: 2, kind: "agent", title: "Assign",
      metric: holders == null ? "Reading…" : `${holders} ${holders === 1 ? "person" : "people"}`,
      what: "The agent hands the issue to a person on the roster: the right team, on shift now, covering that zone. A critical issue not acknowledged in 2 minutes, or a major one in 5, is escalated. People can reassign it.",
      stats: [[num(holders), "people with open issues"], ["2 min", "critical escalates after"], ["5 min", "major escalates after"]],
      go: "issues", cta: "Open Issues" },
    { key: "resolve", lane: 2, kind: "person", title: "Resolve",
      metric: unack == null ? "Reading…" : `${unack} waiting`,
      what: "The owner acknowledges the issue on Issues or the plant map, goes to the equipment, does the fix and records what was done. The walking figure on the map shows the stage of the response; it does not track anyone's location.",
      stats: [[num(unack), "not yet acknowledged"], [mins(sum?.avg_time_to_acknowledge_s), "average to acknowledge"], [mins(sum?.avg_time_to_resolve_s), "average to close"]],
      go: "issues", cta: "Open Issues" },
    { key: "verify", lane: 2, kind: "agent", title: "Verify",
      metric: waiting == null ? "Reading…" : `${waiting} awaiting proof`,
      what: "After the fix is recorded, the issue closes only if fresh readings have stayed inside their limits. If they have not, the check is refused and says why.",
      stats: [[num(waiting), "awaiting proof"], [num(sum?.closed_30d), "closed in 30 days"], ["20 s", "of normal readings checked"]],
      go: "issues", cta: "Open Issues" },
    { key: "monitor", lane: 2, kind: "agent", title: "Monitor",
      metric: normal == null ? "Reading…" : `${normal} of ${utilities.length} normal`,
      what: "Plant overview shows each utility's status, usage against its normal range (modelled demo figures) and what needs attention. Any new abnormal reading sends the flow back to Detect.",
      stats: [[normal == null ? "…" : `${normal}/${utilities.length}`, "utilities normal now"], [num(open), "open issues"], ["Live", "updates on every change"]],
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
                <div className="arch-src-off" title="Live plant feeds are not connected in this proof of concept">SCADA, BMS, PLC<br />not connected</div>
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
