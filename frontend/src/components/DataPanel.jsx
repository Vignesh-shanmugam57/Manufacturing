import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { formatDateTime, number, timeAgo } from "../lib/format.js";
import { IconCheck, IconRefresh, IconUpload, IconX, Spinner } from "./icons.jsx";

const DATASET_HELP = {
  utility: "Hourly flow, pressure, temperature and alarms per utility, plant and zone.",
  machine: "Machine state, temperature, vibration and motor current. Used to see if utilities follow machine activity.",
  downtime: "Downtime events. Used to test whether downtime follows utility alarms.",
  energy: "Electricity per meter and area (compressor, chiller, HVAC, production), with cost and CO2.",
  production: "Output, good and rejected units, and downtime per line and hour. Used for consumption per unit.",
  maintenance: "CMMS work orders: preventive, predictive and corrective, with failure modes and status.",
  ncr: "Defects found, their root causes and the corrective actions (CAPA) still due.",
  quality: "Inspection results (pass or fail) against specification limits, per line and station.",
  assets: "Asset register: each machine, its type, line, criticality and planned maintenance interval.",
  plants: "Plant names, location and currency.",
  lines: "Production lines: line type, nominal capacity and takt time.",
};

function DatasetCard({ d, onClear, busy }) {
  const [confirm, setConfirm] = useState(false);
  const loaded = d.rows > 0;
  return (
    <article className={`card dataset-card${loaded ? " loaded" : ""}`} aria-label={d.label}>
      <header className="dataset-head">
        <h3>{d.label}</h3>
        <span className={`chip ${loaded ? "chip-ok" : ""}`}>{loaded ? "Loaded" : "Not uploaded"}</span>
      </header>
      <p className="small muted">{DATASET_HELP[d.dataset]}</p>
      <div className="dataset-stats">
        <div><span className="stat-value">{number(d.rows)}</span><span className="stat-label">rows</span></div>
        <div>
          <span className="stat-value small-value">{loaded ? `${formatDateTime(d.first_ts)} → ${formatDateTime(d.last_ts)}` : "-"}</span>
          <span className="stat-label">date range</span>
        </div>
      </div>
      {d.last_upload && (
        <p className="small muted">
          Last upload {timeAgo(d.last_upload.uploaded_at)}: {number(d.last_upload.inserted)} added, {number(d.last_upload.skipped)} skipped.
        </p>
      )}
      {loaded && (confirm ? (
        <div className="confirm-row">
          <span className="small">Delete all {number(d.rows)} rows?</span>
          <button className="btn danger xs" disabled={busy} onClick={() => { setConfirm(false); onClear(d.dataset); }}>Delete</button>
          <button className="icon-btn sm" aria-label="Cancel" onClick={() => setConfirm(false)}><IconX width={15} height={15} /></button>
        </div>
      ) : (
        <button className="btn ghost xs" disabled={busy} onClick={() => setConfirm(true)}>Delete data</button>
      ))}
    </article>
  );
}

export default function DataPanel({ onDataChanged, embedded = false }) {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [replace, setReplace] = useState(false);
  const [drag, setDrag] = useState(false);
  const [uploads, setUploads] = useState([]); // {name, state: queued|uploading|done|error, result?, error?}
  const [uploading, setUploading] = useState(false);
  const input = useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setStatus(await api.dataStatus());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function uploadFiles(fileList) {
    const files = [...fileList].filter((f) => f.name.toLowerCase().endsWith(".csv"));
    if (files.length === 0) {
      setError("Choose one or more .csv files.");
      return;
    }
    setError("");
    setUploading(true);
    setUploads(files.map((f) => ({ name: f.name, state: "queued" })));
    for (const [i, file] of files.entries()) {
      const patch = (p) => setUploads((list) => list.map((u, j) => (j === i ? { ...u, ...p } : u)));
      patch({ state: "uploading" });
      try {
        patch({ state: "done", result: await api.uploadCsv(file, replace ? "replace" : "append") });
      } catch (e) {
        patch({ state: "error", error: e.message });
      }
    }
    setUploading(false);
    await load();
    onDataChanged?.();
  }

  async function clear(dataset) {
    setError("");
    try {
      await api.clearDataset(dataset);
      await load();
      onDataChanged?.();
    } catch (e) {
      setError(e.message);
    }
  }

  const anyLoaded = status?.datasets.some((d) => d.rows > 0);

  return (
    <div className={embedded ? "embedded-data" : "page"}>
      <header className="page-head">
        <div>
          {embedded ? <h3>Data upload</h3> : <h2>Data</h2>}
          <p className="muted">
            Import utility telemetry, machine telemetry and downtime files. They are stored in PostgreSQL and the agent
            analyses them to find abnormal usage, link utilities to downtime and suggest savings.
          </p>
        </div>
        <div className="page-actions">
          <button className="btn ghost" onClick={load} disabled={loading || uploading}>
            {loading ? <Spinner /> : <IconRefresh width={16} height={16} />} Refresh
          </button>
        </div>
      </header>

      {error && <div className="chat-error" role="alert">{error}</div>}

      <section
        className={`dropzone card${drag ? " drag" : ""}${uploading ? " busy" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); if (!uploading) uploadFiles(e.dataTransfer.files); }}
      >
        <IconUpload width={28} height={28} />
        <h3>Drop CSV files here</h3>
        <p className="muted small">
          Utility telemetry, machine telemetry and downtime files. The type is recognised from the columns,
          so you can select all of them at once.
        </p>
        <input ref={input} type="file" accept=".csv,text/csv" multiple hidden data-testid="csv-input"
               onChange={(e) => { uploadFiles(e.target.files); e.target.value = ""; }} />
        <button className="btn primary" disabled={uploading} onClick={() => input.current?.click()}>
          {uploading ? <Spinner /> : <IconUpload width={16} height={16} />} {uploading ? "Uploading…" : "Choose CSV files"}
        </button>
        <label className="check small">
          <input type="checkbox" checked={replace} disabled={uploading} onChange={(e) => setReplace(e.target.checked)} />
          Replace existing rows of that file type (otherwise new rows are added and repeats are skipped)
        </label>
        {uploading && <p className="small muted">Saving to the database. Large files can take a minute, please keep this page open.</p>}
      </section>

      {uploads.length > 0 && (
        <section className="card upload-results" aria-label="Upload results" aria-live="polite">
          <h3>Upload results</h3>
          <ul>
            {uploads.map((u, i) => (
              <li key={`${u.name}-${i}`} className={`upload-${u.state}`}>
                <span className="upload-icon">
                  {u.state === "done" && <IconCheck width={16} height={16} />}
                  {u.state === "error" && <IconX width={16} height={16} />}
                  {u.state === "uploading" && <Spinner />}
                  {u.state === "queued" && <span className="pill-dot" />}
                </span>
                <div>
                  <strong>{u.name}</strong>
                  {u.state === "uploading" && <span className="muted small"> uploading…</span>}
                  {u.state === "queued" && <span className="muted small"> waiting</span>}
                  {u.state === "done" && (
                    <p className="small muted">
                      {u.result.label}: <strong>{number(u.result.inserted)}</strong> rows added
                      {u.result.duplicates_skipped > 0 && <>, {number(u.result.duplicates_skipped)} already stored</>}
                      {u.result.invalid_skipped > 0 && <>, <span className="warn-text">{number(u.result.invalid_skipped)} invalid skipped</span></>}
                      {" "}(table now {number(u.result.total_rows)} rows).
                      {u.result.errors.length > 0 && <> First problems: {u.result.errors.join("; ")}</>}
                    </p>
                  )}
                  {u.state === "error" && <p className="small form-error">{u.error}</p>}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {loading && !status && <div className="center muted"><Spinner /> Loading…</div>}
      {status && (
        <>
          <section className="datasets" aria-label="Datasets">
            {status.datasets.map((d) => <DatasetCard key={d.dataset} d={d} onClear={clear} busy={uploading} />)}
          </section>
          {!anyLoaded && (
            <div className="banner" role="status">No data yet. Upload the three files above, then ask the agent in a chat.</div>
          )}
          {status.data_quality.length > 0 && (
            <section className="card quality" aria-label="Data quality notes">
              <h3>Data quality notes</h3>
              <p className="small muted">The agent takes these into account when it analyses your data.</p>
              <ul>{status.data_quality.map((n, i) => <li key={i}>{n}</li>)}</ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}
