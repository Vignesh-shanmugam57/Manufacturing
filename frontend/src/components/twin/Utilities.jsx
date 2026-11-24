import { useState } from "react";
import EquipmentPanel from "./EquipmentPanel.jsx";
import { KEY_TAGS, UTILITIES, UTILITY_COLOR, UTILITY_DETECTS, UTILITY_LABEL, timeAgoShort } from "./labels.js";
import { COLORS, LevelPill, LineChart, PageHead, SeverityPill } from "./ui.jsx";
import { fmt, parseBand, sensorFmt, state, useSeries, useTwin, useTwinResource } from "../../lib/twin.js";

function KeyChart({ tag, i }) {
  const s = state.tags[tag];
  const [pts] = useSeries([tag], 600);
  if (!s) return null;
  return (
    <section className="card tcard">
      <header className="tcard-head"><div><h3>{s.equipment.name}: {s.label}</h3><p className="small muted">Expected {s.normal} · last 10 minutes</p></div>
        <b className="bignum">{sensorFmt(s, state.snap?.values[tag])}</b></header>
      <LineChart series={[{ name: s.label, color: COLORS[i % COLORS.length], points: pts || [] }]} height={140} band={parseBand(s.normal)} unit={s.unit} decimals={s.decimals} windowSec={600} />
    </section>
  );
}

/** One page per utility: equipment, live readings, trends and what the agent watches for. */
export default function Utilities() {
  const [u, setU] = useState("COMPRESSED_AIR");
  const [inspect, setInspect] = useState(null);
  const catalog = useTwin((s) => s.catalog);
  const levels = useTwin((s) => s.snap?.levels);
  const values = useTwin((s) => s.snap?.values);
  const k = useTwin((s) => s.snap?.kpis);
  const alerts = (useTwinResource("/alerts?status=active").data?.alerts || []).filter((a) => a.utility === u);
  const eqs = (catalog?.equipment || []).filter((e) => e.utility === u);
  const worst = Math.max(0, ...eqs.map((e) => (levels?.[e.id] === 4 ? 0 : levels?.[e.id] ?? 0)));
  const cons = k?.consumption?.[u];

  return (
    <div className="page tpage">
      <PageHead title="Utility monitoring" sub="Select a utility to see its equipment, live readings, trends and the conditions the agent watches for." />
      <div className="utabs" role="tablist" aria-label="Utility">
        {UTILITIES.map((id) => (
          <button key={id} role="tab" aria-selected={u === id} className={u === id ? "on" : ""} onClick={() => setU(id)}>
            <span className="rail-dot" style={{ background: UTILITY_COLOR[id] }} />{UTILITY_LABEL[id]}
          </button>
        ))}
      </div>

      <section className="card tcard uhead">
        <div><h3>{UTILITY_LABEL[u]}</h3><p className="small muted"><b>Watched for:</b> {UTILITY_DETECTS[u]}</p></div>
        <div className="uhead-stats">
          <LevelPill level={worst} />
          <span>Availability <b>{fmt(k?.availability_by_utility?.[u], 1)}%</b></span>
          {cons && <span>Consumed <b>{fmt(cons.value, 0)} {cons.unit}</b></span>}
        </div>
      </section>

      {alerts.length > 0 && (
        <section className="card tcard">
          <header className="tcard-head"><h3>Active alarms</h3></header>
          <ul className="eqp-list">{alerts.map((a) => <li key={a.id}><SeverityPill severity={a.severity} /><div><strong>{a.title}</strong><span className="small muted">Reading {a.actual} (expected {a.expected}) · {timeAgoShort(a.created_at)}</span></div></li>)}</ul>
        </section>
      )}

      <div className="tgrid2">{KEY_TAGS[u].map((t, i) => <KeyChart key={t} tag={t} i={i} />)}</div>

      <section className="card tcard">
        <header className="tcard-head"><div><h3>Equipment</h3><p className="small muted">Click a unit for its readings, trends, alarms and maintenance.</p></div></header>
        <div className="eqcards">
          {eqs.map((e) => {
            const lv = levels?.[e.id] ?? 0;
            const main = e.sensors.filter((s) => !s.cumulative && s.normal).slice(0, 3);
            return (
              <button key={e.id} className={`eqcard lv-${lv}`} onClick={() => setInspect(e.id)}>
                <span className="eqcard-top"><b>{e.name}</b><LevelPill level={lv} /></span>
                <span className="small muted">{e.id} · {e.zone}</span>
                <span className="eqcard-reads">{main.map((s) => <span key={s.tag}><em>{s.label}</em><b>{sensorFmt(s, values?.[s.tag])}</b></span>)}</span>
              </button>
            );
          })}
        </div>
      </section>
      {inspect && <div className="eq-drawer"><EquipmentPanel id={inspect} onClose={() => setInspect(null)} /></div>}
    </div>
  );
}
