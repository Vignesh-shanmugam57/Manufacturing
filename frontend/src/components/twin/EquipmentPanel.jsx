import { useMemo, useState } from "react";
import { UTILITY_LABEL, formatWhen } from "./labels.js";
import { COLORS, LevelPill, LineChart, SeverityPill } from "./ui.jsx";
import { SEVERITY_LEVEL, fmt, parseBand, sensorFmt, state, useSeries, useTwin, useTwinPoll } from "../../lib/twin.js";

const TABS = ["Readings", "Trends", "Alarms"];

/** One piece of equipment: live readings against their limits, trends and alarms. */
export default function EquipmentPanel({ id, onClose, onFocus }) {
  const [tab, setTab] = useState("Readings");
  const { data: d } = useTwinPoll(id ? `/equipment/${id}` : null, 2500, !!id);
  const eq = useTwin((s) => s.byId[id]);
  const level = useTwin((s) => s.snap?.levels[id] ?? 0);
  const issueLevel = Math.max(0, ...(d?.alerts || []).filter((a) => a.status !== "VERIFIED").map((a) => SEVERITY_LEVEL[a.severity] ?? 1));
  const shown = issueLevel ? Math.max(level === 4 ? 0 : level, issueLevel) : level;      // an open issue is never shown as Normal
  const tags = useMemo(() => (eq ? eq.sensors.filter((s) => !s.cumulative).map((s) => s.tag) : []), [eq]);
  const values = useTwin((s) => Object.fromEntries((eq?.sensors || []).map((x) => [x.tag, s.snap?.values[x.tag]])), [id]);
  const series = useSeries(tags.slice(0, 8), 300);
  if (!eq) return null;
  const tagLevel = (tag) => state.snap?.tag_levels?.[tag] ?? 0;

  return (
    <aside className="eqpanel" aria-label={`Equipment ${eq.name}`}>
      <header className="eqp-head">
        <div>
          <p className="eyebrow">{UTILITY_LABEL[eq.utility]} · {eq.zone}</p>
          <h3>{eq.name}</h3>
          <p className="small muted">{eq.id} · {eq.category} · criticality {eq.criticality}{eq.standby ? " · standby unit" : ""}</p>
        </div>
        <div className="eqp-actions">
          <LevelPill level={shown} />
          {onFocus && <button className="btn ghost xs" onClick={() => onFocus(id)}>Focus</button>}
          <button className="icon-btn sm" onClick={onClose} aria-label="Close equipment panel">×</button>
        </div>
      </header>

      <nav className="eqp-tabs" role="tablist">
        {TABS.map((t) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t}</button>)}
      </nav>

      {tab === "Readings" && (
        <div className="eqp-body">
          <table className="eqp-table">
            <thead><tr><th>Sensor</th><th>Now</th><th>Normal range</th><th /></tr></thead>
            <tbody>
              {eq.sensors.map((s) => (
                <tr key={s.tag}>
                  <td>{s.label}</td>
                  <td className="num"><b>{sensorFmt(s, values[s.tag])}</b></td>
                  <td className="muted small">{s.cumulative ? "counter" : s.normal || "-"}</td>
                  <td>{!s.cumulative && s.normal && <i className={`ldot lv-${tagLevel(s.tag)}`} title={["Normal", "Warning", "Major", "Critical"][tagLevel(s.tag)]} />}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <dl className="eqp-facts">
            <div><dt>Supplies</dt><dd>{eq.consumers.join(", ") || "-"}</dd></div>
            {d && <div><dt>Running hours</dt><dd>{d.runtime_h != null ? fmt(d.runtime_h, 0) : "-"}</dd></div>}
          </dl>
        </div>
      )}

      {tab === "Trends" && (
        <div className="eqp-body eqp-trends">
          {tags.slice(0, 8).map((tag, i) => {
            const s = state.tags[tag];
            return (
              <figure key={tag}>
                <figcaption><b>{s.label}</b><span className="muted small">{s.unit} · expected {s.normal}</span></figcaption>
                <LineChart series={[{ name: s.label, color: COLORS[i % COLORS.length], points: series[i] || [] }]} height={120}
                           band={parseBand(s.normal)} unit={s.unit} decimals={s.decimals} windowSec={300} />
              </figure>
            );
          })}
        </div>
      )}

      {tab === "Alarms" && (
        <div className="eqp-body">
          {!d ? <p className="muted">Loading…</p> : d.alerts.length === 0 ? <p className="muted">No alarms for this equipment.</p> : (
            <ul className="eqp-list">
              {d.alerts.map((a) => (
                <li key={a.id}><SeverityPill severity={a.severity} />
                  <div><strong>{a.title}</strong><span className="small muted">{a.code} · {a.status.replace("_", " ").toLowerCase()} · {formatWhen(a.created_at)}</span></div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </aside>
  );
}
