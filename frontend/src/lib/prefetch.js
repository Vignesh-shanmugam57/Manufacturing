import { api } from "../api/client.js";
import { cached } from "./cache.js";

// Warm the cache as soon as the user is known, so the first click on any page already has its data.
// Everything runs in parallel and in the background; a failure here is ignored (the page will retry itself).
const quiet = (p) => p.catch(() => {});

export function prefetchAll() {
  cached("healthBoard", () => api.healthBoard()).then(
    (hb) => { if (!hb.empty) quiet(cached("trends-week-8", () => api.trends("week", 8))); },
    () => {},
  );
  quiet(cached("alerts-all", () => api.alerts("all")));
  quiet(cached("alerts-open", () => api.alerts("open")));
  quiet(cached("dataStatus", () => api.dataStatus()));
  quiet(cached("overview", () => api.overview()));
  quiet(cached("health", () => api.health(), { ttl: 15_000 }));
  quiet(import("../components/PlantScene.jsx")); // the 3D line's code, so the Health board opens at once
}
