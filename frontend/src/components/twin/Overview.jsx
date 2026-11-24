import { useMemo } from "react";
import { UTILITIES, UTILITY_COLOR, UTILITY_LABEL, KEY_TAGS, timeAgoShort } from "./labels.js";
import { COLORS, LevelPill, LineChart, Metric, PageHead, SeverityPill } from "./ui.jsx";
import { SAMPLE_ALARMS } from "./sampleAlarms.js";
import { LEVELS, LEVEL_COLOR, fmt, parseBand, sensorFmt, state, useSeries, useTwin, useTwinResource } from "../../lib/twin.js";

function Chart({ title, sub, tags, height = 150, seconds = 600 }) {
  const series = useSeries(tags, seconds);
  const meta = tags.map((t) => state.tags[t]);
  return (
    <section className="card tcard">
      <header className="tcard-head"><div><h3>{title}</h3>{sub && <p className="small muted">{sub}</p>}</div></header>
      <LineChart series={tags.map((t, i) => ({ name: meta[i]?.label || (t === "_total_power_kw" ? "Total power" : t), color: COLORS[i % COLORS.length], points: series[i] || [] }))}
                 height={height} band={tags.length === 1 && meta[0] ? parseBand(meta[0].normal) : null}
                 unit={meta[0]?.unit || (tags[0] === "_total_power_kw" ? "kW" : "")} decimals={meta[0]?.decimals ?? 1} windowSec={seconds} />
    </section>
  );
}

/** Live plant overview: every number here comes from the telemetry stream and the agent's own records. */
export default function Overview() {
  const k = useTwin((s) => s.snap?.kpis);
  const levels = useTwin((s) => s.snap?.levels);
  const values = useTwin((s) => s.snap?.values);
  const catalog = useTwin((s) => s.catalog);
  const scenario = useTwin((s) => s.snap?.scenario);
  const alertsRes = useTwinResource("/alerts?status=active");
  const alerts = alertsRes.data?.alerts || [];

  const health = useMemo(() => {
    const counts = [0, 0, 0, 0, 0];
    (catalog?.equipment || []).forEach((e) => { counts[levels?.[e.id] ?? 0] += 1; });
    const worst = (catalog?.equipment || []).filter((e) => (levels?.[e.id] ?? 0) >= 1 && levels[e.id] < 4)
      .sort((a, b) => levels[b.id] - levels[a.id]).slice(0, 5);
    return { counts, worst };
  }, [catalog, levels]);

  const top = useMemo(() => {
    if (!values) return [];
    return Object.entries(state.tags).filter(([t, s]) => t.endsWith(".power_kw") && s.nominal > 0 && !s.equipment.standby)
      .map(([t, s]) => ({ tag: t, name: s.equipment.name, v: values[t], ratio: values[t] / s.nominal, unit: s.unit }))
      .sort((a, b) => b.ratio - a.ratio).slice(0, 5);
  }, [values, catalog]);

  if (!k) return <div className="page tpage"><PageHead title="Live plant overview" sub="Connecting to the telemetry stream…" /><div className="skel skel-block" /></div>;
  const cons = k.consumption;
  const costTip = UTILITIES.map((u) => `${UTILITY_LABEL[u]}: ${fmt(cons[u].value, 0)} ${cons[u].unit}`).join("\n");

  return (
    <div className="page tpage">
      <PageHead title="Live plant overview" sub="Utilities, equipment and agent findings, updating every second. Counters run since the service started.">
        {scenario?.active && <span className="tchip warn">Demo fault running: {scenario.title}</span>}
      </PageHead>

      <section className="tmetrics" aria-label="Key indicators">
        <Metric label="Total utility consumption" value={fmt(k.energy_kwh, 0)} unit=" kWh" caption="electrical energy since start" hint={costTip} />
        <Metric label="Total utility cost" value={`${k.currency} ${fmt(k.cost, 2)}`} caption="electricity + gas + water at DEMO tariffs" />
        <Metric label="Utility availability" value={fmt(k.availability_pct, 1)} unit="%" caption="last hour, all utilities" tone={k.availability_pct < 100 ? 2 : 0} />
        <Metric label="Active equipment" value={`${k.equipment_active}/${k.equipment_total}`} caption="running and reporting" />
        <Metric label="Active alarms" value={k.alarms_active} caption={`${k.alerts_unacknowledged} not yet acknowledged`} tone={k.alarms_active ? 1 : 0} />
        <Metric label="Critical alerts" value={k.alerts_critical} caption="escalated by rule" tone={k.alerts_critical ? 3 : 0} />
        <Metric label="Suspected leakage" value={k.leaks_suspected} caption={k.leaks_suspected ? `about ${fmt(k.leak_est_m3min, 1)} m3/min extra air` : "no leak pattern detected"} tone={k.leaks_suspected ? 2 : 0} />
        <Metric label="Equipment efficiency" value={fmt(k.efficiency_pct, 1)} unit="%" caption="compressors, chillers, boilers" />
        <Metric label="Utility-related downtime" value={fmt(k.downtime_min, 1)} unit=" min" caption="starved lines, simulated MES" tone={k.downtime_min > 0 ? 2 : 0} />
      </section>

      <div className="tgrid2">
        <Chart title="Plant electrical power" sub="Sum of all metered drives, last 10 minutes" tags={["_total_power_kw"]} />
        <Chart title="Compressed air header pressure (Hall A)" sub="Shaded band is the normal range" tags={["CA-HDR-A.pressure_bar"]} />
        <Chart title="Chilled water Delta T (Chiller 1)" sub="Return minus supply temperature" tags={["CW-CHL-01.delta_t_c"]} />
        <Chart title="Steam header pressure" sub="Instability shows as swings" tags={["ST-HDR-01.pressure_bar"]} />
      </div>

      <section className="card tcard" aria-label="Utility systems">
        <header className="tcard-head"><div><h3>Utility systems</h3><p className="small muted">Status, key reading, availability and consumption for each of the seven systems.</p></div></header>
        <div className="usys">
          {UTILITIES.map((u) => {
            const eqs = (catalog?.equipment || []).filter((e) => e.utility === u);
            const worst = Math.max(0, ...eqs.map((e) => (levels?.[e.id] === 4 ? 0 : levels?.[e.id] ?? 0)));
            const t0 = state.tags[KEY_TAGS[u][0]], t1 = state.tags[KEY_TAGS[u][1]];
            return (
              <div key={u} className={`usys-card lv-${worst}`}>
                <div className="usys-head"><span className="usys-dot" style={{ background: UTILITY_COLOR[u] }} /><b>{UTILITY_LABEL[u]}</b><LevelPill level={worst} /></div>
                <div className="usys-reads">
                  {[t0, t1].filter(Boolean).map((s) => <div key={s.tag}><span>{s.label}</span><b>{sensorFmt(s, values?.[s.tag])}</b></div>)}
                </div>
                <div className="usys-foot">
                  <span>Availability <b>{fmt(k.availability_by_utility[u], 1)}%</b></span>
                  <span>Used <b>{fmt(cons[u].value, 0)} {cons[u].unit}</b></span>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <div className="tgrid3">
        <section className="card tcard">
          <header className="tcard-head"><div><h3>Equipment health</h3><p className="small muted">{k.equipment_total} monitored assets</p></div></header>
          <div className="healthbar" role="img" aria-label="Equipment status distribution">
            {health.counts.map((n, l) => n > 0 && <span key={l} style={{ flex: n, background: LEVEL_COLOR[l] }} title={`${LEVELS[l]}: ${n}`}>{n}</span>)}
          </div>
          <ul className="legend-list">{health.counts.map((n, l) => <li key={l}><i style={{ background: LEVEL_COLOR[l] }} />{LEVELS[l]} <b>{n}</b></li>)}</ul>
          {health.worst.length > 0 && <ul className="eqp-list">{health.worst.map((e) => <li key={e.id}><LevelPill level={levels[e.id]} /><div><strong>{e.name}</strong><span className="small muted">{e.zone}</span></div></li>)}</ul>}
        </section>

        <section className="card tcard">
          <header className="tcard-head"><div><h3>Active alarms</h3><p className="small muted">{alerts.length ? `${alerts.length} open` : "Nothing open"}</p></div></header>
          {alerts.length === 0 ? <p className="muted small">{alertsRes.data == null ? "Loading live alarms…" : "No live alarms. Inject a demo fault on the Digital twin page to see the agent work."}</p> : (
            <ul className="eqp-list">
              {alerts.slice(0, 5).map((a) => <li key={a.id}><SeverityPill severity={a.severity} /><div><strong>{a.title}</strong><span className="small muted">{a.code} · {timeAgoShort(a.created_at)} · {a.status.replace("_", " ").toLowerCase()}</span></div></li>)}
            </ul>
          )}
          <div className="sample-alarms">
            <div className="sample-head"><h4>Sample alarms</h4><span className="sample-tag">Sample</span></div>
            <ul className="eqp-list">
              {SAMPLE_ALARMS.slice(0, 3).map((s) => <li key={s.code}><SeverityPill severity={s.severity} /><div><strong>{s.title}</strong><span className="small muted">{s.code} · {s.equipment}</span></div></li>)}
            </ul>
          </div>
        </section>

        <section className="card tcard">
          <header className="tcard-head"><div><h3>Top consuming equipment</h3><p className="small muted">Motor power against nominal</p></div></header>
          <ul className="toplist">
            {top.map((t) => (
              <li key={t.tag}>
                <span>{t.name}</span>
                <div className="bar"><i style={{ width: `${Math.min(100, t.ratio * 70)}%`, background: t.ratio > 1.15 ? "#f97316" : "#3b82f6" }} /></div>
                <b>{fmt(t.v, 1)} kW <small className={t.ratio > 1.15 ? "warn" : "muted"}>{(t.ratio - 1) * 100 >= 0 ? "+" : ""}{fmt((t.ratio - 1) * 100, 0)}%</small></b>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="card tcard" aria-label="Performance indicators">
        <header className="tcard-head"><div><h3>Performance indicators</h3><p className="small muted">Calculated from live data and the agent's own alert records.</p></div></header>
        <div className="tmetrics sm">
          <Metric label="Energy per production unit" value={fmt(k.energy_per_unit_kwh, 3)} unit=" kWh" caption={`${fmt(k.units_produced, 0)} units (simulated MES)`} />
          <Metric label="Pressure stability" value={fmt(k.pressure_stability_pct, 1)} unit="%" caption="air headers, last 5 min" />
          <Metric label="Temperature stability" value={fmt(k.temperature_stability_pct, 1)} unit="%" caption="chilled water supply, last 5 min" />
          <Metric label="Leakage loss" value={fmt(k.leak_est_m3min, 1)} unit=" m3/min" caption="estimated, active leak alerts" />
          <Metric label="Equipment runtime" value={fmt(k.runtime_h, 0)} unit=" h" caption="all assets, cumulative" />
          <Metric label="Abnormal consumption events" value={k.abnormal_events} caption="alerts raised" />
          <Metric label="Anomaly resolution" value={fmt(k.resolution_min, 1)} unit=" min" caption="raised to verified closed" />
        </div>
      </section>
    </div>
  );
}
