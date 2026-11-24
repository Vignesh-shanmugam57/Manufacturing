import { api } from "../../api/client.js";
import { useCached } from "../../hooks/useCached.js";
import { formatDateTime } from "../../lib/format.js";
import { fmt } from "../../lib/twin.js";
import { Metric } from "./ui.jsx";

const STATUS_ORDER = ["PLANNED", "IN_PROGRESS", "COMPLETED"];
const STATUS_TEXT = { PLANNED: "Planned", IN_PROGRESS: "In progress", COMPLETED: "Completed" };

/** Plant operations from the database: energy and cost, production and downtime, maintenance, quality and assets. */
export default function PlantData({ days = 30 }) {
  const q = useCached(`plant-summary-${days}`, () => api.plantSummary(days), 60_000, { pollMs: 60_000 });
  const d = q.data;

  if (!d) {
    return (
      <section className="card tcard" aria-label="Plant operations">
        <h3>Plant operations</h3>
        {q.error ? (
          <>
            <p className="form-error" role="alert">The database did not answer just now. {q.error}</p>
            <button className="btn primary xs" onClick={() => q.reload()}>Try again</button>
          </>
        ) : <div className="skel skel-block" />}
      </section>
    );
  }
  if (d.empty) {
    return (
      <section className="card tcard" aria-label="Plant operations">
        <h3>Plant operations</h3>
        <p className="muted">{d.message}</p>
      </section>
    );
  }

  const e = d.energy, p = d.production, m = d.maintenance, qu = d.quality;
  const byStatus = m.orders_by_status || {};

  return (
    <div className="plant-data" aria-label="Plant operations">
      <header className="tcard-head">
        <div>
          <h2>Plant operations</h2>
          <p className="small muted">Last {d.days} days up to {formatDateTime(d.as_of)}. Every number is read from the database.</p>
        </div>
      </header>

      <section className="card tcard" aria-label="Energy and cost">
        <header className="tcard-head"><div><h3>Energy and cost</h3><p className="small muted">Electricity per meter area. Compressor, chiller and HVAC are the utilities themselves.</p></div></header>
        <div className="tmetrics sm">
          <Metric label="Electricity" value={fmt(e.total_kwh, 0)} unit=" kWh" caption={`last ${d.days} days`} />
          <Metric label="Electricity cost" value={`INR ${fmt(e.total_cost_inr, 0)}`} caption="at the meter tariffs" />
          <Metric label="CO2e" value={fmt(e.total_co2e_kg, 0)} unit=" kg" caption="from the meters" />
        </div>
        <div className="ttable-wrap">
          <table className="ttable">
            <thead><tr><th>Plant</th><th>Area</th><th>Utility</th><th className="num">kWh</th><th className="num">Cost (INR)</th><th className="num">CO2e (kg)</th></tr></thead>
            <tbody>
              {e.by_area.map((x) => (
                <tr key={`${x.plant_id}-${x.area}`}>
                  <td>{x.plant_name}</td><td>{x.area}</td><td>{x.utility ? "Yes" : "-"}</td>
                  <td className="num">{fmt(x.kwh, 0)}</td><td className="num">{fmt(x.cost_inr, 0)}</td><td className="num">{fmt(x.co2e_kg, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {e.kwh_per_good_unit.length > 0 && (
          <ul className="res-list" aria-label="Consumption per good unit">
            {e.kwh_per_good_unit.map((x) => (
              <li key={x.plant_id}>
                <strong>{x.kwh_per_good_unit} kWh per good unit</strong>
                <span className="small muted">{x.plant_name}: {fmt(x.kwh, 0)} kWh for {fmt(x.good_units, 0)} good units</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card tcard" aria-label="Production and downtime">
        <header className="tcard-head"><div><h3>Production and downtime</h3><p className="small muted">Output per line, and why the lines stopped.</p></div></header>
        <div className="ttable-wrap">
          <table className="ttable">
            <thead><tr><th>Plant</th><th>Line</th><th className="num">Target</th><th className="num">Actual</th><th className="num">Good</th><th className="num">Reject</th><th className="num">Yield</th><th className="num">Downtime (min)</th></tr></thead>
            <tbody>
              {p.lines.map((x) => (
                <tr key={`${x.plant_id}-${x.line_id}`}>
                  <td>{x.plant_name}</td><td>{x.line_id} {x.line_type && <span className="muted small">({x.line_type})</span>}</td>
                  <td className="num">{fmt(x.target, 0)}</td><td className="num">{fmt(x.actual, 0)}</td><td className="num">{fmt(x.good, 0)}</td>
                  <td className="num">{fmt(x.reject, 0)}</td><td className="num">{x.yield_pct == null ? "-" : `${fmt(x.yield_pct, 1)}%`}</td>
                  <td className="num">{fmt(x.downtime_min, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <h4>Downtime reasons</h4>
          {p.downtime_reasons.length === 0 ? <p className="small muted">No downtime with a reason in this window.</p> : (
            <ul className="res-list">
              {p.downtime_reasons.map((x) => (
                <li key={x.reason}><strong>{x.reason.replace(/_/g, " ").toLowerCase()}</strong><span className="small muted">{fmt(x.minutes, 0)} min in {x.events} events</span></li>
              ))}
            </ul>
          )}
        </div>
      </section>

      <section className="card tcard" aria-label="Maintenance">
        <header className="tcard-head"><div><h3>Maintenance (CMMS)</h3><p className="small muted">Work orders, and each machine against its planned service interval.</p></div></header>
        <div className="tmetrics sm">
          {STATUS_ORDER.map((s) => <Metric key={s} label={STATUS_TEXT[s]} value={fmt(byStatus[s] ?? 0, 0)} unit=" orders" caption="work orders" />)}
          <Metric label="Downtime avoided" value={fmt(m.downtime_avoided_min, 0)} unit=" min" caption="estimated, completed orders" />
        </div>
        <div className="ttable-wrap">
          <table className="ttable">
            <thead><tr><th>Machine</th><th>Line</th><th>Criticality</th><th className="num">Interval (days)</th><th>Last completed</th><th>Next due</th><th className="num">Open orders</th></tr></thead>
            <tbody>
              {m.register.map((x) => {
                const overdue = m.overdue_service.some((o) => o.machine_id === x.machine_id);
                return (
                  <tr key={x.machine_id} className={overdue ? "warn-row" : ""}>
                    <td>{x.machine_name} <span className="muted small">{x.machine_id}</span></td><td>{x.line_id}</td><td>{x.criticality}</td>
                    <td className="num">{x.interval_days ?? "-"}</td>
                    <td>{x.last_completed ? x.last_completed.replace("T", " ") : "never in data"}</td>
                    <td>{overdue ? <span className="warn-text">Overdue</span> : (x.next_due ? x.next_due.replace("T", " ") : "-")}</td>
                    <td className="num">{x.open_orders}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div>
          <h4>Most common failure modes</h4>
          <ul className="res-list">
            {m.top_failure_modes.map((x) => (
              <li key={x.failure_mode}><strong>{x.failure_mode.replace(/_/g, " ").toLowerCase()}</strong><span className="small muted">{x.orders} work orders</span></li>
            ))}
          </ul>
        </div>
      </section>

      <section className="card tcard" aria-label="Quality and defects">
        <header className="tcard-head"><div><h3>Quality and defects</h3><p className="small muted">Pass rate per plant, the most common defects, and corrective actions still due.</p></div></header>
        <div className="ttable-wrap">
          <table className="ttable">
            <thead><tr><th>Plant</th><th className="num">Inspections</th><th className="num">Pass</th><th className="num">Pass rate</th></tr></thead>
            <tbody>
              {qu.by_plant.map((x) => (
                <tr key={x.plant_id}><td>{x.plant_name}</td><td className="num">{fmt(x.inspections, 0)}</td><td className="num">{fmt(x.pass, 0)}</td><td className="num">{x.pass_rate_pct == null ? "-" : `${fmt(x.pass_rate_pct, 1)}%`}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="res-stack">
          <div>
            <h4>Most common defects (fails)</h4>
            <ul className="res-list">
              {qu.top_defects.map((x) => <li key={x.defect_code}><strong>{x.defect_code}</strong><span className="small muted">{fmt(x.fails, 0)} failed inspections</span></li>)}
            </ul>
          </div>
          <div>
            <h4>Corrective actions (CAPA)</h4>
            <p className="small">
              {Object.entries(qu.ncr_by_status).map(([k, v]) => `${k.replace(/_/g, " ").toLowerCase()}: ${fmt(v, 0)}`).join(" · ")}
            </p>
            <p className={qu.capa_overdue ? "warn-text" : "small muted"}>{fmt(qu.capa_overdue, 0)} past their due date and not yet closed</p>
          </div>
        </div>
      </section>
    </div>
  );
}
