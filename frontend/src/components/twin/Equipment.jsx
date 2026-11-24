import { useMemo, useState } from "react";
import EquipmentPanel from "./EquipmentPanel.jsx";
import { UTILITIES, UTILITY_LABEL } from "./labels.js";
import { LevelPill, PageHead } from "./ui.jsx";
import { LEVELS, fmt, sensorFmt, useTwin, useTwinPoll } from "../../lib/twin.js";

/** The equipment master: every asset with live status, a key reading, runtime and maintenance dates. */
export default function Equipment() {
  const catalog = useTwin((s) => s.catalog);
  const levels = useTwin((s) => s.snap?.levels);
  const values = useTwin((s) => s.snap?.values);
  const { data } = useTwinPoll("/equipment", 3000);
  const [q, setQ] = useState("");
  const [utility, setUtility] = useState("");
  const [status, setStatus] = useState("");
  const [inspect, setInspect] = useState(null);

  const extra = useMemo(() => Object.fromEntries((data?.equipment || []).map((e) => [e.id, e])), [data]);
  const rows = (catalog?.equipment || []).filter((e) => {
    const lv = levels?.[e.id] ?? 0;
    return (!utility || e.utility === utility) && (!status || String(lv) === status)
      && (!q || `${e.name} ${e.id} ${e.zone}`.toLowerCase().includes(q.toLowerCase()));
  });

  return (
    <div className="page tpage">
      <PageHead title="Equipment monitoring" sub="Every asset with its live status and maintenance position. Click a row to inspect it." />
      <div className="tfilters">
        <input type="search" placeholder="Search name, ID or zone" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search equipment" />
        <select value={utility} onChange={(e) => setUtility(e.target.value)} aria-label="Utility"><option value="">All utilities</option>{UTILITIES.map((u) => <option key={u} value={u}>{UTILITY_LABEL[u]}</option>)}</select>
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status"><option value="">All statuses</option>{LEVELS.map((l, i) => <option key={l} value={i}>{l}</option>)}</select>
        <span className="small muted">{rows.length} of {catalog?.equipment?.length ?? 0} assets</span>
      </div>
      <div className="card ttable-wrap">
        <table className="ttable">
          <thead><tr><th>ID</th><th>Equipment</th><th>Utility</th><th>Zone</th><th>Status</th><th>Key reading</th><th>Runtime</th><th>Next maintenance</th><th>Alarms</th></tr></thead>
          <tbody>
            {rows.map((e) => {
              const lv = levels?.[e.id] ?? 0;
              const s = e.sensors.find((x) => !x.cumulative && x.normal);
              const x = extra[e.id];
              return (
                <tr key={e.id} onClick={() => setInspect(e.id)} tabIndex={0} onKeyDown={(ev) => ev.key === "Enter" && setInspect(e.id)} className={inspect === e.id ? "on" : ""}>
                  <td className="mono">{e.id}</td>
                  <td><b>{e.name}</b>{e.standby && <span className="tag">standby</span>}</td>
                  <td>{UTILITY_LABEL[e.utility]}</td>
                  <td>{e.zone}</td>
                  <td><LevelPill level={lv} /></td>
                  <td className="num">{s ? <><span className="muted small">{s.label}: </span><b>{sensorFmt(s, values?.[s.tag])}</b></> : "-"}</td>
                  <td className="num">{x?.runtime_h != null ? `${fmt(x.runtime_h, 0)} h` : "-"}</td>
                  <td>{x ? <>{x.next_maintenance}{x.maintenance_due && <span className="tag warn">due soon</span>}</> : "-"}</td>
                  <td className="num">{x?.alarms ? <b className="alarmnum">{x.alarms}</b> : "0"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {inspect && <div className="eq-drawer"><EquipmentPanel id={inspect} onClose={() => setInspect(null)} /></div>}
    </div>
  );
}
