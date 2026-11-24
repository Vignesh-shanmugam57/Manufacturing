"""Connector operations: test a connection, save it, pull from it on demand or on a schedule, and store what was read.

Reads go into one of the app's datasets through the same validated importer the CSV upload uses (so rows that are
already stored are skipped and a pull can safely be repeated), or into the live feed. Nothing here writes to the source.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import logging
import re
import threading
import time

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.connectors import registry, secrets as vault
from app.connectors.base import ConnectorError, PullResult, TestResult
from app.db.session import SessionLocal
from app.models.connectors import ConnectorRun, DataConnector
from app.services import ingest

log = logging.getLogger("connectors")
SCHEDULES = {0: "Only when I press Pull now", 60: "Every minute", 300: "Every 5 minutes", 900: "Every 15 minutes", 3600: "Every hour"}
LIVE_FEED = "live_feed"
KEEP_RUNS = 30
_running: set[int] = set()
_running_lock = threading.Lock()


# ------------------------------------------------------------------ mapping
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


_ALIASES = {"timestamp": ["ts", "time", "datetime", "recordedat", "readingtime"], "tag": ["tagname", "name", "sensor", "point", "tagid"],
            "value": ["reading", "val", "v", "measurement"]}


def target_fields(target: str) -> list[str]:
    if target == LIVE_FEED:
        return ["tag", "value"]
    if target in ingest.DATASETS:
        return list(ingest.DATASETS[target].columns)
    raise ConnectorError("Unknown destination.")


def suggest_mapping(target: str, columns: list[str]) -> dict:
    """Match the source's columns to the destination's fields by name."""
    fields = target_fields(target)
    by_norm = {_norm(c): c for c in columns}
    mapping: dict[str, str] = {}
    for f in fields:
        hit = by_norm.get(_norm(f)) or next((by_norm[a] for a in _ALIASES.get(f, []) if a in by_norm), None)
        if hit:
            mapping[f] = hit
    return {"fields": fields, "columns": mapping, "missing": [f for f in fields if f not in mapping]}


def build_csv(target: str, rows: list[dict], mapping: dict) -> bytes:
    ds = ingest.DATASETS[target]
    cols, const = (mapping or {}).get("columns", {}), (mapping or {}).get("constants", {})
    out = io.StringIO(newline="")
    w = csv.writer(out)
    w.writerow(list(ds.columns))
    for r in rows:
        w.writerow([const[f] if f in const else ("" if r.get(cols.get(f, f)) is None else r.get(cols.get(f, f))) for f in ds.columns])
    return out.getvalue().encode("utf-8")


# ------------------------------------------------------------------ testing
def _split(kind: str, config: dict, secrets: dict) -> tuple[dict, dict]:
    keep = registry.secret_keys(kind)
    return ({k: v for k, v in (config or {}).items() if k not in keep}, {k: v for k, v in {**(config or {}), **(secrets or {})}.items() if k in keep})


def test_connection(kind: str, config: dict, secrets: dict, source: dict | None = None) -> dict:
    adapter = registry.adapter_for(kind)
    if kind not in registry.KINDS and kind != "sqlite":
        raise ConnectorError("Unknown connection type.")
    if adapter is None:
        return TestResult(False, "This connection type needs a driver that is added per project, once there is a server to connect to. "
                                 "The details can be saved for then.").__dict__
    cfg, sec = _split(kind, config, secrets)
    missing = [f["label"] for f in registry.KINDS.get(kind, {}).get("fields", []) if f["required"] and not (sec.get(f["key"]) if f["secret"] else cfg.get(f["key"]))]
    if missing:
        return TestResult(False, f"Fill in: {', '.join(missing)}.").__dict__
    if source:
        cfg["source"] = source
    return adapter.test(cfg, sec).__dict__


# ------------------------------------------------------------------ storing what was read
def store(s: Session, c: DataConnector, result: PullResult) -> tuple[int, str]:
    """Put pulled rows into the destination. Returns (rows stored, a plain sentence)."""
    mapping = c.mapping or {}
    if c.target == LIVE_FEED:
        from app.twin.engine import get_engine
        eng = get_engine()
        cols = mapping.get("columns", {})
        readings: dict[str, float] = {}
        for r in result.rows:
            try:
                readings[str(r[cols.get("tag", "tag")])] = float(r[cols.get("value", "value")])
            except (KeyError, TypeError, ValueError):
                continue
        if eng.mode != "live":
            return 0, f"Read {len(readings)} readings, but the live feed is in simulation mode, so they were not applied. Switch the live feed to live to use them."
        accepted, rejected = eng.ingest(readings, dt.datetime.now(), "LIVE")
        return accepted, f"Applied {accepted} readings to the live feed" + (f"; {len(rejected)} unknown tags were ignored." if rejected else ".")
    if c.target not in ingest.DATASETS:
        raise ConnectorError("The destination no longer exists. Edit the connection and choose another.")
    direct = result.raw_csv is not None and not mapping.get("columns") and not mapping.get("constants")
    data = result.raw_csv if direct else build_csv(c.target, result.rows, mapping)
    if not result.rows and not direct:
        return 0, "Nothing new to store."
    summary = ingest.ingest_csv(s, data, c.name, dataset=c.target, mode="append")
    stored = summary["inserted"]
    return stored, (f"{stored:,} new row{'s' if stored != 1 else ''} stored, {summary['duplicates_skipped']:,} already there"
                    + (f", {summary['invalid_skipped']:,} could not be used" if summary["invalid_skipped"] else "") + ".")


# ------------------------------------------------------------------ the saved connection
def connector_dict(c: DataConnector) -> dict:
    k = registry.KINDS.get(c.kind, {})
    try:
        set_keys = sorted(vault.decrypt(c.secrets_enc).keys())
    except ValueError:
        set_keys = []
    nxt = c.last_run_at + dt.timedelta(seconds=c.schedule_s) if (c.enabled and c.schedule_s and c.last_run_at) else None
    tlabel = "Live plant feed" if c.target == LIVE_FEED else ingest.DATASETS[c.target].label if c.target in ingest.DATASETS else c.target
    return {"id": c.id, "name": c.name, "kind": c.kind, "kind_label": k.get("label", c.kind), "category": k.get("category"), "config": c.config or {},
            "secrets_set": set_keys, "target": c.target, "target_label": tlabel, "mapping": c.mapping or {}, "schedule_s": c.schedule_s,
            "schedule_label": SCHEDULES.get(c.schedule_s, f"Every {c.schedule_s} s"), "enabled": c.enabled, "status": c.status,
            "last_run_at": c.last_run_at.isoformat(timespec="seconds") if c.last_run_at else None,
            "last_ok_at": c.last_ok_at.isoformat(timespec="seconds") if c.last_ok_at else None,
            "next_run_at": nxt.isoformat(timespec="seconds") if nxt else None, "last_rows_read": c.last_rows_read, "last_rows_stored": c.last_rows_stored,
            "last_message": c.last_message, "created_by": c.created_by, "created_at": c.created_at.isoformat(timespec="seconds")}


def _validate(kind: str, config: dict, secrets: dict, target: str, schedule_s: int, *, secrets_required: bool = True) -> None:
    if kind not in registry.KINDS:
        raise ConnectorError("Unknown connection type.")
    if registry.KINDS[kind]["adapter"] is None:
        raise ConnectorError("This connection type needs a driver that is added per project, so it cannot be saved yet.")
    if target != LIVE_FEED and target not in ingest.DATASETS:
        raise ConnectorError("Choose where the data should go.")
    if schedule_s not in SCHEDULES:
        raise ConnectorError("Choose how often to pull.")
    cfg, sec = _split(kind, config, secrets)
    for f in registry.KINDS[kind]["fields"]:
        if f["required"] and not (sec.get(f["key"]) if f["secret"] else cfg.get(f["key"])) and (secrets_required or not f["secret"]):
            raise ConnectorError(f"Fill in: {f['label']}.")


def create(s: Session, payload: dict, actor: str) -> DataConnector:
    kind, target = payload.get("kind", ""), payload.get("target", "")
    schedule = int(payload.get("schedule_s", 0) or 0)
    config, secrets = payload.get("config") or {}, payload.get("secrets") or {}
    name = (payload.get("name") or registry.KINDS.get(kind, {}).get("label", "")).strip()[:80]
    if not name:
        raise ConnectorError("Give the connection a name.")
    _validate(kind, config, secrets, target, schedule)
    cfg, sec = _split(kind, config, secrets)
    if payload.get("source"):
        cfg["source"] = payload["source"]
    mapping = payload.get("mapping")
    if not mapping and payload.get("columns"):
        mapping = {"columns": suggest_mapping(target, payload["columns"])["columns"]}
    c = DataConnector(name=name, kind=kind, config=cfg, secrets_enc=vault.encrypt(sec), target=target, mapping=mapping or {}, schedule_s=schedule,
                      enabled=True, status="NEW", created_by=actor[:120])
    s.add(c)
    s.commit()
    return c


def update(s: Session, c: DataConnector, payload: dict) -> DataConnector:
    if "name" in payload and payload["name"].strip():
        c.name = payload["name"].strip()[:80]
    if "enabled" in payload:
        c.enabled = bool(payload["enabled"])
    if "schedule_s" in payload:
        if int(payload["schedule_s"]) not in SCHEDULES:
            raise ConnectorError("Choose how often to pull.")
        c.schedule_s = int(payload["schedule_s"])
    if "mapping" in payload:
        c.mapping = payload["mapping"] or {}
    if "target" in payload:
        c.target = payload["target"]
    if "config" in payload:
        cfg, sec = _split(c.kind, payload["config"] or {}, payload.get("secrets") or {})
        old = dict(c.config or {})
        old.update(cfg)
        if "source" in (payload["config"] or {}):
            old["source"] = payload["config"]["source"]
        c.config = old
        if sec:                                                  # only the secrets that were typed again are replaced
            merged = vault.decrypt(c.secrets_enc)
            merged.update({k: v for k, v in sec.items() if v})
            c.secrets_enc = vault.encrypt(merged)
    if payload.get("reset_cursor"):
        c.cursor = None
    s.commit()
    return c


def delete_connector(s: Session, c: DataConnector) -> None:
    s.execute(delete(ConnectorRun).where(ConnectorRun.connector_id == c.id))
    s.delete(c)
    s.commit()


# ------------------------------------------------------------------ pulling
def run(connector_id: int, trigger: str = "manual") -> dict:
    """Pull once. Never raises for a source problem: the result says what happened and is also saved with the connection."""
    with _running_lock:
        if connector_id in _running:
            raise ConnectorError("A pull is already running for this connection.")
        _running.add(connector_id)
    started = dt.datetime.now().replace(microsecond=0)
    t0 = time.monotonic()
    ok, rows_read, stored, message = True, 0, 0, ""
    try:
        with SessionLocal() as s:
            c = s.get(DataConnector, connector_id)
            if c is None:
                raise ConnectorError("This connection no longer exists.")
            try:
                adapter = registry.adapter_for(c.kind)
                if adapter is None:
                    raise ConnectorError("This connection type needs a driver that is added per project.")
                res = adapter.pull(dict(c.config or {}), vault.decrypt(c.secrets_enc), c.cursor, registry.LIMIT.get(c.kind, 5000))
                rows_read = len(res.rows)
                stored, msg = store(s, c, res)
                message = f"{res.message} {msg}".strip()
                c.cursor = res.cursor
                c.last_ok_at = started
            except (ConnectorError, ValueError) as e:
                s.rollback()
                ok, message = False, str(e)
            except Exception as e:                               # noqa: BLE001
                s.rollback()
                log.exception("connector %s failed", connector_id)
                ok, message = False, f"Unexpected problem: {type(e).__name__}. {str(e)[:150]}"
            c = s.get(DataConnector, connector_id)
            ms = int((time.monotonic() - t0) * 1000)
            c.status, c.last_run_at, c.last_rows_read, c.last_rows_stored, c.last_message = ("OK" if ok else "ERROR"), started, rows_read, stored, message[:1000]
            s.add(ConnectorRun(connector_id=c.id, started_at=started, duration_ms=ms, ok=ok, trigger=trigger, rows_read=rows_read, rows_stored=stored, message=message[:1000]))
            s.flush()
            old = list(s.scalars(select(ConnectorRun.id).where(ConnectorRun.connector_id == c.id).order_by(ConnectorRun.id.desc()).offset(KEEP_RUNS)))
            if old:
                s.execute(delete(ConnectorRun).where(ConnectorRun.id.in_(old)))
            s.commit()
            return {"ok": ok, "rows_read": rows_read, "rows_stored": stored, "message": message, "duration_ms": ms, "connector": connector_dict(c)}
    finally:
        with _running_lock:
            _running.discard(connector_id)


def runs(s: Session, connector_id: int, limit: int = 20) -> list[dict]:
    q = select(ConnectorRun).where(ConnectorRun.connector_id == connector_id).order_by(ConnectorRun.id.desc()).limit(limit)
    return [{"id": r.id, "started_at": r.started_at.isoformat(timespec="seconds"), "duration_ms": r.duration_ms, "ok": r.ok, "trigger": r.trigger,
             "rows_read": r.rows_read, "rows_stored": r.rows_stored, "message": r.message} for r in s.scalars(q)]
