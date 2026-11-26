export const UTILITY_LABELS = {
  COMPRESSED_AIR: "Compressed air",
  CHILLED_WATER: "Chilled water",
  HVAC: "HVAC",
  PROCESS_WATER: "Process water",
  NITROGEN: "Nitrogen",
};

export const utilityLabel = (key) =>
  UTILITY_LABELS[key] || String(key || "").replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());

const TOOL_LABELS = {
  get_data_overview: "Checking which data is loaded",
  get_utility_health_board: "Reading the utility health board",
  get_consumption_trends: "Calculating consumption trends",
  detect_abnormal_usage: "Looking for abnormal usage",
  get_downtime_correlation: "Correlating utilities with downtime",
  get_efficiency_recommendations: "Finding efficiency opportunities",
  list_alerts: "Listing alerts",
  raise_alert: "Raising an alert",
  run_monitoring_scan: "Running the monitoring scan",
  verify_return_to_normal: "Verifying return to normal",
  get_schema: "Reading the data schema",
  run_sql: "Querying the data",
  get_plant_status: "Checking the plant status",
  list_open_issues: "Listing the open issues",
  get_issue: "Reading one issue",
  get_team_on_shift: "Checking who is on shift",
  get_usage_vs_normal: "Comparing usage with normal",
  get_issue_history: "Reading the issue history",
};

export const toolLabel = (name) => TOOL_LABELS[name] || name;

export const STATUS_ORDER = { ALARM: 3, WARNING: 2, WATCH: 1, NORMAL: 0 };

export const number = (n) => (n == null ? "-" : Number(n).toLocaleString());
export const pct = (n) => (n == null ? "-" : `${n > 0 ? "+" : ""}${n}%`);

// Backend timestamps are plant-local and naive ("2026-11-11T10:45:00"); display them as-is.
export function formatDateTime(value) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function timeAgo(value) {
  const d = new Date(value);
  const s = Math.round((Date.now() - d.getTime()) / 1000);
  if (Number.isNaN(s)) return "";
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)}d ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function seconds(ms) {
  if (ms == null) return "";
  return ms < 10000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms / 1000)} s`;
}

export function compact(n) {
  if (n == null) return "";
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

export function money(n) {
  if (n == null) return "-";
  return n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export function initials(name = "") {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join("") || "?";
}
