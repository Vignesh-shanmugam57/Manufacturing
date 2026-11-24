import { useEffect, useMemo, useRef, useState } from "react";
import { twinApi } from "../../api/client.js";
import { useTwin, useTwinResource } from "../../lib/twin.js";
import "../../styles/response.css";

const WALK_MS = 8000;           // the demo walk: short enough to show, long enough to follow
const SCAN_MS = 3000;           // the agent's check after a fix is accepted
const STEPS = [
  { t: "Agent detects", s: "Reading out of range" },
  { t: "Owner notified", s: "By role and zone" },
  { t: "Person goes", s: "After Acknowledge" },
  { t: "Fix on site", s: "Record the fix" },
  { t: "Agent verifies", s: "Readings stay normal" },
];
const ON_SITE = ["ACKNOWLEDGED", "ASSIGNED", "INVESTIGATING"];

/** The live response on the plant map: what the agent and the person are doing about the open issue on the selected equipment. */
export default function LiveResponse({ equipmentId, apiRef }) {
  const open = useTwinResource("/issues?status=open");
  const mine = (open.data?.issues || []).find((i) => i.where.equipment_id === equipmentId) || null;
  const [tracked, setTracked] = useState(null);
  const [tick, setTick] = useState(0);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const snapTs = useTwin((s) => s.snap?.ts);
  const base = useRef({ ms: 0, at: 0 });

  // follow the equipment's open issue, and keep following it after it closes so the finish plays out
  useEffect(() => { if (mine) setTracked(mine.id); else if (!equipmentId) setTracked(null); }, [mine?.id, equipmentId]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setNote(""); setErr(""); if (!mine) setTracked(null); }, [equipmentId]);                                  // eslint-disable-line react-hooks/exhaustive-deps
  const detail = useTwinResource(tracked ? `/issues/${tracked}` : null);
  const d = detail.data && detail.data.id === tracked && detail.data.where.equipment_id === equipmentId ? detail.data : null;

  useEffect(() => { const t = setInterval(() => setTick((n) => n + 1), 500); return () => clearInterval(t); }, []);
  useEffect(() => { if (snapTs) base.current = { ms: Date.parse(snapTs), at: performance.now() }; }, [snapTs]);
  const serverNow = () => (base.current.ms ? base.current.ms + (performance.now() - base.current.at) : Date.now());

  const r = useMemo(() => {
    if (!d) return null;
    const el = (iso) => (iso ? serverNow() - Date.parse(iso) : null);
    const name = d.who?.name || null, local = performance.now();
    const common = { equipId: d.where.equipment_id, name };
    if (!d.open) {
      const c = el(d.time.closed_at);
      if (c == null || c > SCAN_MS + WALK_MS + 500) return null;
      return c < SCAN_MS ? { ...common, phase: "verifying", step: 5 } : { ...common, phase: "returning", returnStart: local - (c - SCAN_MS), step: 5 };
    }
    if (d.status === "OPEN") return { ...common, phase: name ? "notified" : "detected", step: name ? 1 : 0 };
    if (d.status === "CORRECTIVE_ACTION") return { ...common, phase: "verifying", step: 4 };
    const a = el(d.time.acknowledged_at ?? d.last_event?.ts) ?? 0;
    return a < WALK_MS ? { ...common, phase: "walking", walkStart: local - a, step: 2 } : { ...common, phase: "working", step: 3 };
  }, [d, tick]);                                                                                               // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { apiRef.current?.setResponse(r); }, [r?.phase, r?.equipId, r?.name, d?.id, apiRef]);       // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (r) apiRef.current?.setResponse(r); }, [r?.walkStart, r?.returnStart]);                 // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => apiRef.current?.setResponse(null), [apiRef]);

  // camera: a wide shot while the person walks (so the whole route is in view), then in on the equipment when they arrive
  const lastPhase = useRef(null);
  useEffect(() => {
    const was = lastPhase.current, now = r?.phase ?? null;
    lastPhase.current = now;
    if (!was || was === now) return;
    if (now === "walking" || now === "returning") apiRef.current?.resetCamera();
    else if (now === "working" && was === "walking") apiRef.current?.focus(r.equipId);
  }, [r?.phase]);                                                                                              // eslint-disable-line react-hooks/exhaustive-deps

  if (!d || !r) return null;
  const who = d.who?.name ? `${d.who.name}${d.who.role ? `, ${d.who.role}` : ""}` : "the shift team";
  const say = {
    detected: `The agent found ${d.what.actual} (expected ${d.what.expected}). Nobody is assigned yet.`,
    notified: `The agent opened ${d.code} and notified ${who}. Waiting for them to acknowledge.`,
    walking: `${who} acknowledged and is walking to ${d.where.equipment_name}.`,
    working: `${who} is at ${d.where.equipment_name}, working on it. Record the fix when it is done.`,
    verifying: d.open ? "Fix recorded. The agent is checking that the readings stay inside their limits." : `Verified from fresh readings. ${d.code} is closed.`,
    returning: `Closed. ${who} is heading back to the control room.`,
  }[r.phase];

  async function act(action, extra = {}) {
    setBusy(action); setErr("");
    try { await twinApi.post(`/alerts/${d.id}/actions`, { action, ...extra }); setNote(""); await detail.reload(); open.reload(); }
    catch (e) { setErr(e.message); } finally { setBusy(""); }
  }
  const st = d.status;

  return (
    <section className="lr" aria-label="Live response">
      <div className="lr-head"><b>Live response</b><span>{d.code} · {d.where.equipment_name}</span></div>
      <ol className="lr-steps">
        {STEPS.map((x, i) => <li key={x.t} className={i < r.step ? "done" : i === r.step ? "on" : ""}><b>{i + 1} {x.t}</b><small>{x.s}</small></li>)}
      </ol>
      <p className="lr-say" role="status">{say}</p>
      {d.open && (
        <div className="lr-acts">
          {st === "OPEN" && <button type="button" className="btn primary xs" disabled={!!busy} onClick={() => act("acknowledge")}>Acknowledge</button>}
          {ON_SITE.includes(st) && (
            <>
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What was done to fix it" aria-label="Fix note" />
              <button type="button" className="btn primary xs" disabled={!note.trim() || !!busy} onClick={() => act("corrective_action", { comment: note })}>Record the fix</button>
            </>
          )}
          {st === "CORRECTIVE_ACTION" && <button type="button" className="btn primary xs" disabled={!!busy} onClick={() => act("verify")}>Verify with telemetry</button>}
          {err && <span className="lr-err" role="alert">{err}</span>}
        </div>
      )}
    </section>
  );
}
