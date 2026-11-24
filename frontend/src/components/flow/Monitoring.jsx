import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client.js";
import { useCached } from "../../hooks/useCached.js";
import { LEVEL_COLOR, LEVELS, fmt, useTwinPoll } from "../../lib/twin.js";
import "../../styles/overview.css";

const pct = (x) => (x == null ? "-" : `${fmt(x, 1)}%`);
const label = (s) => String(s || "").replace(/_/g, " ").toLowerCase();
const axis = (v) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(Math.round(v)));
const SEV_COLOR = { WARNING: LEVEL_COLOR[1], MAJOR: LEVEL_COLOR[2], CRITICAL: LEVEL_COLOR[3] };

function dur(sec) {
  if (sec == null) return "-";
  const s0 = Math.max(0, Math.floor(sec));
  const d = Math.floor(s0 / 86400), h = Math.floor((s0 % 86400) / 3600), m = Math.floor((s0 % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m ${String(s0 % 60).padStart(2, "0")}s`;
}

function useNow(ms = 1000) {
  const [n, setN] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setN(Date.now()), ms); return () => clearInterval(t); }, [ms]);
  return n;
}

/** Usage against normal: today vs yesterday with the normal range, or the last seven days. */
function UsageChart({ u, range }) {
  const W = 640, H = 210, L = 46, R = 10, T = 10, B = 26;
  const pw = W - L - R, ph = H - T - B;
  const accent = "var(--brand-blue)", bad = "var(--status-alarm)", muted = "var(--text-muted)";

  if (range === "week") {
    const mx = Math.max(...u.days.map((d) => d.total), u.average_prior_days || 0) * 1.12 || 1;
    const bw = pw / u.days.length;
    const ya = u.average_prior_days != null ? T + ph * (1 - u.average_prior_days / mx) : null;
    return (
      <svg className="ov-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${u.label} daily usage, last seven days`}>
        {[0, 0.5, 1].map((k) => <g key={k}><line x1={L} x2={W - R} y1={T + ph * (1 - k)} y2={T + ph * (1 - k)} stroke="rgba(var(--line-rgb), .12)" /><text x={L - 6} y={T + ph * (1 - k) + 4} textAnchor="end" fontSize="11" fill={muted}>{axis(mx * k)}</text></g>)}
        {u.days.map((d, i) => {
          const h = (ph * d.total) / mx, x = L + i * bw + bw * 0.18;
          return (
            <g key={d.date}>
              <rect x={x} y={T + ph - h} width={bw * 0.64} height={h} rx="3" fill={d.partial && u.issue ? bad : accent} opacity={d.partial ? 1 : 0.55} />
              <text x={x + bw * 0.32} y={H - 8} textAnchor="middle" fontSize="11" fill={muted}>{d.label}</text>
            </g>
          );
        })}
        {ya != null && <line x1={L} x2={W - R} y1={ya} y2={ya} stroke={muted} strokeWidth="1.2" strokeDasharray="4 3" />}
      </svg>
    );
  }

  const mx = Math.max(...u.today, ...u.yesterday, ...u.normal.map((b) => b.hi)) * 1.08 || 1;
  const X = (h) => L + (pw * h) / 23, Y = (v) => T + ph * (1 - v / mx);
  const line = (arr, from = 0) => arr.map((v, i) => `${i ? "L" : "M"}${X(i + from).toFixed(1)} ${Y(v).toFixed(1)}`).join("");
  const band = u.normal.map((b, h) => `${h ? "L" : "M"}${X(h).toFixed(1)} ${Y(b.hi).toFixed(1)}`).join("")
    + [...u.normal].reverse().map((b, i) => `L${X(23 - i).toFixed(1)} ${Y(b.lo).toFixed(1)}`).join("") + "Z";
  const runs = []; let run = [];
  u.today.forEach((v, h) => {
    const out = v > u.normal[h].hi || v < u.normal[h].lo;
    if (out) { if (!run.length && h > 0) run.push(h - 1); run.push(h); } else if (run.length) { runs.push(run); run = []; }
  });
  if (run.length) runs.push(run);
  const cur = u.today.length - 1;
  const nowBad = runs.length && runs[runs.length - 1].includes(cur);
  return (
    <svg className="ov-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${u.label} usage today against yesterday and the normal range`}>
      <path d={band} fill="var(--muted-fill)" />
      {[0, 0.25, 0.5, 0.75, 1].map((k) => <g key={k}><line x1={L} x2={W - R} y1={Y(mx * k)} y2={Y(mx * k)} stroke="rgba(var(--line-rgb), .1)" /><text x={L - 6} y={Y(mx * k) + 4} textAnchor="end" fontSize="11" fill={muted}>{axis(mx * k)}</text></g>)}
      {[0, 6, 12, 18, 23].map((h) => <text key={h} x={X(h)} y={H - 8} textAnchor="middle" fontSize="11" fill={muted}>{String(h).padStart(2, "0")}:00</text>)}
      <path d={line(u.yesterday)} fill="none" stroke={muted} strokeWidth="1.5" strokeDasharray="4 3" />
      <path d={line(u.today)} fill="none" stroke={accent} strokeWidth="2" />
      {runs.map((r, i) => <path key={i} d={line(u.today.slice(r[0], r[r.length - 1] + 1), r[0])} fill="none" stroke={bad} strokeWidth="2.6" />)}
      <line x1={X(cur)} x2={X(cur)} y1={T} y2={H - B} stroke="rgba(var(--line-rgb), .3)" strokeDasharray="2 3" />
      <text x={X(cur) + 5} y={T + 10} fontSize="11" fill={muted}>now</text>
      <circle cx={X(cur)} cy={Y(u.today[cur])} r="4" fill={nowBad ? bad : accent} />
    </svg>
  );
}

/** The reading behind an open issue against its limit, hour by hour today. Red where it is outside the limit. */
function SignalChart({ s }) {
  const W = 640, H = 150, L = 46, R = 10, T = 10, B = 22;
  const pw = W - L - R, ph = H - T - B;
  const lo = s.lo ?? Math.min(...s.points), hi = s.hi ?? Math.max(...s.points);
  const all = [...s.points, lo, hi];
  const pad = (Math.max(...all) - Math.min(...all)) * 0.14 || 1;
  const y0 = Math.min(...all) - pad, y1 = Math.max(...all) + pad;
  const X = (h) => L + (pw * h) / 23, Y = (v) => T + ph * (1 - (v - y0) / (y1 - y0));
  const out = (v) => (s.hi != null && v > s.hi) || (s.lo != null && v < s.lo);
  const line = (arr, from = 0) => arr.map((v, i) => `${i ? "L" : "M"}${X(i + from).toFixed(1)} ${Y(v).toFixed(1)}`).join("");
  const runs = []; let run = [];
  s.points.forEach((v, h) => {
    if (out(v)) { if (!run.length && h > 0) run.push(h - 1); run.push(h); } else if (run.length) { runs.push(run); run = []; }
  });
  if (run.length) runs.push(run);
  const cur = s.points.length - 1, bad = out(s.points[cur]);
  const muted = "var(--text-muted)";
  return (
    <svg className="ov-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${s.label} today against its limit`}>
      <rect x={L} y={Y(hi)} width={pw} height={Math.max(2, Y(lo) - Y(hi))} fill="var(--muted-fill)" />
      {[lo, hi].map((v, i) => (
        <g key={i}><line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} stroke="rgba(var(--line-rgb), .25)" strokeDasharray="3 3" /><text x={L - 6} y={Y(v) + 4} textAnchor="end" fontSize="11" fill={muted}>{Number(v.toFixed(1))}</text></g>
      ))}
      {[0, 6, 12, 18, 23].map((h) => <text key={h} x={X(h)} y={H - 6} textAnchor="middle" fontSize="11" fill={muted}>{String(h).padStart(2, "0")}:00</text>)}
      <path d={line(s.points)} fill="none" stroke="var(--brand-blue)" strokeWidth="2" />
      {runs.map((r, i) => <path key={i} d={line(s.points.slice(r[0], r[r.length - 1] + 1), r[0])} fill="none" stroke="var(--status-alarm)" strokeWidth="2.8" />)}
      <circle cx={X(cur)} cy={Y(s.points[cur])} r="4.5" fill={bad ? "var(--status-alarm)" : "var(--brand-blue)"} />
      <text x={Math.min(X(cur) + 8, W - 70)} y={Math.max(T + 10, Y(s.points[cur]) - 8)} fontSize="12" fontWeight="700" fill={bad ? "var(--status-alarm)" : muted}>{s.actual} {s.unit}</text>
    </svg>
  );
}

/**
 * Plant overview: the status of every utility right now, its usage against normal, and what needs attention.
 * Energy, production, maintenance and quality sit lower on the page, collapsed.
 */
export default function Monitoring({ onGo }) {
  const ov = useTwinPoll("/overview", 5000);
  const [sel, setSel] = useState(null);
  const [range, setRange] = useState("day");
  const utils = ov.data?.utilities || [];
  useEffect(() => {
    if (!sel && utils.length) setSel([...utils].sort((a, b) => b.level - a.level)[0].utility);
  }, [utils.length]);                                          // eslint-disable-line react-hooks/exhaustive-deps
  const us = useTwinPoll(sel ? `/usage?utility=${sel}` : null, 60_000, !!sel);
  const u = us.data && us.data.utility === sel ? us.data : null;

  const nowMs = useNow();
  const fetchedAt = useMemo(() => Date.now(), [ov.data]);      // eslint-disable-line react-hooks/exhaustive-deps
  const drift = (nowMs - fetchedAt) / 1000;

  const ctx = useCached("plant-summary-week", () => api.plantSummary(7, null), 60_000, { pollMs: 60_000 });
  const d = ctx.data && !ctx.data.empty ? ctx.data : null;

  return (
    <div className="page ov-page">
      <header className="page-head">
        <div>
          <h2>Plant overview</h2>
          <p className="muted">Status of every utility now, usage against normal, and what needs attention.</p>
        </div>
      </header>

      <section className="ov-strip" aria-label="Utility status">
        {utils.length === 0 && <p className="muted">Reading the plant…</p>}
        {utils.map((x) => (
          <button type="button" key={x.utility} className="ov-ut" aria-pressed={sel === x.utility} onClick={() => setSel(x.utility)}>
            <b><i className="ov-dot" style={{ background: LEVEL_COLOR[x.level] }} />{x.label}</b>
            <span className="rd">{x.reading}</span>
            <span className="sub">{x.open_issues ? x.reading_label : "All normal"}</span>
            {x.open_issues > 0 && <span className="iss" style={{ color: LEVEL_COLOR[x.level] === LEVEL_COLOR[1] ? "var(--text-secondary)" : LEVEL_COLOR[x.level] }}>{x.open_issues} open issue{x.open_issues > 1 ? "s" : ""} · {LEVELS[x.level]}</span>}
          </button>
        ))}
      </section>

      <div className="ov-grid">
        <section className="card ov-card" aria-label="Usage">
          <div className="ov-top">
            <h3>{u ? `${u.label}: ${u.what.toLowerCase()}` : "Usage"}<span className="ov-chip">Mock usage data</span></h3>
            <div className="ov-seg" role="group" aria-label="Range">
              <button type="button" aria-pressed={range === "day"} onClick={() => setRange("day")}>Today</button>
              <button type="button" aria-pressed={range === "week"} onClick={() => setRange("week")}>Last 7 days</button>
            </div>
          </div>
          {!u && <p className="muted">{us.error || "Loading usage…"}</p>}
          {u && (
            <>
              <div className="ov-nums">
                <div><b>{u.vs_yesterday_pct == null ? "-" : `${u.vs_yesterday_pct > 0 ? "+" : ""}${Math.round(u.vs_yesterday_pct)}%`}</b><span>vs the same time yesterday</span></div>
                <div><b>{u.peak_hour == null ? "-" : `${String(u.peak_hour).padStart(2, "0")}:00`}</b><span>peak so far today ({u.unit})</span></div>
                <div><b>{u.energy ? `INR ${fmt(u.energy.cost_inr, 0)}` : "Not metered"}</b><span>{u.energy ? `${fmt(u.energy.kwh, 0)} kWh energy today (estimate)` : "no electricity meter on this utility"}</span></div>
              </div>
              <UsageChart u={u} range={range} />
              <div className="ov-legend" aria-hidden="true">
                {range === "day" ? (
                  <>
                    <span><i style={{ borderColor: "var(--brand-blue)" }} />Today</span>
                    <span><i style={{ borderColor: "var(--text-muted)", borderTopStyle: "dashed" }} />Yesterday</span>
                    <span><i style={{ borderColor: "var(--muted-fill)", borderTopWidth: 8 }} />Normal range</span>
                    <span><i style={{ borderColor: "var(--status-alarm)" }} />Outside normal</span>
                  </>
                ) : (
                  <>
                    <span><i style={{ borderColor: "var(--brand-blue)" }} />Daily total ({u.unit} added up); today is so far</span>
                    <span><i style={{ borderColor: "var(--text-muted)", borderTopStyle: "dashed" }} />Average of the previous days</span>
                  </>
                )}
              </div>
              {u.signal && (
                <>
                  <p className="ov-signal-title"><b>{u.signal.label}</b>{u.signal.label.includes(u.signal.unit) ? "" : ` (${u.signal.unit})`} against its limit of {u.signal.expected}</p>
                  <SignalChart s={u.signal} />
                </>
              )}
              <p className={`ov-note${u.issue ? " bad" : ""}`}>
                {u.note}
                {u.issue && onGo && <button type="button" className="btn ghost xs" onClick={() => onGo("issues")}>Open Issues</button>}
              </p>
            </>
          )}
        </section>

        <section className="card ov-card" aria-label="Needs attention">
          <div className="ov-top">
            <h3>Needs attention</h3>
            {onGo && <button type="button" className="btn ghost xs" onClick={() => onGo("issues")}>All issues</button>}
          </div>
          {ov.data && ov.data.attention.length === 0 && <p className="muted">Nothing needs attention. Every utility is within its limits.</p>}
          <ul className="ov-att">
            {(ov.data?.attention || []).map((a) => {
              const age = (a.age_s ?? 0) + drift;
              return (
                <li key={a.id}>
                  <span className="bar" style={{ background: SEV_COLOR[a.severity] || LEVEL_COLOR[1] }} />
                  <span><b>{a.title}</b><small>{a.zone}{a.who ? ` · ${a.who}` : ""}</small></span>
                  <time className={a.needs_attention ? "late" : ""}>{dur(age)}</time>
                </li>
              );
            })}
          </ul>
        </section>
      </div>

      <details className="card ov-context">
        <summary>Energy, production, maintenance and quality <small>plant context from the last 7 days</small></summary>
        {!d ? <p className="muted" style={{ padding: 16 }}>{ctx.error ? "The database did not answer just now." : "Reading the database…"}</p> : (
          <div className="mon-row mon-four">
            <section className="card mon-card" aria-label="Energy">
              <h3>Energy</h3>
              <div className="mon-kv"><span>Electricity</span><b>{fmt(d.energy.total_kwh, 0)} kWh</b></div>
              <div className="mon-kv"><span>Cost</span><b>INR {fmt(d.energy.total_cost_inr, 0)}</b></div>
              {d.energy.kwh_per_good_unit.map((x) => (
                <div key={x.plant_id} className="mon-kv"><span className="mon-ellipsis">{x.plant_name}</span><b>{x.kwh_per_good_unit} kWh/unit</b></div>
              ))}
            </section>
            <section className="card mon-card" aria-label="Production">
              <h3>Production</h3>
              {Object.entries(d.production.lines.reduce((acc, l) => {
                const p = acc[l.plant_id] || { name: l.plant_name, good: 0, actual: 0 };
                p.good += l.good || 0; p.actual += l.actual || 0; acc[l.plant_id] = p; return acc;
              }, {})).map(([id, p]) => (
                <div key={id} className="mon-kv"><span className="mon-ellipsis">{p.name}</span><b>{p.actual ? `${fmt((100 * p.good) / p.actual, 1)}% yield` : "-"}</b></div>
              ))}
              <div className="mon-kv"><span>Top downtime</span><b>{d.production.downtime_reasons[0] ? label(d.production.downtime_reasons[0].reason) : "-"}</b></div>
            </section>
            <section className="card mon-card" aria-label="Maintenance">
              <h3>Maintenance</h3>
              <div className="mon-kv"><span>Planned</span><b>{fmt(d.maintenance.orders_by_status?.PLANNED || 0, 0)}</b></div>
              <div className="mon-kv"><span>In progress</span><b>{fmt(d.maintenance.orders_by_status?.IN_PROGRESS || 0, 0)}</b></div>
              <div className="mon-kv"><span>Completed</span><b>{fmt(d.maintenance.orders_by_status?.COMPLETED || 0, 0)}</b></div>
              <div className={`mon-kv${d.maintenance.overdue_service.length ? " warn-text" : ""}`}><span>Services overdue</span><b>{fmt(d.maintenance.overdue_service.length, 0)}</b></div>
            </section>
            <section className="card mon-card" aria-label="Quality">
              <h3>Quality</h3>
              {d.quality.by_plant.map((x) => (
                <div key={x.plant_id} className="mon-kv"><span className="mon-ellipsis">{x.plant_name}</span><b>{pct(x.pass_rate_pct)} pass</b></div>
              ))}
              <div className="mon-kv"><span>Top defect</span><b>{d.quality.top_defects[0] ? d.quality.top_defects[0].defect_code : "-"}</b></div>
              <div className={`mon-kv${d.quality.capa_overdue ? " warn-text" : ""}`}><span>Quality actions overdue</span><b>{fmt(d.quality.capa_overdue, 0)}</b></div>
            </section>
          </div>
        )}
      </details>
    </div>
  );
}
