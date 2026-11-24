import { api } from "../api/client.js";
import { formatDateTime, number, STATUS_ORDER, timeAgo, utilityLabel } from "../lib/format.js";
import { useCached } from "../hooks/useCached.js";
import PageSkeleton from "./Skeleton.jsx";
import Sparkline from "./Sparkline.jsx";
import StatusPill from "./StatusPill.jsx";
import { IconBell, IconBolt, IconChat, IconDatabase, IconGauge, IconScan, IconShield, IconTool } from "./icons.jsx";

const ASK = [
  "Give me a status overview of the plant utilities. What needs attention first?",
  "Is any utility using abnormal amounts compared with its normal pattern?",
  "Is utility usage linked to our downtime events?",
  "Where can we save energy? Give me simple efficiency recommendations.",
];

const RISK_RANK = { HIGH: 2, MEDIUM: 1, LOW: 0 };
const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null);

function fmtMinutes(m) {
  if (m == null) return "-";
  if (m < 1) return "< 1 min";
  if (m < 60) return `${Math.round(m)} min`;
  if (m < 1440) return `${(m / 60).toFixed(1)} h`;
  return `${(m / 1440).toFixed(1)} d`;
}

// Supply-risk rule (shown in the UI tooltip): ALARM -> HIGH; WATCH or a possible downtime link -> MEDIUM; else LOW.
function supplyRisk(hb) {
  const links = Object.fromEntries((hb.downtime_link?.by_utility_type || []).map((x) => [x.utility_type, x]));
  return hb.utilities.map((u) => {
    const link = links[u.utility_type];
    let level = "LOW";
    let reason = `No abnormal pattern against its own history. ${u.alarms_7d} alarm${u.alarms_7d === 1 ? "" : "s"} in 7 days.`;
    if (u.status === "ALARM") { level = "HIGH"; reason = u.reasons[0]; }
    else if (u.status !== "NORMAL") { level = "MEDIUM"; reason = u.reasons[0]; }
    else if (link?.verdict === "possible link") {
      level = "MEDIUM";
      reason = `Downtime starts ${link.lift}x more often within 2 hours after its alarms.`;
    }
    return { ...u, level, reason };
  }).sort((a, b) => RISK_RANK[b.level] - RISK_RANK[a.level]);
}

function Kpi({ label, value, unit, caption, tone = "neutral", icon, hint }) {
  return (
    <div className={`dkpi tone-${tone}`} title={hint}>
      <div className="dkpi-top"><span className="dkpi-icon">{icon}</span><span className="dkpi-label">{label}</span></div>
      <div className="dkpi-value">{value}{unit && <small>{unit}</small>}</div>
      <div className="dkpi-cap">{caption}</div>
    </div>
  );
}

const LIVE_MS = 15_000; // how often the dashboard quietly checks the database for newer data

function UtilityTile({ u, trend, onClick }) {
  const c = u.flow_change_pct;
  const dir = c == null ? "flat" : c > 0 ? "up" : c < 0 ? "down" : "flat";
  return (
    <button className={`utile status-${u.status.toLowerCase()}`} onClick={onClick}
            aria-label={`${utilityLabel(u.utility_type)} ${u.status}. Open the health board`}>
      <span className="utile-head"><span className="utile-name">{utilityLabel(u.utility_type)}</span><StatusPill value={u.status} /></span>
      <span className="utile-main">
        <span className="utile-value">{u.avg_flow_24h ?? "-"}</span>
        <span className={`utile-delta d-${dir}`} title="Change against the previous 7 days">
          {dir === "up" ? "▲" : dir === "down" ? "▼" : "–"} {c == null ? "-" : `${Math.abs(c)}%`}
        </span>
      </span>
      <span className="utile-cap">Load index, last 24 h</span>
      {trend && <Sparkline series={trend.series} />}
      <span className="utile-foot">{u.alarms_7d} alarms · {u.avg_pressure_bar_24h ?? "-"} bar · {u.avg_temperature_c_24h ?? "-"}°C</span>
    </button>
  );
}

export default function Dashboard({ onOpen, onAsk }) {
  const hb = useCached("healthBoard", api.healthBoard, 60_000, { pollMs: LIVE_MS });
  const tr = useCached("trends-week-8", () => api.trends("week", 8), 60_000, { pollMs: 60_000 });
  const al = useCached("alerts-all", () => api.alerts("all"), 60_000, { pollMs: LIVE_MS });
  const st = useCached("dataStatus", api.dataStatus, 60_000, { pollMs: 30_000 });
  const hl = useCached("health", api.health, 15_000, { pollMs: LIVE_MS });
  const reloadAll = () => { hb.reload(); tr.reload(); al.reload(); st.reload(); hl.reload(); };

  if (hb.loading && !hb.data) return <PageSkeleton kpis={4} label="Loading the dashboard" />;
  if (hb.error && !hb.data) {
    return (
      <div className="page"><div className="chat-error" role="alert">{hb.error}
        <button className="btn ghost xs" onClick={reloadAll}>Try again</button></div></div>
    );
  }
  const board = hb.data;
  if (board.empty) {
    return (
      <div className="page">
        <div className="empty-state card">
          <h3>No data connected yet</h3>
          <p className="muted">Connect a data source to see the plant dashboard, abnormal-usage alerts and recommendations.</p>
          <button className="btn primary" onClick={() => onOpen("data")}>Open data connectors</button>
        </div>
      </div>
    );
  }

  const trendOf = Object.fromEntries((tr.data?.groups || []).map((g) => [g.group, g]));
  const utilities = [...board.utilities].sort((a, b) => STATUS_ORDER[b.status] - STATUS_ORDER[a.status]);
  const k = board.kpis;
  const needAttention = utilities.filter((u) => u.status !== "NORMAL").length;
  const alertsReady = !!al.data;           // until it arrives, show "loading" rather than a wrong "0 / none"
  const alerts = al.data?.alerts || [];
  const openAlerts = alerts.filter((a) => a.status === "OPEN" || a.status === "ACKNOWLEDGED");
  const risk = supplyRisk(board);
  const atRisk = risk.filter((r) => r.level !== "LOW").length;
  const recs = board.efficiency?.recommendations || [];

  // KPI inputs
  const availability = k.alarm_rate_7d_pct == null ? null : Math.round((100 - k.alarm_rate_7d_pct) * 10) / 10;
  const unstable = new Set(board.anomalies.filter((a) => a.metric === "pressure" || a.metric === "temperature").map((a) => a.utility_type));
  const leaks = board.anomalies.filter((a) => (a.metric === "flow" && a.direction === "up") || (a.metric === "pressure" && a.direction === "down"));
  const linkVerdicts = board.downtime_link?.by_utility_type || [];
  const linked = linkVerdicts.filter((x) => x.verdict === "possible link").length;
  const acked = alerts
    .filter((a) => a.acknowledged_at && a.created_at)
    .map((a) => (new Date(a.acknowledged_at) - new Date(a.created_at)) / 60000)
    .filter((m) => m >= 0);

  const datasets = st.data?.datasets || [];
  const totalRows = datasets.reduce((s, d) => s + (d.rows || 0), 0);
  const dbOk = hl.data?.database_ok;

  const deliverables = [
    { icon: <IconGauge />, title: "Utility health board", value: `${utilities.length} utilities`, note: needAttention ? `${needAttention} need attention` : "All normal", go: () => onOpen("health"), cta: "Open board" },
    { icon: <IconBell />, title: "Abnormal-consumption alerts", value: alertsReady ? `${openAlerts.length} open` : "…", note: alertsReady ? `${alerts.length} raised in total` : "Loading alerts", go: () => onOpen("alerts"), cta: "Open alerts" },
    { icon: <IconScan />, title: "Leak / anomaly candidates", value: `${leaks.length} found`, note: `${board.anomalies.length} abnormal patterns in 7 days`, go: () => onOpen("health"), cta: "See findings" },
    { icon: <IconTool />, title: "Maintenance recommendations", value: `${recs.length} suggested`, note: recs[0] ? recs[0].action.slice(0, 64) + (recs[0].action.length > 64 ? "…" : "") : "Nothing to suggest", go: () => onOpen("health"), cta: "See suggestions" },
    { icon: <IconShield />, title: "Supply-risk report", value: `${atRisk} at risk`, note: atRisk ? "Review below" : "No supply risk found", go: () => document.getElementById("supply-risk")?.scrollIntoView({ behavior: "smooth", block: "start" }), cta: "Jump to report" },
  ];

  return (
    <div className="page dash">
      <header className="dash-hero">
        <div className="dash-hero-text">
          <h2 className="eyebrow">Utilities Management Agent · {hl.data?.site || "Plant"}</h2>
          <p className="muted">Data as of {formatDateTime(board.as_of)} · {number(k.readings_7d)} readings checked in the last 7 days</p>
        </div>
      </header>

      <section className={`dstatus tone-${needAttention ? "attention" : "ok"}`} aria-label="Plant status">
        <span className="dstatus-icon" aria-hidden="true">{needAttention ? "!" : "✓"}</span>
        <div className="dstatus-text">
          <h3>{needAttention ? `${needAttention} of ${utilities.length} utilities need attention` : `All ${utilities.length} utilities are behaving normally`}</h3>
          <p>Each utility is compared with its own normal pattern over the last 7 days. The agent is advisory only and never operates equipment.</p>
        </div>
        <ul className="dstatus-chips">
          <li className={dbOk ? "ok" : "bad"}><IconDatabase width={14} height={14} /> {!dbOk ? (hl.loading ? "Checking database…" : "Database unreachable") : st.data ? `${number(totalRows)} rows in database` : "Database connected"}</li>
          <li className={hl.data ? "ok" : "bad"}><IconBolt width={14} height={14} /> {hl.data ? "Agent online" : hl.loading ? "Checking agent…" : "Agent offline"}</li>
        </ul>
      </section>

      <section className="dkpis" aria-label="Key performance indicators">
        <Kpi label="Utility availability" icon={<IconBolt width={15} height={15} />} tone="ok"
             value={availability == null ? "-" : availability} unit={availability == null ? "" : "%"}
             caption={`readings without an alarm · ${number(k.alarms_7d)} alarms in 7 days`}
             hint="Share of readings in the last 7 days that carried no utility alarm. A proxy for availability." />
        <Kpi label="Pressure / temp stability" icon={<IconGauge width={15} height={15} />}
             tone={unstable.size ? "warn" : "ok"}
             value={`${utilities.length - unstable.size}/${utilities.length}`} unit=" stable"
             caption="utilities with steady pressure & temperature vs own history"
             hint="A utility counts as unstable when its pressure or temperature moved significantly against its own earlier history." />
        <Kpi label="Utility-related downtime" icon={<IconTool width={15} height={15} />}
             tone={linked ? "warn" : "neutral"}
             value={number(k.downtime_minutes_7d)} unit=" min"
             caption={`${k.downtime_events_7d} events in 7 days · ${linked ? `${linked} possible link${linked === 1 ? "" : "s"} to alarms` : "no link to utility alarms"}`}
             hint="All downtime in the last 7 days. The agent tests whether downtime starts more often right after utility alarms." />
        <Kpi label="Alert response time" icon={<IconBell width={15} height={15} />} tone="neutral"
             value={alertsReady ? fmtMinutes(mean(acked)) : "…"}
             caption={!alertsReady ? "loading alerts" : acked.length ? `mean time to acknowledge · ${acked.length} alert${acked.length === 1 ? "" : "s"}` : "no alert acknowledged yet"}
             hint="Average time from an alert being raised to a person acknowledging it." />
      </section>

      <div className="dgrid">
        <section className="card dpanel" aria-label="Utilities at a glance">
          <header className="dpanel-head">
            <div><h3>Utilities at a glance</h3><p className="small muted">Load index is a relative level, because units differ in the data. Click a tile for details.</p></div>
          </header>
          <div className="utiles">
            {utilities.map((u) => <UtilityTile key={u.utility_type} u={u} trend={trendOf[u.utility_type]} onClick={() => onOpen("health")} />)}
          </div>
        </section>

        <aside className="dside">
          <section className="card dpanel" aria-label="Open alerts">
            <header className="dpanel-head">
              <div><h3>Open alerts</h3><p className="small muted">{!alertsReady ? "Loading…" : openAlerts.length ? `${openAlerts.length} waiting for a person` : "Nothing waiting"}</p></div>
            </header>
            {!alertsReady ? (
              <div className="skel skel-line" aria-hidden="true" />
            ) : openAlerts.length === 0 ? (
              <p className="small muted dempty">No open alerts right now. New alerts appear here by themselves.</p>
            ) : (
              <ul className="alert-feed">
                {openAlerts.slice(0, 5).map((a) => (
                  <li key={a.id}>
                    <StatusPill value={a.severity} />
                    <div><strong>{a.title}</strong><span className="small muted">{utilityLabel(a.utility_type)} · {timeAgo(a.created_at)} · {a.status.toLowerCase()}</span></div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="card dpanel" aria-label="Ask the agent">
            <header className="dpanel-head"><div><h3>Ask the agent</h3><p className="small muted">Plain-language questions, answered from your data.</p></div></header>
            <div className="ask-list">
              {ASK.map((q) => (
                <button key={q} className="ask" onClick={() => onAsk(q)}><IconChat width={15} height={15} /><span>{q}</span></button>
              ))}
            </div>
          </section>
        </aside>
      </div>

      <div className="dgrid dgrid-even">
        <section className="card dpanel" id="supply-risk" aria-label="Supply-risk report">
          <header className="dpanel-head">
            <div>
              <h3>Supply-risk report</h3>
              <p className="small muted" title="HIGH: an alarming abnormal pattern. MEDIUM: a smaller abnormal pattern, or downtime that follows its alarms. LOW: neither.">
                Which utility could threaten production first. Ranked by risk.
              </p>
            </div>
          </header>
          <ul className="srisk-list">
            {risk.map((r) => (
              <li key={r.utility_type}>
                {r.level === "LOW" ? <StatusPill value="MINIMAL" label="LOW" /> : <StatusPill value={r.level} />}
                <div><strong>{utilityLabel(r.utility_type)}</strong><span className="small muted">{r.reason}</span></div>
              </li>
            ))}
          </ul>
        </section>

        <section className="card dpanel" aria-label="Recommended actions">
          <header className="dpanel-head">
            <div><h3>Recommended actions</h3><p className="small muted">{board.efficiency?.conclusion || "Efficiency suggestions appear when machine data is connected."}</p></div>
          </header>
          {recs.length === 0 ? (
            <p className="small muted dempty">No actions suggested right now.</p>
          ) : (
            <ul className="rec-list">
              {recs.slice(0, 3).map((r, i) => (
                <li key={i}>
                  <StatusPill value={r.priority} />
                  <div><strong>{r.action}</strong><span className="small muted">Owner: {r.owner}</span></div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="sect" aria-label="What this agent delivers">
        <div className="sect-head">
          <h3>What this agent delivers</h3>
          <p className="small muted">The five outputs of the Utilities Management Agent, each computed from your data.</p>
        </div>
        <div className="outputs">
          {deliverables.map((d) => (
            <button key={d.title} className="card output" onClick={d.go}>
              <span className="output-icon">{d.icon}</span>
              <span className="output-title">{d.title}</span>
              <span className="output-value">{d.value}</span>
              <span className="output-note small muted">{d.note}</span>
              <span className="output-cta">{d.cta} ›</span>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
