// Live plant data. One Server-Sent Events stream feeds a small external store; components subscribe to just
// the slice they show, so a value that did not change does not re-render anything. The 3D scene reads the store
// directly inside its animation loop.
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { authHeaders, twinApi } from "../api/client.js";

export const LEVELS = ["Normal", "Warning", "Major", "Critical", "Offline"];
export const LEVEL_COLOR = ["#22c55e", "#facc15", "#f97316", "#ef4444", "#6b7280"];
export const SEVERITY_LEVEL = { INFO: 0, WARNING: 1, MAJOR: 2, CRITICAL: 3 };
const HISTORY_MAX = 1800;          // points kept per tag in the browser (30 min at 1 Hz)

export const state = {
  rev: 0, tick: 0, conn: "idle", snap: null, catalog: null, lastEvent: 0, history: new Map(), byId: {}, tags: {}, error: "",
};
const subs = new Set();
const emit = () => { state.rev += 1; subs.forEach((f) => f()); };
const subscribe = (f) => { subs.add(f); return () => subs.delete(f); };

function shallowEqual(a, b) {
  if (Object.is(a, b)) return true;
  if (typeof a !== "object" || typeof b !== "object" || !a || !b) return false;
  const ka = Object.keys(a), kb = Object.keys(b);
  return ka.length === kb.length && ka.every((k) => Object.is(a[k], b[k]));
}

/** Subscribe to a slice of the store. `selector(state)` must be cheap; the result is compared shallowly. */
export function useTwin(selector, deps = []) {
  const sel = useRef(selector);
  sel.current = selector;
  const key = JSON.stringify(deps);
  const cache = useRef({ rev: -1, value: undefined, key });
  if (cache.current.key !== key) cache.current = { rev: -1, value: undefined, key };
  const get = useCallback(() => {
    const c = cache.current;
    if (c.rev === state.rev) return c.value;
    const next = sel.current(state);
    c.rev = state.rev;
    if (!shallowEqual(c.value, next)) c.value = next;
    return c.value;
  }, []);
  return useSyncExternalStore(subscribe, get);
}

// ----------------------------------------------------------------------------- stream
let stopped = true;
let abort = null;
let watchdog = null;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function onSnapshot(snap) {
  const now = Date.now();
  state.snap = snap;
  state.tick += 1;
  state.lastEvent = now;
  state.conn = "live";
  let power = 0;
  for (const [tag, v] of Object.entries(snap.values)) {
    let arr = state.history.get(tag);
    if (!arr) { arr = []; state.history.set(tag, arr); }
    arr.push([now, v]);
    if (arr.length > HISTORY_MAX) arr.splice(0, arr.length - HISTORY_MAX);
    if (tag.endsWith(".power_kw")) power += v;
  }
  let tot = state.history.get("_total_power_kw");
  if (!tot) { tot = []; state.history.set("_total_power_kw", tot); }
  tot.push([now, Math.round(power * 10) / 10]);
  if (tot.length > HISTORY_MAX) tot.splice(0, tot.length - HISTORY_MAX);
  emit();
}

async function backfill() {
  try {
    const tags = Object.keys(state.snap?.values || {}).join(",");
    if (!tags) return;
    const res = await twinApi.get(`/series?tags=${encodeURIComponent(tags)}&minutes=15&step=3`);
    for (const [tag, pts] of Object.entries(res.series)) {
      const cur = state.history.get(tag) || [];
      const first = cur.length ? cur[0][0] : Infinity;
      state.history.set(tag, [...pts.filter((p) => p[0] < first), ...cur]);
    }
    // the plant total is not a sensor, so rebuild its history from the metered drives
    const sums = new Map();
    for (const [tag, pts] of Object.entries(res.series)) {
      if (!tag.endsWith(".power_kw")) continue;
      for (const [t, v] of pts) sums.set(t, (sums.get(t) || 0) + v);
    }
    const tot = state.history.get("_total_power_kw") || [];
    const firstTot = tot.length ? tot[0][0] : Infinity;
    const old = [...sums.entries()].sort((a, b) => a[0] - b[0]).filter(([t]) => t < firstTot).map(([t, v]) => [t, Math.round(v * 10) / 10]);
    state.history.set("_total_power_kw", [...old, ...tot]);
    emit();
  } catch { /* charts simply start from now */ }
}

async function connectLoop() {
  let delay = 1000;
  let first = true;
  while (!stopped) {
    try {
      abort = new AbortController();
      state.conn = state.snap ? "reconnecting" : "connecting";
      emit();
      const res = await fetch("/api/twin/stream", { headers: authHeaders(), signal: abort.signal });
      if (!res.ok) throw new Error(`stream ${res.status}`);
      delay = 1000;
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true }).replace(/\r\n/g, "\n");
        let i;
        while ((i = buf.indexOf("\n\n")) !== -1) {
          const block = buf.slice(0, i);
          buf = buf.slice(i + 2);
          const line = block.split("\n").find((l) => l.startsWith("data: "));
          if (line) {
            onSnapshot(JSON.parse(line.slice(6)));
            if (first) { first = false; backfill(); }
          }
        }
      }
    } catch (e) {
      if (stopped || e.name === "AbortError") return;
    }
    if (stopped) return;
    state.conn = "reconnecting";
    emit();
    await sleep(delay);
    delay = Math.min(delay * 1.6, 8000);
  }
}

async function loadCatalog() {
  try {
    const c = await twinApi.get("/catalog");
    state.catalog = c;
    state.byId = Object.fromEntries(c.equipment.map((e) => [e.id, e]));
    state.tags = {};
    for (const e of c.equipment) for (const s of e.sensors) state.tags[s.tag] = { ...s, equipment: e };
    emit();
  } catch (e) {
    state.error = e.message;
    emit();
  }
}

export function startTwin() {
  if (!stopped) return;
  stopped = false;
  loadCatalog();
  connectLoop();
  watchdog = setInterval(() => {
    if (state.conn === "live" && Date.now() - state.lastEvent > 4500) { state.conn = "reconnecting"; emit(); }
  }, 2000);
}

export function stopTwin() {
  stopped = true;
  abort?.abort();
  clearInterval(watchdog);
  state.conn = "idle";
  state.snap = null;
  state.history = new Map();
  emit();
}

// ----------------------------------------------------------------------------- data hooks
/** A REST resource that refreshes when the server says something changed (alerts, tasks, notifications). */
export function useTwinResource(path) {
  const version = useTwin((s) => s.snap?.version ?? 0);
  const [res, setRes] = useState({ data: null, loading: true, error: "" });
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const reload = useCallback(async () => {
    try {
      const data = await twinApi.get(path);
      if (alive.current) setRes({ data, loading: false, error: "" });
      return data;
    } catch (e) {
      if (alive.current) setRes((r) => ({ ...r, loading: false, error: r.data ? "" : e.message }));
      return null;
    }
  }, [path]);
  useEffect(() => { reload(); }, [reload, version]);
  return { ...res, reload };
}

/** A REST resource polled on an interval (live equipment detail). */
export function useTwinPoll(path, ms = 2000, enabled = true) {
  const [res, setRes] = useState({ data: null, loading: true, error: "" });
  useEffect(() => {
    if (!enabled || !path) return undefined;
    let alive = true;
    const load = async () => {
      try {
        const data = await twinApi.get(path);
        if (alive) setRes({ data, loading: false, error: "" });
      } catch (e) {
        if (alive) setRes((r) => ({ ...r, loading: false, error: r.data ? "" : e.message }));
      }
    };
    setRes({ data: null, loading: true, error: "" });
    load();
    const id = setInterval(load, ms);
    return () => { alive = false; clearInterval(id); };
  }, [path, ms, enabled]);
  return res;
}

/** Live history of tags for charts: [[ms, value], ...] per tag, newest last, limited to the last `seconds`. */
export function useSeries(tags, seconds = 300) {
  return useTwin((s) => {
    const cutoff = Date.now() - seconds * 1000;
    return tags.map((t) => {
      const arr = s.history.get(t) || [];
      let i = 0;
      while (i < arr.length && arr[i][0] < cutoff) i += 1;
      return arr.slice(i);
    });
  }, [tags.join(","), seconds]);
}

// ----------------------------------------------------------------------------- helpers
export const fmt = (v, d = 1) => (v == null || Number.isNaN(v) ? "-" : Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d }));
export const sensorFmt = (s, v) => `${fmt(v, s?.decimals ?? 1)}${s?.unit ? ` ${s.unit}` : ""}`;

export function parseBand(text) {
  // "6.4 - 7.2 bar" -> [6.4, 7.2]; "<= 5 %" -> [null, 5]
  if (!text) return null;
  const m = text.match(/^(-?[\d.]+) - (-?[\d.]+)/);
  if (m) return [parseFloat(m[1]), parseFloat(m[2])];
  const le = text.match(/^<= (-?[\d.]+)/);
  if (le) return [null, parseFloat(le[1])];
  const ge = text.match(/^>= (-?[\d.]+)/);
  if (ge) return [parseFloat(ge[1]), null];
  return null;
}
