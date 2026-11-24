// Placeholder blocks for a page whose data has never been loaded. Once data is known (even from an earlier
// visit) pages show it immediately and refresh quietly instead.
export default function PageSkeleton({ kpis = 6, label = "Loading" }) {
  return (
    <div className="page dash" aria-busy="true" aria-label={label}>
      <div className="skel skel-hero" />
      <div className="dkpis">{Array.from({ length: kpis }, (_, i) => <div key={i} className="skel skel-kpi" />)}</div>
      <div className="dgrid"><div className="skel skel-block" /><div className="skel skel-block" /></div>
    </div>
  );
}
