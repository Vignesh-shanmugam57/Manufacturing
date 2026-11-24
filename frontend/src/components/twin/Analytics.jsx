import { useEffect, useMemo, useState } from "react";
import { twinApi } from "../../api/client.js";
import { UTILITIES, UTILITY_COLOR, UTILITY_LABEL, formatWhen } from "./labels.js";
import { COLORS, LineChart, PageHead } from "./ui.jsx";
import PlantData from "./PlantData.jsx";
import { fmt, state, useTwin, useTwinResource } from "../../lib/twin.js";

const WINDOWS = [[15, "15 min"], [60, "1 hour"], [360, "6 hours"], [1440, "24 hours"], [10080, "7 days"]];

function csv(rows) {
  const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  return ["time,alert,equipment,actor,action,detail", ...rows.map((r) => [r.ts, r.alert_code, r.equipment_id, r.actor, r.action, r.detail].map(esc).join(","))].join("\n");
}

/** Consumption analytics, historical trends (from the live buffer and stored history) and the audit trail. */
export default function Analytics() {
  const k = useTwin((s) => s.snap?.kpis);
  const catalog = useTwin((s) => s.catalog);
  const audit = useTwinResource("/audit?limit=300");
  const [tag, setTag] = useState("CA-HDR-A.pressure_bar");
  const [minutes, setMinutes] = useState(60);
  const [pts, setPts] = useState(null);
  const [err, setErr] = useState("");
  const [filter, setFilter] = useState("");

  useEffect(() => {
    let alive = true;
    setPts(null); setErr("");
    twinApi.get(`/series?tags=${encodeURIComponent(tag)}&minutes=${minutes}&step=${minutes <= 60 ? 5 : minutes <= 360 ? 30 : 300}`)
      .then((r) => { if (alive) setPts(r.series[tag] || []); })
      .catch((e) => { if (alive) setErr(e.message); });
    return () => { alive = false; };
  }, [tag, minutes]);

  const groups = useMemo(() => UTILITIES.map((u) => ({ u, tags: (catalog?.equipment || []).filter((e) => e.utility === u).flatMap((e) => e.sensors.filter((s) => !s.cumulative && s.normal).map((s) => ({ tag: s.tag, text: `${e.name}: ${s.label}` }))) })), [catalog]);
  const meta = state.tags[tag];
  const events = (audit.data?.events || []).filter((e) => !filter || `${e.alert_code} ${e.equipment_id} ${e.actor} ${e.action} ${e.detail}`.toLowerCase().includes(filter.toLowerCase()));
  const totalCost = k ? Math.max(k.cost, 0.0001) : 1;

  function download() {
    const blob = new Blob([csv(audit.data?.events || [])], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = `utilities-audit-${new Date().toISOString().slice(0, 10)}.csv`; a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <div className="page tpage">
      <PageHead title="Analytics and reports" sub="Plant operations from the database, consumption by utility, historical trends and the complete event history." />
      <PlantData />
      {k && (
        <section className="card tcard">
          <header className="tcard-head"><div><h3>Consumption by utility</h3><p className="small muted">Since the service started {formatWhen(k.since)}. Cost uses the DEMO tariffs set on the Configuration page.</p></div></header>
          <table className="ttable">
            <thead><tr><th>Utility</th><th>Consumed</th><th>Availability (1 h)</th></tr></thead>
            <tbody>
              {UTILITIES.map((u) => (
                <tr key={u}><td><span className="rail-dot" style={{ background: UTILITY_COLOR[u] }} /> {UTILITY_LABEL[u]}</td>
                  <td className="num"><b>{fmt(k.consumption[u].value, 0)}</b> {k.consumption[u].unit}</td>
                  <td className="num">{fmt(k.availability_by_utility[u], 1)}%</td></tr>
              ))}
              <tr className="sum"><td>Electrical energy</td><td className="num"><b>{fmt(k.energy_kwh, 0)}</b> kWh</td><td className="num">total cost {k.currency} {fmt(totalCost, 2)}</td></tr>
            </tbody>
          </table>
        </section>
      )}

      <section className="card tcard">
        <header className="tcard-head">
          <div><h3>Historical trend</h3><p className="small muted">Up to 2 hours at 1 s resolution from live memory, longer periods from the stored 5-minute history.</p></div>
          <div className="tfilters inline">
            <select value={tag} onChange={(e) => setTag(e.target.value)} aria-label="Sensor">
              {groups.map((g) => <optgroup key={g.u} label={UTILITY_LABEL[g.u]}>{g.tags.map((t) => <option key={t.tag} value={t.tag}>{t.text}</option>)}</optgroup>)}
            </select>
            <select value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} aria-label="Period">{WINDOWS.map(([m, l]) => <option key={m} value={m}>{l}</option>)}</select>
          </div>
        </header>
        {err ? <p className="form-error">{err}</p> : pts === null ? <div className="skel skel-line" /> : pts.length < 2 ? <p className="muted small">Not enough history stored for this period yet. History is saved every 5 minutes while the service runs.</p> : (
          <LineChart series={[{ name: meta?.label || tag, color: COLORS[0], points: pts }]} height={200} band={null} unit={meta?.unit} decimals={meta?.decimals ?? 1} />
        )}
      </section>

      <section className="card tcard">
        <header className="tcard-head">
          <div><h3>Event history and audit trail</h3><p className="small muted">Every detection, notification and user action on every alert.</p></div>
          <div className="tfilters inline"><input type="search" placeholder="Filter events" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter events" /><button className="btn ghost xs" onClick={download} disabled={!audit.data?.events?.length}>Download CSV</button></div>
        </header>
        {events.length === 0 ? <p className="muted small">No events yet.</p> : (
          <div className="ttable-wrap"><table className="ttable">
            <thead><tr><th>Time</th><th>Alert</th><th>Equipment</th><th>Who</th><th>Action</th><th>Detail</th></tr></thead>
            <tbody>{events.slice(0, 120).map((e, i) => <tr key={i}><td className="small">{formatWhen(e.ts)}</td><td className="mono">{e.alert_code}</td><td className="mono">{e.equipment_id}</td><td>{e.actor}</td><td><b>{e.action.replace(/_/g, " ")}</b></td><td className="small">{e.detail}</td></tr>)}</tbody>
          </table></div>
        )}
      </section>
    </div>
  );
}
