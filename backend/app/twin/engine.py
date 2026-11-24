"""Telemetry engine: live values, limit evaluation, anomaly detection, alert lifecycle, KPIs.

Live state (ring buffers, levels, alert cache) is in memory so the stream and every page answer instantly; the
database (Neon) is the durable record, written by a background writer so the 1 Hz loop never waits on a round trip.
It assumes one server process. Readings come from the SIMULATED adapter or are pushed to /api/twin/ingest.
"""
from __future__ import annotations

import datetime as dt
import logging
import math
import queue
import statistics
import threading
import time
from collections import defaultdict, deque

from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models import (TwinAlert, TwinAlertEvent, TwinEquipment, TwinMaintenance, TwinNotification, TwinPerson,
                        TwinReading, TwinSetting)
from app.twin import agent, catalog as cat, detectors, people as ppl
from app.twin.simulator import SCENARIOS, Simulator

log = logging.getLogger("twin")

RING = 7200                 # seconds of 1 Hz history kept in memory
CONFIRM_UP, CONFIRM_DOWN = 3, 5      # consecutive readings before a worse / better level is believed
CREATE_AFTER = 5            # consecutive evaluations an anomaly must persist before an alert is raised
CLEAR_AFTER = 10            # evaluations without the anomaly before "condition cleared" is recorded
VERIFY_STABLE = 20          # seconds of readings that must all be inside limits to verify recovery
STALE_S = 15                # a tag not updated for this long is OFFLINE
ESCALATE_AFTER = {"CRITICAL": 120, "MAJOR": 300}      # seconds unacknowledged before escalation
ESCALATE_TO = {"CRITICAL": "plant_manager", "MAJOR": "operations_supervisor"}
PERSIST_EVERY_S = 300
RETENTION_DAYS = 7
LEVEL_NUM = {"INFO": 0, "WARNING": 1, "MAJOR": 2, "CRITICAL": 3}
DEFAULT_TARIFFS = {"electricity": 0.11, "gas": 0.45, "water": 1.8, "currency": "USD"}
TEAMS = ["Maintenance team", "Facilities team", "Utilities engineer", "Instrument technician", "Safety officer"]

ALERT_ACTIONS = {
    "acknowledge": {"OPEN"},
    "assign": {"OPEN", "ACKNOWLEDGED", "ASSIGNED", "INVESTIGATING"},
    "investigate": {"ACKNOWLEDGED", "ASSIGNED"},
    "comment": {"OPEN", "ACKNOWLEDGED", "ASSIGNED", "INVESTIGATING", "CORRECTIVE_ACTION"},
    "corrective_action": {"ACKNOWLEDGED", "ASSIGNED", "INVESTIGATING"},
    "verify": {"CORRECTIVE_ACTION"},
    "reopen": {"CORRECTIVE_ACTION", "VERIFIED"},
}


def _iso(d: dt.datetime | dt.date | None) -> str | None:
    return d.isoformat(timespec="seconds") if isinstance(d, dt.datetime) else (d.isoformat() if d else None)


def alert_dict(r: TwinAlert, events: list[dict] | None = None) -> dict:
    return {
        "id": r.id, "code": r.code, "created_at": _iso(r.created_at), "updated_at": _iso(r.updated_at), "utility": r.utility,
        "equipment_id": r.equipment_id, "zone": r.zone, "severity": r.severity, "anomaly_type": r.anomaly_type,
        "title": r.title, "actual": r.actual, "expected": r.expected, "description": r.description,
        "probable_cause": r.probable_cause, "certainty": r.cause_certainty, "confidence": r.confidence,
        "recommendation": r.recommendation, "impact": r.impact, "consumers": r.consumers or [], "status": r.status,
        "assigned_to": r.assigned_to, "source": r.source, "acknowledged_at": _iso(r.acknowledged_at),
        "closed_at": _iso(r.closed_at), "verification_note": r.verification_note, "analysis": r.analysis,
        "evidence": r.evidence or [], "events": events or [], "condition_cleared": False, "escalated": False,
    }


def maint_dict(m: TwinMaintenance) -> dict:
    return {"id": m.id, "alert_id": m.alert_id, "equipment_id": m.equipment_id, "maintenance_type": m.maintenance_type,
            "problem": m.problem, "recommendation": m.recommendation, "priority": m.priority, "assigned_to": m.assigned_to,
            "planned_date": _iso(m.planned_date), "status": m.status, "notes": m.notes, "resolution": m.resolution,
            "source": m.source, "created_at": _iso(m.created_at), "completed_at": _iso(m.completed_at),
            "verified_at": _iso(m.verified_at)}


def note_dict(n: TwinNotification) -> dict:
    return {"id": n.id, "ts": _iso(n.ts), "alert_id": n.alert_id, "recipient": n.recipient, "channel": n.channel,
            "level": n.level, "message": n.message, "escalated": n.escalated}


class ActionError(ValueError):
    pass


class Engine:
    def __init__(self, seed: int | None = None, start: dt.datetime | None = None):
        start = start or dt.datetime.now()
        self.sim = Simulator(seed, start)
        self.mode = "simulation"
        self.lock = threading.RLock()
        self.q: queue.Queue = queue.Queue()
        self.values: dict[str, float] = {}
        self.stamp: dict[str, float] = {}
        self.ring = {t: deque(maxlen=RING) for t in cat.TAGS}
        self.levels = {t: 0 for t in cat.TAGS}
        self._up: dict[str, int] = defaultdict(int)
        self._down: dict[str, int] = defaultdict(int)
        self.eq_level = {e.id: 0 for e in cat.EQUIPMENT}
        self.alerts: dict[int, dict] = {}
        self.maint: dict[int, dict] = {}
        self.notifications: deque = deque(maxlen=300)
        self.active: dict[tuple, int] = {}
        self.pending: set = set()
        self._cond: dict = defaultdict(int)
        self._clear: dict = defaultdict(int)
        self.avail = {u: deque(maxlen=3600) for u in cat.UTILITIES}
        self.downtime_s = 0.0
        self.version = 0
        self.ticks = 0
        self.started = start
        self.tariffs = dict(DEFAULT_TARIFFS)
        self.meta: dict[str, dict] = {}
        self.last_snapshot_ts = None
        self._kpi_cache: tuple[float, dict] | None = None
        self._last_persist = time.monotonic()
        self.ready = threading.Event()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.rejected = 0
        self.ingested = 0
        self._now_ts = start.timestamp()
        self._seed_meta()
        self.ingest(self.sim.values, start, "SIMULATED", count=False)
        self.evaluate(start, 1.0)

    # ------------------------------------------------------------------ View protocol used by the detectors
    def hist(self, tag: str, seconds: int) -> list[float]:
        cutoff = self._now_ts - seconds
        out: list[float] = []
        for t, v in reversed(self.ring[tag]):
            if t < cutoff:
                break
            out.append(v)
        out.reverse()
        return out

    def baseline(self, tag: str) -> float:
        now = self._now_ts
        vals = [v for t, v in self.ring[tag] if now - 900 <= t <= now - 90]
        if len(vals) >= 30:
            return statistics.median(vals)
        e, s = cat.SPEC[tag]
        return s.nominal

    # ------------------------------------------------------------------ meta / lifecycle
    def _seed_meta(self) -> None:
        today = dt.date.today()
        for e in cat.EQUIPMENT:
            last = today - dt.timedelta(days=e.last_maintenance_days_ago)
            self.meta[e.id] = {"last_maintenance": last, "next_maintenance": last + dt.timedelta(days=e.maintenance_interval_days)}

    @property
    def source_label(self) -> str:
        return "SIMULATED" if self.mode == "simulation" else "LIVE"

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        for fn, name in ((self._run_loop, "twin-engine"), (self._writer_loop, "twin-writer")):
            th = threading.Thread(target=fn, name=name, daemon=True)
            th.start()
            self._threads.append(th)

    def stop(self) -> None:
        self._stop.set()
        for th in self._threads:
            th.join(timeout=3)
        self._threads.clear()

    def _run_loop(self) -> None:
        nxt = time.monotonic()
        while not self._stop.is_set():
            nxt += 1.0
            try:
                self.tick(dt.datetime.now(), 1.0)
            except Exception:                                   # noqa: BLE001 - the loop must survive a bad tick
                log.exception("twin tick failed")
            delay = nxt - time.monotonic()
            if delay > 0:
                self._stop.wait(delay)
            else:
                nxt = time.monotonic()

    def _writer_loop(self) -> None:
        try:
            self.load_from_db()
        except Exception:                                       # noqa: BLE001
            log.exception("twin: could not load from the database; continuing in memory")
        self.ready.set()
        while not self._stop.is_set():
            try:
                item = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            self._handle(item)

    def drain(self) -> None:
        """Process every queued database write now (used by tests and by shutdown)."""
        while True:
            try:
                item = self.q.get_nowait()
            except queue.Empty:
                return
            self._handle(item)

    def _handle(self, item) -> None:
        kind, args = item[0], item[1:]
        try:
            {"create": self._h_create, "severity": self._h_severity, "event": self._h_event, "escalate": self._h_escalate,
             "verify": self._h_verify, "readings": self._h_readings}[kind](*args)
        except Exception:                                       # noqa: BLE001
            log.exception("twin writer: %s failed", kind)
            if kind == "create":
                self.pending.discard((args[0]["equipment_id"], args[0]["type"]))

    # ------------------------------------------------------------------ ingest and tick
    def ingest(self, readings: dict[str, float], now: dt.datetime, source: str, count: bool = True) -> tuple[int, list[str]]:
        ts = now.timestamp()
        rejected: list[str] = []
        with self.lock:
            self._now_ts = max(self._now_ts, ts)
            n = 0
            for tag, v in readings.items():
                if tag not in cat.SPEC or not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
                    rejected.append(tag)
                    continue
                self.values[tag] = float(v)
                self.stamp[tag] = ts
                self.ring[tag].append((ts, float(v)))
                n += 1
            if count:
                self.ingested += n
                self.rejected += len(rejected)
        return n, rejected

    def tick(self, now: dt.datetime, dt_s: float = 1.0) -> None:
        if self.mode == "simulation":
            self.ingest(self.sim.step(dt_s, now), now, "SIMULATED", count=False)
        self.evaluate(now, dt_s)
        self.ticks += 1
        if time.monotonic() - self._last_persist >= PERSIST_EVERY_S:
            self._last_persist = time.monotonic()
            rows = [(now, t, v) for t, v in self.values.items() if t in cat.SPEC]
            self.q.put(("readings", rows))

    # ------------------------------------------------------------------ evaluation
    def evaluate(self, now: dt.datetime, dt_s: float) -> None:
        with self.lock:
            self._levels(now)
            self._availability(dt_s)
            self._manage_alerts(now)

    def _levels(self, now: dt.datetime) -> None:
        ts = now.timestamp()
        for tag, v in self.values.items():
            raw = cat.level_of(tag, v)
            cur = self.levels[tag]
            if raw > cur:
                self._up[tag] += 1
                self._down[tag] = 0
                if self._up[tag] >= CONFIRM_UP:
                    self.levels[tag], self._up[tag] = raw, 0
            elif raw < cur:
                self._down[tag] += 1
                self._up[tag] = 0
                if self._down[tag] >= CONFIRM_DOWN:
                    self.levels[tag], self._down[tag] = raw, 0
            else:
                self._up[tag] = self._down[tag] = 0
        for e in cat.EQUIPMENT:
            tags = [e.tag(s.key) for s in e.sensors]
            stale = all(ts - self.stamp.get(t, 0.0) > STALE_S for t in tags)
            self.eq_level[e.id] = 4 if stale else max((self.levels[t] for t in tags), default=0)

    def _availability(self, dt_s: float) -> None:
        for u in cat.UTILITIES:
            eqs = [e for e in cat.EQUIPMENT if e.utility == u and not e.standby]
            ok = all(self.eq_level[e.id] < 3 for e in eqs)
            self.avail[u].append(ok)
        starved = any((e.criticality == "High" and self.eq_level[e.id] == 3) or (e.category == "header" and self.eq_level[e.id] >= 2)
                      for e in cat.EQUIPMENT)
        if starved:
            self.downtime_s += dt_s

    def _manage_alerts(self, now: dt.datetime) -> None:
        anomalies = detectors.detect(self)
        seen: set = set()
        for a in anomalies:
            key = (a["equipment_id"], a["type"])
            seen.add(key)
            self._clear[key] = 0
            aid = self.active.get(key)
            if aid is None:
                self._cond[key] += 1
                if key not in self.pending and self._cond[key] >= CREATE_AFTER:
                    self.pending.add(key)
                    analysis = agent.build_analysis(a, self, now, now.timestamp(), self.stamp, self.source_label)
                    self.q.put(("create", a, analysis, now))
            else:
                al = self.alerts.get(aid)
                if al is None:
                    continue
                al["condition_cleared"] = False
                if a["level"] > LEVEL_NUM[al["severity"]] and al["status"] != "VERIFIED" and not al.get("raising") and al.get("source") != "MOCK":
                    al["raising"] = True
                    analysis = agent.build_analysis(a, self, now, now.timestamp(), self.stamp, self.source_label)
                    self.q.put(("severity", aid, a, analysis, now))
        for key in list(self._cond):
            if key not in seen:
                self._cond[key] = 0
        for key, aid in list(self.active.items()):
            al = self.alerts.get(aid)
            if al is None or key in seen or al.get("source") == "MOCK":
                continue
            self._clear[key] += 1
            if self._clear[key] == CLEAR_AFTER and not al["condition_cleared"]:
                al["condition_cleared"] = True
                self.q.put(("event", aid, "utilities-agent", "condition_cleared",
                            "Telemetry is back inside the engineering limits. Awaiting an inspection record and verification."))
            if al["status"] == "CORRECTIVE_ACTION" and self._clear[key] >= VERIFY_STABLE and not al.get("verifying"):
                al["verifying"] = True
                self.q.put(("verify", aid, "utilities-agent"))
        created = {a: dt.datetime.fromisoformat(al["created_at"]) for a, al in self.alerts.items()
                   if al["status"] == "OPEN" and al.get("source") != "MOCK"}
        for aid, c in created.items():
            al = self.alerts[aid]
            limit = ESCALATE_AFTER.get(al["severity"])
            if limit and not al["escalated"] and (now - c).total_seconds() > limit:
                al["escalated"] = True
                self.q.put(("escalate", aid, now))

    # ------------------------------------------------------------------ writer handlers (database)
    @staticmethod
    def _event_row(s, alert_id: int, actor: str, action: str, detail: str, ts: dt.datetime) -> dict:
        s.add(TwinAlertEvent(alert_id=alert_id, ts=ts, actor=actor, action=action, detail=detail))
        return {"ts": _iso(ts), "actor": actor, "action": action, "detail": detail}

    def _h_create(self, a: dict, analysis: dict, now: dt.datetime) -> None:
        key = (a["equipment_id"], a["type"])
        try:
            if key in self.active:
                return
            with SessionLocal() as s:
                row = TwinAlert(
                    created_at=now, updated_at=now, utility=a["utility"], equipment_id=a["equipment_id"], zone=a["zone"],
                    severity=a["severity"], anomaly_type=a["type"], title=a["title"][:200], actual=a["actual"][:160],
                    expected=a["expected"][:160], description=a["description"], probable_cause=a["probable_cause"],
                    cause_certainty=a["certainty"], confidence=a["confidence"], recommendation=a["recommendation"],
                    impact=a["impact"], consumers=a["consumers"], status="OPEN", source=analysis["source"], analysis=analysis,
                    evidence=a["evidence"])
                s.add(row)
                s.flush()
                row.code = f"ALT-{row.id:05d}"
                try:
                    resp = ppl.responder_for(s, a["utility"], a["zone"], now)
                except Exception:          # the roster must never stop an alert from being raised
                    log.exception("could not pick a responder")
                    resp = None
                if resp:
                    row.assigned_to = resp["name"]
                evs = [self._event_row(s, row.id, "utilities-agent", "detected", f"{a['severity']} anomaly detected by rule {a['type']}.", now),
                       self._event_row(s, row.id, "utilities-agent", "analysis_completed",
                                       f"Root cause analysis completed ({a['certainty'].lower()} cause, confidence {a['confidence']:.0%}).", now)]
                notes = []
                for role in agent.roles_for(a["severity"], a):
                    n = TwinNotification(ts=now, alert_id=row.id, recipient=role, level=a["severity"],
                                         message=f"{a['severity']}: {a['title']} ({a['equipment_id']})")
                    s.add(n)
                    notes.append(n)
                evs.append(self._event_row(s, row.id, "utilities-agent", "notified", f"Notified: {', '.join(n.recipient for n in notes)}.", now))
                if resp:
                    pn = TwinNotification(ts=now, alert_id=row.id, recipient=resp["name"], level=a["severity"],
                                          message=f"Assigned to you: {a['title']} ({a['equipment_id']})")
                    s.add(pn)
                    notes.append(pn)
                    evs.append(self._event_row(s, row.id, "utilities-agent", "auto_assigned",
                                               f"{resp['name']} ({resp['role']}, shift {resp['shift']}) is on shift for {a['zone']} and was notified.", now))
                m = TwinMaintenance(alert_id=row.id, equipment_id=a["equipment_id"], maintenance_type=a["maintenance_type"],
                                    problem=a["title"][:240], recommendation=a["recommendation"], priority=agent.PRIORITY[a["severity"]],
                                    assigned_to=resp["name"] if resp else None, status="PENDING", planned_date=now.date() + dt.timedelta(days=agent.PLANNED_DAYS[a["severity"]]),
                                    source=analysis["source"], created_at=now)
                s.add(m)
                s.flush()
                evs.append(self._event_row(s, row.id, "utilities-agent", "maintenance_created", f"Maintenance task #{m.id} created ({m.maintenance_type}).", now))
                s.commit()
                d = alert_dict(row, evs)
                d["sensors"] = a["sensors"]
                d["type"] = a["type"]
                with self.lock:
                    self.alerts[row.id] = d
                    self.active[key] = row.id
                    self.maint[m.id] = maint_dict(m)
                    for n in notes:
                        self.notifications.appendleft(note_dict(n))
                    self.version += 1
        finally:
            self.pending.discard(key)

    def _persist_alert(self, aid: int, changes: dict, event: tuple | None = None, maint: dict | None = None) -> None:
        """Write alert (and optionally its audit event and maintenance changes) to the database and the cache."""
        now = dt.datetime.now().replace(microsecond=0)
        with SessionLocal() as s:
            row = s.get(TwinAlert, aid)
            if row is None:
                raise ActionError(f"Alert {aid} not found.")
            for k, v in changes.items():
                setattr(row, k, v)
            row.updated_at = now
            ev = self._event_row(s, aid, event[0], event[1], event[2], now) if event else None
            maint_rows = []
            if maint:
                for m in s.scalars(select(TwinMaintenance).where(TwinMaintenance.alert_id == aid)):
                    for k, v in maint.items():
                        setattr(m, k, v)
                    maint_rows.append(m)
            s.commit()
            md = [maint_dict(m) for m in maint_rows]
        with self.lock:
            al = self.alerts.get(aid)
            if al is not None:
                for k, v in changes.items():
                    al[{"cause_certainty": "certainty"}.get(k, k)] = _iso(v) if isinstance(v, (dt.datetime, dt.date)) else v
                al["updated_at"] = _iso(now)
                if ev:
                    al["events"].append(ev)
            for d in md:
                self.maint[d["id"]] = d
            self.version += 1

    def _h_event(self, aid: int, actor: str, action: str, detail: str) -> None:
        self._persist_alert(aid, {}, (actor, action, detail))

    def _h_severity(self, aid: int, a: dict, analysis: dict, now: dt.datetime) -> None:
        """The condition got worse: refresh severity, readings and analysis, and notify anyone newly responsible."""
        al = self.alerts[aid]
        try:
            old = al["severity"]
            prev_steps = (al.get("analysis") or {}).get("steps", [])
            if prev_steps:
                analysis["steps"][-1] = prev_steps[-1]            # keep the verification state
            with SessionLocal() as s:
                for role in agent.roles_for(a["severity"], a):
                    if role not in agent.roles_for(old, a):
                        n = TwinNotification(ts=now, alert_id=aid, recipient=role, level=a["severity"],
                                             message=f"{a['severity']}: {a['title']} ({a['equipment_id']})")
                        s.add(n)
                        s.flush()
                        self.notifications.appendleft(note_dict(n))
                s.commit()
            self._persist_alert(
                aid, {"severity": a["severity"], "actual": a["actual"][:160], "description": a["description"], "evidence": a["evidence"],
                      "probable_cause": a["probable_cause"], "confidence": a["confidence"], "title": a["title"][:200], "impact": a["impact"], "analysis": analysis},
                ("utilities-agent", "severity_raised", f"Severity raised from {old} to {a['severity']} (reading {a['actual']})."),
                {"priority": agent.PRIORITY[a["severity"]]})
        finally:
            al["raising"] = False

    def _h_escalate(self, aid: int, now: dt.datetime) -> None:
        al = self.alerts[aid]
        role = ESCALATE_TO[al["severity"]]
        with SessionLocal() as s:
            n = TwinNotification(ts=now, alert_id=aid, recipient=role, level=al["severity"], escalated=True,
                                 message=f"ESCALATED: {al['title']} has not been acknowledged ({al['severity']}).")
            s.add(n)
            s.commit()
            nd = note_dict(n)
        with self.lock:
            self.notifications.appendleft(nd)
        self._persist_alert(aid, {}, ("utilities-agent", "escalated", f"Not acknowledged in time: escalated to {role}."))

    def _h_verify(self, aid: int, actor: str) -> None:
        try:
            self._verify(aid, actor)
        except ActionError as e:
            self._persist_alert(aid, {}, (actor, "verification_failed", str(e)))
        finally:
            al = self.alerts.get(aid)
            if al:
                al["verifying"] = False

    def _h_readings(self, rows: list[tuple]) -> None:
        with SessionLocal() as s:
            s.add_all([TwinReading(ts=ts.replace(microsecond=0), tag=t, value=v) for ts, t, v in rows])
            s.execute(delete(TwinReading).where(TwinReading.ts < dt.datetime.now() - dt.timedelta(days=RETENTION_DAYS)))
            s.commit()

    def load_from_db(self) -> None:
        """Warm the caches: equipment dates, settings, recent alerts with their audit trail, maintenance."""
        with SessionLocal() as s:
            have = {e.id for e in s.scalars(select(TwinEquipment))}
            for e in cat.EQUIPMENT:
                if e.id not in have:
                    m = self.meta[e.id]
                    s.add(TwinEquipment(id=e.id, name=e.name, utility=e.utility, category=e.category, zone=e.zone,
                                        criticality=e.criticality, last_maintenance=m["last_maintenance"], next_maintenance=m["next_maintenance"]))
            s.commit()
            for r in s.scalars(select(TwinEquipment)):
                if r.id in self.meta and r.last_maintenance:
                    self.meta[r.id] = {"last_maintenance": r.last_maintenance, "next_maintenance": r.next_maintenance}
            for st in s.scalars(select(TwinSetting)):
                if st.key == "tariffs" and st.value:
                    self.tariffs.update(st.value)
                elif st.key == "limits" and st.value:
                    cat.OVERRIDES.update(st.value)
                elif st.key == "mode" and st.value and st.value.get("mode") in ("simulation", "live"):
                    self.mode = st.value["mode"]
            rows = list(s.scalars(select(TwinAlert).order_by(TwinAlert.id.desc()).limit(500)))
            ids = [r.id for r in rows]
            events: dict[int, list] = defaultdict(list)
            if ids:
                for ev in s.scalars(select(TwinAlertEvent).where(TwinAlertEvent.alert_id.in_(ids)).order_by(TwinAlertEvent.id)):
                    events[ev.alert_id].append({"ts": _iso(ev.ts), "actor": ev.actor, "action": ev.action, "detail": ev.detail})
            maint = list(s.scalars(select(TwinMaintenance).order_by(TwinMaintenance.id.desc()).limit(500)))
            notes = list(s.scalars(select(TwinNotification).order_by(TwinNotification.id.desc()).limit(100)))
        with self.lock:
            for r in rows:
                d = alert_dict(r, events.get(r.id, []))
                d["sensors"] = [x["tag"] for x in (r.evidence or [])]
                d["type"] = r.anomaly_type
                self.alerts[r.id] = d
                if r.status != "VERIFIED":
                    self.active[(r.equipment_id, r.anomaly_type)] = r.id
            for m in maint:
                self.maint[m.id] = maint_dict(m)
            for n in reversed(notes):
                self.notifications.appendleft(note_dict(n))
            self.version += 1

    def reload_from_db(self) -> None:
        """Drop the cached alerts, tasks and notifications and read them again (used after the mock data is re-seeded)."""
        with self.lock:
            self.alerts.clear()
            self.maint.clear()
            self.notifications.clear()
            self.active.clear()
            self.pending.clear()
            self._cond.clear()
            self._clear.clear()
        self.load_from_db()

    # ------------------------------------------------------------------ user actions (synchronous)
    def act(self, aid: int, action: str, actor: str, assignee: str | None = None, comment: str | None = None) -> dict:
        al = self.alerts.get(aid)
        if al is None:
            raise ActionError(f"Alert {aid} not found.")
        if action not in ALERT_ACTIONS:
            raise ActionError(f"Unknown action '{action}'.")
        if al["status"] not in ALERT_ACTIONS[action]:
            raise ActionError(f"'{action}' is not possible while the alert is {al['status']}.")
        comment = (comment or "").strip()
        if action in ("comment", "corrective_action") and not comment:
            raise ActionError("A comment is required." if action == "comment" else "Describe the corrective action that was taken.")
        if action == "assign" and (not assignee or not self._known_assignee(assignee)):
            raise ActionError("Choose a person from the roster, or one of the teams: " + ", ".join(TEAMS) + ".")
        now = dt.datetime.now().replace(microsecond=0)
        if action == "acknowledge":
            self._persist_alert(aid, {"status": "ACKNOWLEDGED", "acknowledged_at": now}, (actor, "acknowledged", comment or "Alert acknowledged."))
        elif action == "assign":
            changes = {"status": "ASSIGNED", "assigned_to": assignee}
            if not al.get("acknowledged_at"):
                changes["acknowledged_at"] = now
            self._persist_alert(aid, changes, (actor, "assigned", f"Assigned to {assignee}." + (f" {comment}" if comment else "")),
                                {"assigned_to": assignee, "status": "ASSIGNED"})
        elif action == "investigate":
            self._persist_alert(aid, {"status": "INVESTIGATING"}, (actor, "investigating", comment or "Investigation started."),
                                {"status": "IN_PROGRESS"})
        elif action == "comment":
            self._persist_alert(aid, {}, (actor, "comment", comment))
        elif action == "corrective_action":
            self._persist_alert(aid, {"status": "CORRECTIVE_ACTION"}, (actor, "corrective_action", comment),
                                {"status": "COMPLETED", "completed_at": now, "resolution": comment})
        elif action == "verify":
            self._verify(aid, actor)
        elif action == "reopen":
            self.active[(al["equipment_id"], al["type"])] = aid
            self._persist_alert(aid, {"status": "INVESTIGATING", "closed_at": None, "verification_note": None},
                                (actor, "reopened", comment or "Alert reopened."), {"status": "IN_PROGRESS", "verified_at": None})
        return self.alerts[aid]

    @staticmethod
    def _known_assignee(name: str) -> bool:
        if name in TEAMS:
            return True
        with SessionLocal() as s:
            return s.scalar(select(TwinPerson.id).where(TwinPerson.name == name, TwinPerson.active.is_(True))) is not None

    def _telemetry_normal(self, tags: list[str]) -> tuple[bool, str]:
        for tag in tags:
            e, s = cat.SPEC[tag]
            if s.cumulative:
                continue
            if self.eq_level[e.id] == 4:
                return False, f"{e.name} is offline or not reporting."
            if self.levels[tag] != 0:
                return False, f"{e.name}: {s.label.lower()} is still outside its normal range {cat.band_text(tag)}."
            h = self.hist(tag, VERIFY_STABLE)
            if len(h) < min(VERIFY_STABLE, 10):
                return False, "Not enough fresh telemetry yet to verify recovery."
            if any(cat.level_of(tag, v) != 0 for v in h):
                return False, f"{e.name}: {s.label.lower()} was outside its limits within the last {VERIFY_STABLE} s."
        return True, ""

    def _verify(self, aid: int, actor: str) -> None:
        al = self.alerts[aid]
        if al["status"] != "CORRECTIVE_ACTION":
            raise ActionError("Record the corrective action first; recovery is verified after maintenance.")
        ok, why = self._telemetry_normal(al.get("sensors") or [x["tag"] for x in al["evidence"]])
        if not ok:
            self._persist_alert(aid, {}, (actor, "verification_failed", f"Not back to normal: {why}"))
            raise ActionError(f"Not back to normal yet. {why}")
        now = dt.datetime.now().replace(microsecond=0)
        note = f"Fresh telemetry for the last {VERIFY_STABLE} s is inside the engineering limits."
        analysis = dict(al["analysis"] or {})
        steps = [dict(x) for x in analysis.get("steps", [])]
        if steps:
            steps[-1] = {**steps[-1], "ts": _iso(now), "ok": True, "detail": f"Verified: {note}"}
        analysis["steps"] = steps
        eq = cat.BY_ID[al["equipment_id"]]
        today = now.date()
        self._persist_alert(aid, {"status": "VERIFIED", "closed_at": now, "verification_note": note, "analysis": analysis},
                            (actor, "verified", f"Recovery verified from telemetry. Alert closed. {note}"),
                            {"status": "VERIFIED", "verified_at": now})
        with SessionLocal() as s:
            row = s.get(TwinEquipment, eq.id)
            if row is not None:
                row.last_maintenance, row.next_maintenance = today, today + dt.timedelta(days=eq.maintenance_interval_days)
                s.commit()
        with self.lock:
            self.meta[eq.id] = {"last_maintenance": today, "next_maintenance": today + dt.timedelta(days=eq.maintenance_interval_days)}
            self.active.pop((al["equipment_id"], al["type"]), None)

    # ------------------------------------------------------------------ scenario and reset
    def set_mode(self, mode: str) -> dict:
        if mode not in ("simulation", "live"):
            raise ActionError("Mode must be 'simulation' or 'live'.")
        self.mode = mode
        if mode == "live":
            self.sim.reset()
        self._save_setting("mode", {"mode": mode})
        return {"mode": mode}

    def _save_setting(self, key: str, value: dict) -> None:
        with SessionLocal() as s:
            row = s.get(TwinSetting, key)
            if row is None:
                s.add(TwinSetting(key=key, value=value))
            else:
                row.value = value
            s.commit()

    def set_limit(self, tag: str, band: str, lo: float | None, hi: float | None, actor: str) -> dict:
        if tag not in cat.SPEC or cat.SPEC[tag][1].cumulative:
            raise ActionError(f"Unknown sensor '{tag}'.")
        if band not in ("normal", "warn", "crit"):
            raise ActionError("Band must be normal, warn or crit.")
        cur = {k: v for k, v in zip(("normal", "warn", "crit"), cat.bands(tag))}
        cur[band] = (lo, hi)
        n, w, c = cur["normal"], cur["warn"], cur["crit"]

        def lo_of(b, d):
            return d if (b is None or b[0] is None) else b[0]

        def hi_of(b, d):
            return d if (b is None or b[1] is None) else b[1]
        if lo is not None and hi is not None and lo > hi:
            raise ActionError("The lower limit cannot be above the upper limit.")
        if not (lo_of(c, -1e18) <= lo_of(w, -1e18) <= lo_of(n, -1e18) and hi_of(n, 1e18) <= hi_of(w, 1e18) <= hi_of(c, 1e18)):
            raise ActionError("Limits must nest: critical band outside warning band outside normal band.")
        with self.lock:
            cat.OVERRIDES.setdefault(tag, {})[band] = [lo, hi]
            self._save_setting("limits", dict(cat.OVERRIDES))
        log.info("twin limit %s.%s set to %s..%s by %s", tag, band, lo, hi, actor)
        return {"tag": tag, "limits": {k: list(b) if b else None for k, b in zip(("normal", "warn", "crit"), cat.bands(tag))}}

    def reset_demo(self) -> dict:
        """Clear the scenario and delete every SIMULATED alert, task, notification and audit event."""
        self.sim.reset()
        with SessionLocal() as s:
            alerts = [r.id for r in s.scalars(select(TwinAlert).where(TwinAlert.source == "SIMULATED"))]
            if alerts:
                s.execute(delete(TwinNotification).where(TwinNotification.alert_id.in_(alerts)))
                s.execute(delete(TwinMaintenance).where(TwinMaintenance.alert_id.in_(alerts)))
                s.execute(delete(TwinAlertEvent).where(TwinAlertEvent.alert_id.in_(alerts)))
                s.execute(delete(TwinAlert).where(TwinAlert.id.in_(alerts)))
            s.commit()
        with self.lock:
            for aid in alerts:
                self.alerts.pop(aid, None)
            self.maint = {k: v for k, v in self.maint.items() if v["alert_id"] not in alerts}
            self.notifications = deque((n for n in self.notifications if n["alert_id"] not in alerts), maxlen=300)
            self.active = {k: v for k, v in self.active.items() if v in self.alerts}
            self.pending.clear()
            self._cond.clear()
            self._clear.clear()
            self.downtime_s = 0.0
            self.version += 1
        return {"alerts_deleted": len(alerts)}

    # ------------------------------------------------------------------ read models
    def _eff(self) -> float | None:
        parts = []
        for e in cat.EQUIPMENT:
            if e.standby:
                continue
            v = self.values
            if e.category == "compressor":
                sp, nsp = v[e.tag("power_kw")] / max(v[e.tag("flow_m3min")], 0.1), 55.0 / 8.0
                parts.append(min(100.0, 100 * nsp / sp))
            elif e.category == "chiller":
                sp, nsp = v[e.tag("power_kw")] / max(v[e.tag("load_kw")], 1), 180.0 / 650.0
                parts.append(min(100.0, 100 * nsp / sp))
            elif e.category == "boiler":
                parts.append(v[e.tag("efficiency_pct")])
        return round(statistics.fmean(parts), 1) if parts else None

    def _stability(self, tags: list[str]) -> float | None:
        cvs = []
        for t in tags:
            h = self.hist(t, 300)
            if len(h) >= 20 and statistics.fmean(h):
                cvs.append(statistics.pstdev(h) / abs(statistics.fmean(h)) * 100)
        return round(max(0.0, 100 - 8 * statistics.fmean(cvs)), 1) if cvs else None

    def kpis(self) -> dict:
        now = time.monotonic()
        if self._kpi_cache and now - self._kpi_cache[0] < 2:
            return self._kpi_cache[1]
        with self.lock:
            c, t = self.sim.counters, self.tariffs
            gas = c["gas_nm3"]
            cost = c["energy_kwh"] * t["electricity"] + gas * t["gas"] + c["water_m3"] * t["water"]
            av = [100 * sum(d) / len(d) for d in self.avail.values() if d]
            alerts = list(self.alerts.values())
            active = [a for a in alerts if a["status"] != "VERIFIED"]

            def mins(a, b):
                try:
                    return (dt.datetime.fromisoformat(b) - dt.datetime.fromisoformat(a["created_at"])).total_seconds() / 60
                except (TypeError, ValueError):
                    return None
            resp = [m for a in alerts if a.get("acknowledged_at") for m in [mins(a, a["acknowledged_at"])] if m is not None]
            reso = [m for a in alerts if a.get("closed_at") for m in [mins(a, a["closed_at"])] if m is not None]
            leaks = [a for a in active if "leak" in a["type"]]
            leak_m3 = sum(((a.get("analysis") or {}).get("metrics") or {}).get("leak_est") or 0 for a in leaks)
            run = [e for e in cat.EQUIPMENT if self.eq_level[e.id] != 4 and (not e.standby or self.values.get(e.tag("flow_m3min" if e.category == "compressor" else "flow_kghr"), 0) > 0.1)]
            out = {
                "energy_kwh": round(c["energy_kwh"], 1), "cost": round(cost, 2), "currency": t["currency"],
                "since": self.started.isoformat(timespec="seconds"),
                "consumption": {"COMPRESSED_AIR": {"value": round(c["air_m3"], 0), "unit": "m3"}, "STEAM": {"value": round(c["steam_kg"], 0), "unit": "kg"},
                                "CHILLED_WATER": {"value": round(c["chilled_kwh_th"], 0), "unit": "kWh(th)"}, "COOLING_TOWER": {"value": round(c["cooling_makeup_m3"], 1), "unit": "m3"},
                                "HVAC": {"value": round(c["hvac_kwh"], 1), "unit": "kWh"}, "WATER": {"value": round(c["water_m3"], 1), "unit": "m3"},
                                "GAS": {"value": round(gas, 0), "unit": "Nm3"}},
                "availability_pct": round(statistics.fmean(av), 1) if av else None,
                "availability_by_utility": {u: round(100 * sum(d) / len(d), 1) for u, d in self.avail.items() if d},
                "equipment_total": len(cat.EQUIPMENT), "equipment_active": len(run),
                "alarms_active": len(active), "alerts_critical": sum(1 for a in active if a["severity"] == "CRITICAL"),
                "alerts_unacknowledged": sum(1 for a in active if a["status"] == "OPEN"),
                "leaks_suspected": len(leaks), "leak_est_m3min": round(leak_m3, 2),
                "efficiency_pct": self._eff(),
                "downtime_min": round(self.downtime_s / 60, 1),
                "maintenance_pending": sum(1 for m in self.maint.values() if m["status"] in ("PENDING", "ASSIGNED", "IN_PROGRESS")),
                "energy_per_unit_kwh": round(c["energy_kwh"] / c["units"], 3) if c["units"] > 1 else None,
                "units_produced": round(c["units"], 0),
                "pressure_stability_pct": self._stability(["CA-HDR-A.pressure_bar", "CA-HDR-B.pressure_bar"]),
                "temperature_stability_pct": self._stability(["CW-CHL-01.supply_c", "CW-CHL-02.supply_c"]),
                "runtime_h": round(sum(self.values[e.tag("runtime_h")] for e in cat.EQUIPMENT if e.tag("runtime_h") in self.values), 0),
                "abnormal_events": len(alerts),
                "maintenance_response_min": round(statistics.fmean(resp), 1) if resp else None,
                "resolution_min": round(statistics.fmean(reso), 1) if reso else None,
            }
        self._kpi_cache = (now, out)
        return out

    FIX_RAMP_S = 30.0

    def _effective(self) -> tuple[dict, dict, dict]:
        """What every screen reads: live values, tag levels and equipment levels, with open demo (MOCK) issues applied on top so
        the map, inspector, trends and overview show the same reading as the issue. The reading eases back to live over
        30 s after the fix is recorded, and the override ends when the issue is verified. Call with the lock held. Detectors
        keep using the raw values, so nothing is raised twice."""
        values, tag_lv, eq_lv = dict(self.values), {t: l for t, l in self.levels.items() if l}, dict(self.eq_level)
        now = dt.datetime.now()
        for a in self.alerts.values():
            if a.get("source") != "MOCK" or a["status"] == "VERIFIED":
                continue
            w = 1.0
            if a["status"] == "CORRECTIVE_ACTION":
                fix = next((e["ts"] for e in reversed(a["events"]) if e["action"] == "corrective_action"), None)
                if fix:
                    w = max(0.0, 1.0 - (now - dt.datetime.fromisoformat(fix)).total_seconds() / self.FIX_RAMP_S)
            if w <= 0:
                continue
            for ev in a.get("evidence") or []:
                tag, v = ev.get("tag"), ev.get("value")
                if tag not in values or v is None:
                    continue
                values[tag] = values[tag] + (float(v) - values[tag]) * w
                lvl = {"CRITICAL": 3, "MAJOR": 2, "WARNING": 1}.get(a["severity"], 0) if w >= 1 else cat.level_of(tag, values[tag])   # an open issue shows at its own severity
                if lvl > tag_lv.get(tag, 0):
                    tag_lv[tag] = lvl
                e = cat.SPEC[tag][0]
                if eq_lv.get(e.id, 0) != 4 and lvl > eq_lv.get(e.id, 0):
                    eq_lv[e.id] = lvl
        return values, tag_lv, eq_lv

    def snapshot(self) -> dict:
        with self.lock:
            values, tag_levels, eq_level = self._effective()
            return {
                "ts": dt.datetime.now().isoformat(timespec="seconds"), "mode": self.mode, "source": self.source_label,
                "scenario": self.sim.state(), "values": values, "levels": eq_level,
                "tag_levels": tag_levels, "version": self.version,
                "alerts": {"active": sum(1 for a in self.alerts.values() if a["status"] != "VERIFIED"),
                           "critical": sum(1 for a in self.alerts.values() if a["status"] != "VERIFIED" and a["severity"] == "CRITICAL"),
                           "unacknowledged": sum(1 for a in self.alerts.values() if a["status"] == "OPEN")},
                "kpis": self.kpis(),
            }

    def series(self, tags: list[str], minutes: int, step: int) -> dict:
        minutes = max(1, min(minutes, 7 * 24 * 60))
        step = max(1, step)
        out: dict[str, list] = {}
        if minutes <= RING // 60:
            cutoff = self._now_ts - minutes * 60
            for tag in tags:
                if tag not in self.ring:
                    continue
                buckets: dict[int, list[float]] = defaultdict(list)
                for ts, v in self.ring[tag]:
                    if ts >= cutoff:
                        buckets[int(ts // step)].append(v)
                out[tag] = [[b * step * 1000, round(statistics.fmean(vs), 3)] for b, vs in sorted(buckets.items())]
            with self.lock:                                         # a reading held by an open demo issue is drawn as that reading
                held = self._effective()[0]
                for a in self.alerts.values():
                    if a.get("source") == "MOCK" and a["status"] != "VERIFIED":
                        for ev in a.get("evidence") or []:
                            if ev.get("tag") in out and out[ev["tag"]] and abs(held[ev["tag"]] - self.values[ev["tag"]]) > 1e-9:
                                out[ev["tag"]] = [[t, round(held[ev["tag"]], 3)] for t, _ in out[ev["tag"]]]
            return out
        since = dt.datetime.now() - dt.timedelta(minutes=minutes)
        with SessionLocal() as s:
            for tag in tags:
                rows = s.execute(select(TwinReading.ts, TwinReading.value).where(TwinReading.tag == tag, TwinReading.ts >= since).order_by(TwinReading.ts)).all()
                pts = [[int(ts.timestamp() * 1000), round(v, 3)] for ts, v in rows]
                live = self.series([tag], 60, max(step, 60)).get(tag, [])
                out[tag] = pts + [p for p in live if not pts or p[0] > pts[-1][0]]
        return out

    def equipment_detail(self, eid: str) -> dict:
        e = cat.BY_ID.get(eid)
        if e is None:
            raise ActionError(f"Unknown equipment '{eid}'.")
        with self.lock:
            values, tag_lv, eq_lv = self._effective()
            sensors = []
            for s in e.sensors:
                tag = e.tag(s.key)
                sensors.append({"key": s.key, "tag": tag, "label": s.label, "unit": s.unit, "decimals": s.decimals,
                                "value": values.get(tag), "level": tag_lv.get(tag, 0), "cumulative": s.cumulative,
                                "normal": None if s.cumulative else cat.band_text(tag, "normal"),
                                "warn": None if s.cumulative else cat.band_text(tag, "warn"),
                                "crit": None if s.cumulative else cat.band_text(tag, "crit")})
            alerts = sorted((a for a in self.alerts.values()
                             if a["equipment_id"] == eid or any(t.startswith(eid + ".") for t in a.get("sensors") or [])),
                            key=lambda a: a["id"], reverse=True)
            maint = sorted((m for m in self.maint.values() if m["equipment_id"] == eid), key=lambda m: m["id"], reverse=True)
            m = self.meta[eid]
            rt = next((x["value"] for x in sensors if x["key"] == "runtime_h"), None)
            return {"id": e.id, "name": e.name, "utility": e.utility, "category": e.category, "zone": e.zone,
                    "criticality": e.criticality, "consumers": list(e.consumers), "standby": e.standby, "level": eq_lv[eid],
                    "status": cat.LEVELS[eq_lv[eid]], "runtime_h": rt, "sensors": sensors,
                    "last_maintenance": _iso(m["last_maintenance"]), "next_maintenance": _iso(m["next_maintenance"]),
                    "maintenance_interval_days": e.maintenance_interval_days,
                    "alerts": [{k: a[k] for k in ("id", "code", "severity", "status", "title", "created_at", "recommendation", "probable_cause", "certainty")} for a in alerts[:10]],
                    "maintenance": maint[:10],
                    "recommendations": [a["recommendation"] for a in alerts if a["status"] != "VERIFIED"][:3]}

    def equipment_list(self) -> list[dict]:
        """One row per equipment for the Equipment page: status, runtime, maintenance dates and open alarm count."""
        with self.lock:
            values, _tl, eq_lv = self._effective()
            out = []
            for e in cat.EQUIPMENT:
                m = self.meta[e.id]
                open_alerts = [a for a in self.alerts.values()
                               if a["status"] != "VERIFIED" and (a["equipment_id"] == e.id or any(t.startswith(e.id + ".") for t in a.get("sensors") or []))]
                out.append({"id": e.id, "level": eq_lv[e.id], "status": cat.LEVELS[eq_lv[e.id]],
                            "runtime_h": values.get(e.tag("runtime_h")),
                            "last_maintenance": _iso(m["last_maintenance"]), "next_maintenance": _iso(m["next_maintenance"]),
                            "maintenance_due": m["next_maintenance"] <= dt.date.today() + dt.timedelta(days=14),
                            "alarms": len(open_alerts)})
            return out

    def list_alerts(self, status: str = "all", limit: int = 200) -> list[dict]:
        with self.lock:
            rows = sorted(self.alerts.values(), key=lambda a: a["id"], reverse=True)
        if status == "active":
            rows = [a for a in rows if a["status"] != "VERIFIED"]
        elif status == "closed":
            rows = [a for a in rows if a["status"] == "VERIFIED"]
        return rows[:limit]


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = Engine()
    return _engine


def start_engine() -> Engine:
    eng = get_engine()
    eng.start()
    return eng


def stop_engine() -> None:
    if _engine is not None:
        _engine.stop()
