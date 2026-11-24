// Stale-while-revalidate cache shared by every page.
//
// Pages show whatever is already known straight away and refresh it quietly in the background, so moving
// between pages (or reloading the browser) never waits for the database. Values are also kept in
// localStorage, per signed-in user, so even the first paint after a reload has data. Only the very first
// visit with nothing stored has to wait.
const PREFIX = "utilities-agent.cache.";
const store = new Map(); // key -> { at, value?, promise? }   (at = 0 means "known but out of date")
let scope = null;        // signed-in user id; the persisted copy lives under it
let saveTimer = null;

const storage = () => { try { return window.localStorage; } catch { return null; } };

function save() {
  if (!scope || saveTimer) return;
  saveTimer = setTimeout(() => {
    saveTimer = null;
    const ls = storage();
    if (!ls || !scope) return;
    const out = {};
    for (const [k, e] of store) if (e.value !== undefined) out[k] = { at: e.at, value: e.value };
    try { ls.setItem(PREFIX + scope, JSON.stringify(out)); } catch { /* storage full or blocked: memory only */ }
  }, 300);
}

/** Call when a user signs in (or the page loads with a stored user). Loads that user's saved values. */
export function setCacheScope(userId) {
  if (scope === (userId || null)) return;
  scope = userId || null;
  store.clear();
  const ls = storage();
  if (!scope || !ls) return;
  try {
    const saved = JSON.parse(ls.getItem(PREFIX + scope) || "{}");
    for (const [k, e] of Object.entries(saved)) {
      if (e && e.value !== undefined) store.set(k, { at: e.at || 0, value: e.value });
    }
  } catch { /* corrupt entry: start empty */ }
}

/** The value if it is still fresh (younger than ttl), else undefined. */
export function peek(key, ttl = 60_000) {
  const e = store.get(key);
  return e && !e.promise && e.value !== undefined && Date.now() - e.at < ttl ? e.value : undefined;
}

/** Any value we know for this key, however old, else undefined. */
export function peekStale(key) {
  const e = store.get(key);
  return e && e.value !== undefined ? e.value : undefined;
}

/** When the value was last fetched (ms since epoch); 0 if unknown or marked out of date. */
export function cachedAt(key) {
  return store.get(key)?.at || 0;
}

/** Fetch through the cache. Concurrent callers share one request; `force` always starts a new one. */
export function cached(key, fetcher, { ttl = 60_000, force = false } = {}) {
  const e = store.get(key);
  if (!force && e) {
    if (e.promise) return e.promise;
    if (e.value !== undefined && Date.now() - e.at < ttl) return Promise.resolve(e.value);
  }
  const promise = fetcher().then(
    (value) => {
      if (store.get(key)?.promise === promise) { store.set(key, { at: Date.now(), value }); save(); }
      return value;
    },
    (err) => {
      const cur = store.get(key);
      if (cur?.promise === promise) {
        if (cur.value !== undefined) store.set(key, { at: cur.at, value: cur.value }); // keep showing the old value
        else store.delete(key);
      }
      throw err;
    },
  );
  store.set(key, { at: e?.at ?? 0, value: e?.value, promise });
  return promise;
}

/** Put a value in directly (for example a list the app already holds in state). */
export function setCached(key, value) {
  store.set(key, { at: Date.now(), value });
  save();
}

/** The data changed (upload, scan, alert update...). Keep the old values on screen but mark them out of date. */
export function invalidate() {
  for (const [k, e] of store) store.set(k, { at: 0, value: e.value }); // also drops requests that started earlier
  save();
}

/** Sign out: forget everything, in memory and on disk. */
export function clearCache() {
  store.clear();
  const ls = storage();
  if (ls && scope) { try { ls.removeItem(PREFIX + scope); } catch { /* ignore */ } }
  scope = null;
}
