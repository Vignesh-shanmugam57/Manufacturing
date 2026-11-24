// Weekly average flow as a tiny line chart. Flow units differ between rows in the source data,
// so this is a relative load trend, not a volume.
export default function Sparkline({ series }) {
  const pts = (series || []).filter((p) => p.avg_flow != null);
  if (pts.length < 2) return null;
  const w = 220, h = 54, pad = 4;
  const ys = pts.map((p) => p.avg_flow);
  const min = Math.min(...ys), max = Math.max(...ys);
  const span = max - min || 1;
  const x = (i) => pad + (i * (w - 2 * pad)) / (pts.length - 1);
  const y = (v) => h - pad - ((v - min) * (h - 2 * pad)) / span;
  const d = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.avg_flow).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} role="img"
         aria-label={`Weekly average flow, ${pts.length} weeks, from ${pts[0].avg_flow} to ${last.avg_flow}`}>
      <path d={d} fill="none" stroke="var(--chart-c1)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(pts.length - 1)} cy={y(last.avg_flow)} r="3.2" fill="var(--chart-c1)" />
    </svg>
  );
}
