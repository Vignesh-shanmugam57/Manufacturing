import { useCallback, useEffect, useRef, useState } from "react";
import { cached, cachedAt, peek, peekStale } from "../lib/cache.js";

/**
 * Load one endpoint through the shared stale-while-revalidate cache.
 * Returns { data, error, loading, refreshing, offline, updatedAt, reload }:
 *   loading    - nothing known yet (the only time a page should show a skeleton)
 *   refreshing - data is on screen and is being updated after a click or a navigation
 *   offline    - the last live update failed; the data on screen is the last known
 *   updatedAt  - when the data on screen was fetched (ms), for a "updated 5 s ago" label
 * With `pollMs` the data is also re-fetched quietly on that interval while the tab is visible (live view),
 * and straight away when the tab becomes visible again.
 */
export function useCached(key, fetcher, ttl = 60_000, { pollMs = 0 } = {}) {
  const fetchRef = useRef(fetcher);
  fetchRef.current = fetcher;
  const keyRef = useRef(key);
  keyRef.current = key;
  const alive = useRef(true);
  const [state, setState] = useState(() => {
    const v = peekStale(key);
    return { key, data: v === undefined ? null : v, error: "", loading: v === undefined, refreshing: false, offline: false, at: cachedAt(key) };
  });

  const load = useCallback((force = false, silent = false) => {
    const mine = () => alive.current && keyRef.current === key;
    if (!silent) {
      const fresh = force ? undefined : peek(key, ttl);
      if (fresh !== undefined) {
        setState({ key, data: fresh, error: "", loading: false, refreshing: false, offline: false, at: cachedAt(key) });
        return Promise.resolve();
      }
      const stale = peekStale(key);
      setState((s) => {
        const known = stale !== undefined ? stale : (s.key === key ? s.data : null);
        return { key, data: known, error: "", loading: known === null, refreshing: known !== null, offline: false, at: s.key === key ? s.at : cachedAt(key) };
      });
    }
    return cached(key, () => fetchRef.current(), { ttl, force: force || silent })
      .then((data) => { if (mine()) setState({ key, data, error: "", loading: false, refreshing: false, offline: false, at: Date.now() }); })
      .catch((e) => {
        if (!mine()) return;
        // With something already on screen a failed refresh is silent (live views just say "reconnecting").
        setState((s) => ({ ...s, key, error: s.data ? "" : e.message, loading: false, refreshing: false, offline: !!s.data }));
      });
  }, [key, ttl]);

  useEffect(() => {
    alive.current = true;
    load();
    return () => { alive.current = false; };
  }, [load]);

  useEffect(() => {
    if (!pollMs) return undefined;
    const visible = () => document.visibilityState === "visible";
    const id = setInterval(() => { if (visible()) load(true, true); }, pollMs);
    const onVisible = () => { if (visible() && Date.now() - cachedAt(key) > pollMs) load(true, true); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { clearInterval(id); document.removeEventListener("visibilitychange", onVisible); };
  }, [load, pollMs, key]);

  // Until the effect runs for a new key, show what is known for that key rather than the previous key's data.
  const cur = state.key === key ? state : (() => {
    const v = peekStale(key);
    return { data: v === undefined ? null : v, error: "", loading: v === undefined, refreshing: false, offline: false, at: cachedAt(key) };
  })();
  return {
    data: cur.data, error: cur.error, loading: cur.loading, refreshing: cur.refreshing,
    offline: cur.offline, updatedAt: cur.at, reload: () => load(true),
  };
}
