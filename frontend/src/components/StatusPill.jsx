// One pill for health status (NORMAL/WATCH/WARNING/ALARM), risk (MINIMAL/LOW/MEDIUM/HIGH),
// severity (LOW/MEDIUM/HIGH/CRITICAL) and alert status.
const TONE = {
  NORMAL: "normal", MINIMAL: "normal", VERIFIED: "normal", READY: "normal", OK: "normal",
  WATCH: "watch", LOW: "watch", ACKNOWLEDGED: "watch", RESOLVED: "watch",
  WARNING: "warning", MEDIUM: "warning", OPEN: "warning",
  ALARM: "alarm", HIGH: "alarm", CRITICAL: "alarm", "NO_DATA": "watch",
};

export default function StatusPill({ value, label, title }) {
  const v = String(value || "").toUpperCase();
  return (
    <span className={`pill pill-${TONE[v] || "neutral"}`} title={title}>
      <span className="pill-dot" />
      {label || v.replace("_", " ")}
    </span>
  );
}
