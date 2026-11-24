import { useMemo, useState } from "react";
import { twinApi } from "../../api/client.js";
import { Spinner } from "../icons.jsx";
import DataPanel from "../DataPanel.jsx";
import { UTILITY_LABEL } from "./labels.js";
import { PageHead } from "./ui.jsx";
import { fmt, useTwin, useTwinResource } from "../../lib/twin.js";

const BANDS = [["normal", "Normal"], ["warn", "Warning limit"], ["crit", "Critical limit"]];
const num = (v) => (v === "" || v == null ? null : Number(v));

function LimitRow({ s, onSaved }) {
  const [edit, setEdit] = useState(false);
  const [vals, setVals] = useState({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const show = (b) => (b ? `${b[0] ?? "−∞"} … ${b[1] ?? "∞"}` : "-");

  async function save() {
    setBusy(true); setErr("");
    try {
      for (const [band] of BANDS) {
        const lo = num(vals[`${band}.lo`]), hi = num(vals[`${band}.hi`]);
        const cur = s.limits[band];
        if (lo !== (cur?.[0] ?? null) || hi !== (cur?.[1] ?? null)) await twinApi.put("/limits", { tag: s.tag, band, lo, hi });
      }
      setEdit(false); await onSaved();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }
  const start = () => { setEdit(true); setErr(""); setVals(Object.fromEntries(BANDS.flatMap(([b]) => [[`${b}.lo`, s.limits[b]?.[0] ?? ""], [`${b}.hi`, s.limits[b]?.[1] ?? ""]]))); };

  return (
    <>
      <tr>
        <td><b>{s.equipment}</b><br /><span className="muted small">{s.label}</span></td>
        <td>{UTILITY_LABEL[s.utility]}</td>
        {BANDS.map(([b]) => <td key={b} className="num small">{show(s.limits[b])} {s.unit}</td>)}
        <td>{s.overridden && <span className="tag warn">changed</span>}<button className="btn ghost xs" onClick={edit ? () => setEdit(false) : start}>{edit ? "Cancel" : "Edit"}</button></td>
      </tr>
      {edit && (
        <tr className="editrow"><td colSpan={6}>
          <div className="limedit">
            {BANDS.map(([b, label]) => (
              <fieldset key={b}><legend>{label}</legend>
                <input type="number" step="any" value={vals[`${b}.lo`] ?? ""} onChange={(e) => setVals({ ...vals, [`${b}.lo`]: e.target.value })} aria-label={`${label} lower`} placeholder="lower" />
                <input type="number" step="any" value={vals[`${b}.hi`] ?? ""} onChange={(e) => setVals({ ...vals, [`${b}.hi`]: e.target.value })} aria-label={`${label} upper`} placeholder="upper" />
              </fieldset>
            ))}
            <button className="btn primary xs" onClick={save} disabled={busy}>{busy && <Spinner size={12} />} Save limits</button>
            {err && <span className="form-error">{err}</span>}
          </div>
        </td></tr>
      )}
    </>
  );
}

/** Demonstration controls, engineering limits, tariffs and the notification rules. */
export default function Config({ onDataChanged }) {
  const settings = useTwinResource("/settings");
  const limits = useTwinResource("/limits");
  const catalog = useTwin((s) => s.catalog);
  const scenario = useTwin((s) => s.snap?.scenario);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [pick, setPick] = useState("compressed_air_leak");
  const [tariffs, setTariffs] = useState(null);
  const s = settings.data;
  const t = tariffs || s?.tariffs;
  const rows = useMemo(() => (limits.data?.sensors || []).filter((x) => !q || `${x.equipment} ${x.label} ${x.tag}`.toLowerCase().includes(q.toLowerCase())), [limits.data, q]);

  async function act(name, fn) {
    setBusy(name); setMsg("");
    try { const r = await fn(); setMsg(typeof r === "string" ? r : ""); await settings.reload(); } catch (e) { setMsg(e.message); } finally { setBusy(""); }
  }

  return (
    <div className="page tpage">
      <PageHead title="Configuration and engineering limits" sub="Data upload, the demonstration controls, the limits every reading is checked against, and the cost and notification rules." />
      {msg && <div className="banner" role="status">{msg}</div>}

      <DataPanel embedded onDataChanged={onDataChanged} />

      <section className="card tcard">
        <header className="tcard-head"><div><h3>Demonstration</h3><p className="small muted">Inject a simulated fault, then watch the agent detect, analyse, alert and verify recovery. Reset removes every simulated alert, task and audit record.</p></div></header>
        <div className="tfilters inline">
          <select value={pick} onChange={(e) => setPick(e.target.value)} aria-label="Fault">{(catalog?.scenarios || []).map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}</select>
          <button className="btn primary xs" disabled={!!busy || !!scenario?.active || s?.mode !== "simulation"} onClick={() => act("start", () => twinApi.post("/scenarios/start", { name: pick }).then(() => "Fault injected."))}>Inject fault</button>
          <button className="btn ghost xs" disabled={!!busy || !scenario?.active} onClick={() => act("fix", () => twinApi.post("/scenarios/fix").then(() => "Simulated corrective action: telemetry is returning to normal."))}>Simulate corrective action</button>
          <button className="btn ghost xs" disabled={!!busy} onClick={() => act("reset", () => twinApi.post("/scenarios/reset").then((r) => `Demo reset: ${r.alerts_deleted} simulated alert(s) removed.`))}>Reset demo</button>
          <span className="small muted">{scenario?.active ? `${scenario.title} (${scenario.phase})` : "Normal operation"}</span>
        </div>
        <p className="small muted">{(catalog?.scenarios || []).find((x) => x.id === pick)?.text}</p>
      </section>

      <section className="card tcard">
        <header className="tcard-head"><div><h3>Engineering limits</h3><p className="small muted">A reading is Normal inside the normal band, Warning inside the warning limit, Major inside the critical limit and Critical beyond it. These are DEMO limits: replace them with site-engineered values. Every change is logged.</p></div>
          <input type="search" placeholder="Search sensor" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search sensors" /></header>
        <div className="ttable-wrap limits"><table className="ttable">
          <thead><tr><th>Sensor</th><th>Utility</th><th>Normal</th><th>Warning limit</th><th>Critical limit</th><th /></tr></thead>
          <tbody>{rows.map((x) => <LimitRow key={x.tag} s={x} onSaved={limits.reload} />)}</tbody>
        </table></div>
      </section>

      <div className="tgrid2">
        <section className="card tcard">
          <header className="tcard-head"><div><h3>Tariffs (DEMO)</h3><p className="small muted">Used for the cost indicator only.</p></div></header>
          {t && (
            <form className="tariffs" onSubmit={(e) => { e.preventDefault(); act("tariffs", () => twinApi.put("/settings/tariffs", { electricity: Number(t.electricity), gas: Number(t.gas), water: Number(t.water) }).then(() => "Tariffs saved.")); }}>
              {[["electricity", "Electricity per kWh"], ["gas", "Gas per Nm3"], ["water", "Water per m3"]].map(([k, label]) => (
                <label key={k} className="field"><span>{label} ({t.currency})</span><input type="number" step="0.01" min="0" value={t[k]} onChange={(e) => setTariffs({ ...t, [k]: e.target.value })} /></label>
              ))}
              <button className="btn primary xs" disabled={!!busy}>{busy === "tariffs" && <Spinner size={12} />} Save tariffs</button>
            </form>
          )}
        </section>
        <section className="card tcard">
          <header className="tcard-head"><div><h3>Notification and escalation rules</h3><p className="small muted">In-app notifications. Every notification is stored and audited.</p></div></header>
          <dl className="rules">
            {Object.entries(s?.notification_roles || {}).map(([sev, roles]) => <div key={sev}><dt>{sev === "gas" ? "Gas safety alarms" : sev[0] + sev.slice(1).toLowerCase()}</dt><dd>{roles.join(", ").replace(/_/g, " ")}</dd></div>)}
            {Object.entries(s?.escalation || {}).map(([sev, text]) => <div key={sev}><dt>Escalation, {sev.toLowerCase()}</dt><dd>{text}</dd></div>)}
          </dl>
        </section>
      </div>

      <section className="card tcard safety">
        <header className="tcard-head"><h3>Safety and autonomy</h3></header>
        <p>The agent may <b>monitor, analyse, detect, predict, recommend, alert, track maintenance and verify</b> a return to normal. It has <b>no</b> function that changes setpoints, operates valves, starts or stops pumps, edits PLC logic or overrides an interlock, and the API contains no such endpoint. Any intervention stays with certified, authorised operators under approved site procedures. "Simulate corrective action" only moves simulated telemetry in demo mode.</p>
      </section>
    </div>
  );
}
