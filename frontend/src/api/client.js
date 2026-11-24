// Thin API client. All calls go to /api (proxied to FastAPI by Vite in development).
const USER_KEY = "utilities-agent.user";

export function loadUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY)) || null;
  } catch {
    return null;
  }
}

export function saveUser(user) {
  try {
    if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
    else localStorage.removeItem(USER_KEY);
  } catch {
    /* storage unavailable (private mode) - the session simply won't persist */
  }
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function headers() {
  const user = loadUser();
  return { "Content-Type": "application/json", ...(user ? { "X-User-Id": user.id } : {}) };
}

async function errorFrom(res) {
  let detail = `Request failed (${res.status})`;
  try {
    const body = await res.json();
    if (typeof body.detail === "string") detail = body.detail;
    else if (Array.isArray(body.detail)) {
      detail = body.detail.map((d) => String(d.msg || "").replace(/^Value error, /, "")).join("; ");
    }
  } catch {
    /* non-JSON error body */
  }
  if (res.status === 401) window.dispatchEvent(new CustomEvent("auth:expired"));
  return new ApiError(detail, res.status);
}

async function request(path, { method = "GET", body, form } = {}) {
  let res;
  try {
    const h = headers();
    if (form) delete h["Content-Type"];            // the browser sets the multipart boundary itself
    res = await fetch(`/api${path}`, {
      method,
      headers: h,
      body: form ?? (body === undefined ? undefined : JSON.stringify(body)),
    });
  } catch {
    throw new ApiError("Cannot reach the server. Is the backend running?", 0);
  }
  if (!res.ok) throw await errorFrom(res);
  return res.status === 204 ? null : res.json();
}

export const api = {
  health: () => request("/health"),
  login: (email, name, role) => request("/users/login", { method: "POST", body: { email, name, role } }),
  me: () => request("/users/me"),

  listSessions: () => request("/sessions"),
  getSession: (id) => request(`/sessions/${id}`),
  renameSession: (id, title) => request(`/sessions/${id}`, { method: "PATCH", body: { title } }),
  deleteSession: (id) => request(`/sessions/${id}`, { method: "DELETE" }),

  dataStatus: () => request("/data/status"),
  uploadCsv: (file, mode = "append") => {
    const form = new FormData();
    form.append("file", file);
    form.append("mode", mode);
    return request("/data/upload", { method: "POST", form });
  },
  clearDataset: (dataset) => request(`/data/${dataset}`, { method: "DELETE" }),

  healthBoard: () => request("/utilities/health-board"),
  plantSummary: (days = 30, day = null) => request(`/plant/summary?days=${days}${day ? `&day=${day}` : ""}`),
  overview: () => request("/utilities/overview"),
  anomalies: (days = 7) => request(`/utilities/anomalies?days=${days}`),
  downtimeCorrelation: () => request("/utilities/downtime-correlation"),
  efficiency: () => request("/utilities/efficiency"),
  trends: (period = "week", periods = 8) => request(`/utilities/trends?period=${period}&periods=${periods}`),
  scan: () => request("/utilities/scan", { method: "POST" }),

  alerts: (status = "open") => request(`/alerts?status=${encodeURIComponent(status)}`),
  assignAlert: (id, assignee) => request(`/alerts/${id}/assign`, { method: "POST", body: { assignee } }),
  setAlertStatus: (id, status, note = "") =>
    request(`/alerts/${id}/status`, { method: "POST", body: { status, note } }),
  verifyAlert: (id) => request(`/alerts/${id}/verify`, { method: "POST" }),
};

// Digital twin (live plant). Reads and writes go through the same error handling as the rest of the API.
export const authHeaders = () => headers();
export const twinApi = {
  get: (p) => request(`/twin${p}`),
  post: (p, body) => request(`/twin${p}`, { method: "POST", body }),
  put: (p, body) => request(`/twin${p}`, { method: "PUT", body }),
  del: (p) => request(`/twin${p}`, { method: "DELETE" }),
};

// Connections to the plant's data applications (databases, REST APIs, CSV links). Read only.
export const connApi = {
  get: (p) => request(`/connectors${p}`),
  post: (p, body) => request(`/connectors${p}`, { method: "POST", body }),
  patch: (p, body) => request(`/connectors${p}`, { method: "PATCH", body }),
  del: (p) => request(`/connectors${p}`, { method: "DELETE" }),
};

/**
 * Send a chat message and receive Server-Sent Events while the agent works:
 * session -> thinking / tool_start / tool_end ... -> final (or error).
 */
export async function streamChat({ sessionId, message, onEvent, signal }) {
  let res;
  try {
    res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ session_id: sessionId, message }),
      signal,
    });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw new ApiError("Cannot reach the server. Is the backend running?", 0);
  }
  if (!res.ok) throw await errorFrom(res);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let sep;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let type = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) type = line.slice(7).trim();
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) onEvent(type, JSON.parse(data));
    }
  }
}
