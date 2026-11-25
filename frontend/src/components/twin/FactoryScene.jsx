import { useEffect, useRef, useState } from "react";
import { state, useTwin } from "../../lib/twin.js";
import { createFactory } from "./factoryScene.js";

/** The interactive 3D plant. All animation reads the live store directly, so React does not re-render per frame. */
export default function FactoryScene({ selectedId, onSelect, utility, flows = true, alerts, apiRef, labels = true, onLabelsClosed, inset = 0 }) {
  const closedRef = useRef(onLabelsClosed);
  closedRef.current = onLabelsClosed;
  const host = useRef(null);
  const scene = useRef(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const catalog = useTwin((s) => s.catalog);
  const [failed, setFailed] = useState("");

  useEffect(() => {
    if (!catalog || !host.current) return undefined;
    let api;
    try {
      api = createFactory(host.current, {
        catalog, getState: () => state,
        onSelect: (id) => onSelectRef.current?.(id),
        onLabelsClosed: (n) => closedRef.current?.(n),
      });
    } catch (e) {
      setFailed(e.message || "The 3D view could not start.");
      return undefined;
    }
    scene.current = api;
    window.__factory = api;            // handle for automated tests and debugging
    if (apiRef) apiRef.current = api;
    return () => { api.dispose(); scene.current = null; if (apiRef) apiRef.current = null; };
  }, [catalog, apiRef]);

  useEffect(() => { scene.current?.setSelected(selectedId); }, [selectedId, catalog]);
  useEffect(() => { scene.current?.setFilter(utility); }, [utility, catalog]);
  useEffect(() => { scene.current?.setFlows(flows); }, [flows, catalog]);
  useEffect(() => { scene.current?.setAlerts(alerts); }, [alerts, catalog]);
  useEffect(() => { scene.current?.setLabels(labels); }, [labels, catalog]);
  useEffect(() => { scene.current?.setInset(inset); }, [inset, catalog]);

  return (
    <div className="factory" ref={host} data-testid="factory-3d">
      {!catalog && !failed && <div className="factory-msg">Loading the plant model…</div>}
      {failed && <div className="factory-msg err">The 3D view needs WebGL, which is not available here. ({failed})</div>}
    </div>
  );
}
