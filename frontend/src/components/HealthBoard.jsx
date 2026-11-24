import { lazy, Suspense } from "react";
import { api } from "../api/client.js";
import { useCached } from "../hooks/useCached.js";
import { formatDateTime, number, pct, STATUS_ORDER, utilityLabel } from "../lib/format.js";
import PageSkeleton from "./Skeleton.jsx";
import Sparkline from "./Sparkline.jsx";
import StatusPill from "./StatusPill.jsx";
import { Spinner } from "./icons.jsx";

const PlantScene = lazy(() => import("./PlantScene.jsx"));

function UtilityCard({ u, trend }) {
  const change = u.flow_change_pct;
  const dir = change == null ? "flat" : change > 0 ? "up" : change < 0 ? "down" : "flat";
  const arrow = dir === "up" ? "▲" : dir === "down" ? "▼" : "–";
  return (
    <article id={`util-${u.utility_type}`} className={`card ucard status-${u.status.toLowerCase()}`} aria-label={`${utilityLabel(u.utility_type)} ${u.status}`}>
      <header className="ucard-head">
        <h3>{utilityLabel(u.utility_type)}</h3>
        <StatusPill value={u.status} />
      </header>

      <div className="ucard-main">
        <div className="ucard-value">{u.avg_flow_24h ?? "-"}</div>
        <div className="ucard-cap">Load index, last 24 h</div>
        <div className={`delta delta-${dir}`} title="Change against the previous 7 days">
          <span>{arrow} {change == null ? "-" : `${Math.abs(change)}%`}</span>
          <small>vs previous 7 d</small>
        </div>
      </div>

      {trend && (
        <div className="ucard-trend" title={trend.last_vs_previous_pct != null ? `${pct(trend.last_vs_previous_pct)} last week` : undefined}>
          <Sparkline series={trend.series} />
          <p className="small muted">Weekly trend: <strong>{trend.direction}</strong></p>
        </div>
      )}

      <p className="ucard-foot" title="Alarms in 7 days · average pressure · average temperature (last 24 h)">
        {u.alarms_7d} alarms · {u.avg_pressure_bar_24h ?? "-"} bar · {u.avg_temperature_c_24h ?? "-"}°C
      </p>
      {u.status !== "NORMAL" && <p className="ucard-note">{u.reasons[0]}</p>}
    </article>
  );
}

function Accordion({ label, title, result, tone = "normal", children }) {
  return (
    <section className="card acc" aria-label={label}>
      <details>
        <summary>
          <span className="acc-title">{title}</span>
          <span className={`acc-result tone-${tone}`}>{result}</span>
          <span className="acc-chev" aria-hidden="true">›</span>
        </summary>
        <div className="acc-body">{children}</div>
      </details>
    </section>
  );
}

function Anomalies({ hb }) {
  const n = hb.anomalies.length;
  return (
    <Accordion label="Abnormal usage" title="Abnormal usage, last 7 days"
               result={n ? `${n} found` : "Nothing abnormal"} tone={n ? "warning" : "normal"}>
      <p className="small muted">{hb.anomaly_conclusion}</p>
      {n > 0 && (
        <ul className="finding-list">
          {hb.anomalies.map((a, i) => (
            <li key={i}>
              <div className="finding-head"><StatusPill value={a.severity} /><strong>{a.description}</strong></div>
              <p className="small muted">{a.likely_cause}</p>
              <p className="small"><strong>Do:</strong> {a.recommendation}</p>
            </li>
          ))}
        </ul>
      )}
    </Accordion>
  );
}

function DowntimeLink({ link }) {
  if (!link) return null;
  const possible = link.by_utility_type.some((x) => x.verdict === "possible link");
  return (
    <Accordion label="Downtime correlation" title="Utilities and downtime"
               result={possible ? "Possible link" : "No link found"} tone={possible ? "watch" : "normal"}>
      <p className="small muted">{link.conclusion}</p>
      <table className="mini-table">
        <thead><tr><th>Utility</th><th>Downtime after alarm vs normal</th><th>Verdict</th></tr></thead>
        <tbody>
          {link.by_utility_type.map((x) => (
            <tr key={x.utility_type}>
              <td>{utilityLabel(x.utility_type)}</td>
              <td className="num">{x.lift != null ? `${x.lift}×` : "-"} <span className="muted small">({x.downtime_events_after_alarm} events)</span></td>
              <td><StatusPill value={x.verdict === "possible link" ? "WATCH" : "NORMAL"} label={x.verdict} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </Accordion>
  );
}

function Suggestions({ eff }) {
  if (!eff) return null;
  return (
    <section className="sect" aria-label="Efficiency recommendations">
      <div className="sect-head">
        <h3>What we suggest</h3>
        <p className="small muted">{eff.conclusion}</p>
      </div>
      {eff.recommendations.length > 0 && (
        <div className="recs">
          {eff.recommendations.map((r, i) => (
            <article key={i} className="card rec">
              <StatusPill value={r.priority} />
              <h4>{r.action}</h4>
              <p className="rec-owner">Owner: <strong>{r.owner}</strong></p>
              <details>
                <summary>Why?</summary>
                <p className="small muted">{r.why}</p>
              </details>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

export default function HealthBoard({ onOpenData }) {
  // Shown at once from what is already known (even from an earlier visit) and refreshed quietly in the background.
  const board = useCached("healthBoard", api.healthBoard, 60_000, { pollMs: 15_000 });
  const trendQ = useCached("trends-week-8", () => api.trends("week", 8), 60_000, { pollMs: 60_000 });

  if (board.loading && !board.data) return <PageSkeleton kpis={3} label="Loading the health board" />;
  if (board.error && !board.data) return <div className="page"><div className="chat-error" role="alert">{board.error}</div></div>;

  const hb = board.data;
  const trends = hb.empty ? null : trendQ.data;
  if (hb.empty) {
    return (
      <div className="page">
        <div className="empty-state card">
          <h3>No data yet</h3>
          <p className="muted">Upload the utility telemetry, machine telemetry and downtime CSV files to see the dashboard.</p>
          <button className="btn primary" onClick={onOpenData}>Go to Data</button>
        </div>
      </div>
    );
  }

  const trendOf = Object.fromEntries((trends?.groups || []).map((g) => [g.group, g]));
  const utilities = [...hb.utilities].sort((a, b) => STATUS_ORDER[b.status] - STATUS_ORDER[a.status]);
  const k = hb.kpis;
  const needAttention = utilities.filter((u) => u.status !== "NORMAL").length;
  const focusUtility = (type) => {
    const el = document.getElementById(`util-${type}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("flash");
    setTimeout(() => el.classList.remove("flash"), 1600);
  };
  const headline = needAttention === 0
    ? `All ${utilities.length} utilities are behaving normally`
    : `${needAttention} of ${utilities.length} utilities need attention`;

  return (
    <div className="page calm">
      <header className="page-head">
        <div>
          <h2>Utility health board</h2>
          <p className="muted">Data as of {formatDateTime(hb.as_of)}</p>
        </div>
      </header>

      <section className={`summary tone-${needAttention ? "attention" : "ok"}`} aria-label="Summary">
        <div className="summary-main">
          <span className="summary-icon" aria-hidden="true">{needAttention ? "!" : "✓"}</span>
          <div>
            <h3>{headline}</h3>
            <p>Each utility is compared with its own normal pattern over the last 7 days.</p>
          </div>
        </div>
        <dl className="summary-stats">
          <div className="summary-stat"><dt>Alarms, 7 d</dt><dd>{number(k.alarms_7d)}</dd></div>
          <div className="summary-stat"><dt>Downtime, 7 d</dt><dd>{number(k.downtime_minutes_7d)} <small>min</small></dd></div>
          <div className="summary-stat"><dt>Open alerts</dt><dd>{hb.open_alerts ?? 0}</dd></div>
        </dl>
      </section>

      <section className="card plant-card" aria-label="iPhone assembly line">
        <header className="plant-head">
          <div>
            <h3>iPhone assembly line</h3>
            <p className="small muted">Each station is fed by one utility. The dot shows that utility's status. Click a label for details.</p>
          </div>
        </header>
        <Suspense fallback={<div className="plant center muted"><Spinner /> Building the 3D line…</div>}>
          <PlantScene utilities={utilities} onSelect={focusUtility} />
        </Suspense>
      </section>

      <section className="sect" aria-label="Utilities">
        <div className="sect-head">
          <h3>Utilities</h3>
          <p className="small muted">
            <StatusPill value="NORMAL" /> as usual &nbsp; <StatusPill value="WATCH" /> small deviation &nbsp; <StatusPill value="ALARM" /> check now.
            Load index is a relative usage level, because the units in the data differ.
          </p>
        </div>
        <div className="systems">
          {utilities.map((u) => <UtilityCard key={u.utility_type} u={u} trend={trendOf[u.utility_type]} />)}
        </div>
      </section>

      <Suggestions eff={hb.efficiency} />

      <section className="sect" aria-label="More details">
        <div className="sect-head">
          <h3>More details</h3>
          <p className="small muted">Open a line to see how the result was worked out.</p>
        </div>
        <div className="accs">
          <Anomalies hb={hb} />
          <DowntimeLink link={hb.downtime_link} />
          {hb.data_quality.length > 0 && (
            <Accordion label="Data quality" title="Read the numbers with care"
                       result={`${hb.data_quality.length} notes`} tone="watch">
              <ul className="finding-list plain">{hb.data_quality.map((n, i) => <li key={i} className="small muted">{n}</li>)}</ul>
            </Accordion>
          )}
        </div>
      </section>
    </div>
  );
}
