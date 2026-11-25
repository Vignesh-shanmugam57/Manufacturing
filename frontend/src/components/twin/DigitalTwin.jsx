import { useEffect, useMemo, useRef, useState } from "react";
import { twinApi } from "../../api/client.js";
import { IconRefresh, Spinner } from "../icons.jsx";
import EquipmentPanel from "./EquipmentPanel.jsx";
import FactoryScene from "./FactoryScene.jsx";
import LiveResponse from "./LiveResponse.jsx";
import { UTILITIES, UTILITY_COLOR, UTILITY_LABEL, timeAgoShort } from "./labels.js";
import { SAMPLE_ALARMS } from "./sampleAlarms.js";
import { LevelPill, SeverityPill, SimBadge } from "./ui.jsx";
import { LEVELS, LEVEL_COLOR, SEVERITY_LEVEL, useTwin, useTwinResource } from "../../lib/twin.js";

const SCENARIO_PHASE = { ramping: "fault developing", active: "fault active", recovering: "recovering after corrective action" };

// the panels that float over the 3D plant; each can be closed and reopened, and the choice is remembered
const PANELS = [["systems", "Systems"], ["response", "Response"], ["labels", "Labels"], ["demo", "Demo"], ["tickets", "Tickets"]];
const ALL_OPEN = Object.fromEntries(PANELS.map(([k]) => [k, true]));
const loadPanels = () => { try { return { ...ALL_OPEN, ...JSON.parse(localStorage.getItem("mapPanels") || "{}") }; } catch { return ALL_OPEN; } };

/** The 3D plant: filter by utility, inspect equipment, watch alarms, and run the demonstration scenarios. */
export default function DigitalTwin({ focusId = null }) {
  const catalog = useTwin((s) => s.catalog);
  const levels = useTwin((s) => s.snap?.levels);
  const scenario = useTwin((s) => s.snap?.scenario);
  const mode = useTwin((s) => s.snap?.mode);
  const [selected, setSelected] = useState(null);
  const [utility, setUtility] = useState(null);
  const [flows, setFlows] = useState(true);
  const [pick, setPick] = useState("compressed_air_leak");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const apiRef = useRef(null);
  const [show, setShow] = useState(loadPanels);
  const [full, setFull] = useState(false);
  const [closedLabels, setClosedLabels] = useState(0);
  const toggle = (key, on = !show[key]) => {
    setShow((s) => ({ ...s, [key]: on }));
    if (key === "labels" && on) apiRef.current?.restoreLabels();
  };
  useEffect(() => { try { localStorage.setItem("mapPanels", JSON.stringify(show)); } catch { /* private browsing */ } }, [show]);
  useEffect(() => {
    if (!full) return undefined;
    const esc = (e) => { if (e.key === "Escape") setFull(false); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [full]);
  const alertsRes = useTwinResource("/alerts?status=active");
  const active = alertsRes.data?.alerts || [];

  const rail = useMemo(() => UTILITIES.map((u) => {
    const eqs = (catalog?.equipment || []).filter((e) => e.utility === u);
    const live = Math.max(0, ...eqs.map((e) => (levels?.[e.id] === 4 ? 0 : levels?.[e.id] ?? 0)));
    const open = Math.max(0, ...active.filter((a) => a.utility === u).map((a) => SEVERITY_LEVEL[a.severity] ?? 1));
    const worst = Math.max(live, open);
    return { id: u, worst, alarms: active.filter((a) => a.utility === u).length };
  }), [catalog, levels, active]);

  async function demo(kind) {
    setBusy(kind); setErr("");
    try {
      if (kind === "start") await twinApi.post("/scenarios/start", { name: pick, intensity: 1 });
      else if (kind === "fix") await twinApi.post("/scenarios/fix");
      else await twinApi.post("/scenarios/reset");
      if (kind === "reset") setSelected(null);
    } catch (e) { setErr(e.message); } finally { setBusy(""); }
  }

  const select = (id) => { setSelected(id); if (id) apiRef.current?.setSelected(id); };

  // opened from an issue: fly to that equipment as soon as the 3D scene is ready
  useEffect(() => {
    if (!focusId) return undefined;
    let tries = 0;
    const t = setInterval(() => {
      tries += 1;
      if (apiRef.current) { setSelected(focusId); apiRef.current.setSelected(focusId); apiRef.current.focus(focusId); clearInterval(t); }
      else if (tries > 40) clearInterval(t);
    }, 250);
    return () => clearInterval(t);
  }, [focusId]);

  return (
    <div className={`twin-page${show.tickets ? " side-open" : ""}${full ? " full" : ""}`}>
      <div className="twin-main">
      {show.systems && (
      <nav className="twin-rail" aria-label="Utility systems">
        <div className="hud-head"><h3>Systems</h3><button type="button" className="hud-x" onClick={() => toggle("systems", false)} aria-label="Close systems panel">×</button></div>
        <button className={`rail-item${!utility ? " on" : ""}`} onClick={() => setUtility(null)}>
          <span className="rail-dot all" /> Full factory
        </button>
        {rail.map((r) => (
          <button key={r.id} className={`rail-item${utility === r.id ? " on" : ""}`} onClick={() => setUtility(utility === r.id ? null : r.id)} aria-pressed={utility === r.id}>
            <span className="rail-dot" style={{ background: UTILITY_COLOR[r.id] }} />
            <span className="rail-name">{UTILITY_LABEL[r.id]}</span>
            {r.alarms > 0
              ? <span className="rail-count" style={{ background: LEVEL_COLOR[r.worst] }} title={`${r.alarms} open, worst ${LEVELS[r.worst]}`}>{r.alarms}</span>
              : <i className={`ldot lv-${r.worst}`} title={LEVELS[r.worst]} />}
          </button>
        ))}
        <div className="legend" aria-label="Status colours">
          {[0, 1, 2, 3, 4].map((l) => <span key={l}><i style={{ background: LEVEL_COLOR[l] }} />{LEVELS[l]}</span>)}
        </div>
      </nav>
      )}

      <section className="twin-stage" aria-label="3D factory">
        <FactoryScene selectedId={selected} onSelect={select} utility={utility} flows={flows} alerts={active} apiRef={apiRef} labels={show.labels} onLabelsClosed={setClosedLabels} inset={show.tickets ? 350 : 0} />
        <div className="stage-top">
          <SimBadge />
          <div className="stage-tools">
            <div className="hud-toggles" role="group" aria-label="Show or hide panels">
              {PANELS.map(([key, label]) => (
                <button key={key} type="button" className={`btn ghost xs${show[key] ? " pressed" : ""}`} aria-pressed={show[key]} onClick={() => toggle(key)}>
                  {label}{key === "tickets" && active.length > 0 ? ` (${active.length})` : ""}
                </button>
              ))}
            </div>
            {show.labels && closedLabels > 0 && <button type="button" className="btn ghost xs" onClick={() => apiRef.current?.restoreLabels()}>Reopen closed labels ({closedLabels})</button>}
            <button type="button" className={`btn ghost xs${full ? " pressed" : ""}`} aria-pressed={full} onClick={() => setFull((f) => !f)}>{full ? "Exit full screen (Esc)" : "Full screen"}</button>
            <button className="btn ghost xs" onClick={() => apiRef.current?.resetCamera()}><IconRefresh width={13} height={13} /> Reset view</button>
            <button className={`btn ghost xs${flows ? " pressed" : ""}`} aria-pressed={flows} onClick={() => setFlows((f) => !f)}>Flow animation {flows ? "on" : "off"}</button>
          </div>
        </div>

        <div className="stage-dock">
        <LiveResponse equipmentId={selected} apiRef={apiRef} hidden={!show.response} onClose={() => toggle("response", false)} />

        {mode === "simulation" && show.demo && (
          <div className="demo-bar" aria-label="Demonstration controls">
            <span className="demo-tag">DEMO</span>
            <select value={pick} onChange={(e) => setPick(e.target.value)} disabled={!!scenario?.active} aria-label="Fault to simulate">
              {(catalog?.scenarios || []).map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
            </select>
            <button className="btn primary xs" onClick={() => demo("start")} disabled={!!busy || !!scenario?.active}>
              {busy === "start" ? <Spinner size={12} /> : null} Inject fault
            </button>
            <button className="btn ghost xs" onClick={() => demo("fix")} disabled={!!busy || !scenario?.active || scenario.phase === "recovering"}>
              {busy === "fix" ? <Spinner size={12} /> : null} Simulate corrective action
            </button>
            <button className="btn ghost xs" onClick={() => demo("reset")} disabled={!!busy}>
              {busy === "reset" ? <Spinner size={12} /> : null} Reset demo
            </button>
            <span className="demo-state" role="status">
              {scenario?.active ? `${scenario.title}: ${SCENARIO_PHASE[scenario.phase] || scenario.phase}` : "Normal operation"}
            </span>
            {err && <span className="form-error">{err}</span>}
            <button type="button" className="hud-x" onClick={() => toggle("demo", false)} aria-label="Close demo controls">×</button>
          </div>
        )}
        </div>
      </section>
      </div>

      {show.tickets && (
      <aside className="twin-side">
        <button type="button" className="side-hide" onClick={() => toggle("tickets", false)}>Close panel ×</button>
        {selected ? (
          <EquipmentPanel id={selected} onClose={() => select(null)} onFocus={(id) => apiRef.current?.focus(id)} />
        ) : (
          <div className="side-alarms">
            <h3>Active alarms</h3>
            {alertsRes.data == null ? (
              <p className="muted small">{alertsRes.error ? `Live alarms unavailable: ${alertsRes.error}` : "Loading live alarms…"}</p>
            ) : active.length === 0 ? (
              <p className="muted small">No live alarms. All monitored equipment is within its engineering limits.</p>
            ) : (
              <ul className="alarm-list">
                {active.map((a) => (
                  <li key={a.id}>
                    <button className="alarm-card" onClick={() => { select(a.equipment_id); apiRef.current?.focus(a.equipment_id); }}>
                      <span className="alarm-top"><SeverityPill severity={a.severity} /><span className="small muted">{a.code} · {timeAgoShort(a.created_at)}</span></span>
                      <strong>{a.title}</strong>
                      <span className="small">Reading <b>{a.actual}</b> · expected {a.expected}</span>
                      <span className="small muted">{a.recommendation}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <section className="sample-alarms" aria-labelledby="sample-alarms-title">
              <div className="sample-head"><h4 id="sample-alarms-title">Sample alarms</h4><span className="sample-tag">Sample</span></div>
              <p className="small muted">Static examples for demonstration. They are not plant readings and are not live alerts.</p>
              <ul className="alarm-list">
                {SAMPLE_ALARMS.map((s) => (
                  <li key={s.code}>
                    <article className="sample-alarm" aria-label={`Sample alarm: ${s.title}`}>
                      <span className="alarm-top"><SeverityPill severity={s.severity} /><span className="small muted">{s.code}</span></span>
                      <strong>{s.title}</strong>
                      <span className="small">{s.equipment}: reading <b>{s.actual}</b> · expected {s.expected}</span>
                      <span className="small muted">{s.recommendation}</span>
                    </article>
                  </li>
                ))}
              </ul>
            </section>
            <p className="small muted">Click equipment in the 3D view to see its readings, trends, alarms and maintenance.</p>
          </div>
        )}
      </aside>
      )}
      {!show.tickets && (
        <button type="button" className="side-tab" onClick={() => toggle("tickets", true)}>Tickets{active.length > 0 ? ` (${active.length})` : ""}</button>
      )}
    </div>
  );
}
