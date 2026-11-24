"""Issues: the plant team's view of an alert.

Turns the engine's alert records into the answers the team asks for: what went wrong, where, who has to go, how long it
has been open, whether it is overdue, and what to do. Reads only; actions still go through the engine so the audit trail
stays complete.
"""
from __future__ import annotations

import datetime as dt
import time

from sqlalchemy import select

from app.db.session import SessionLocal
from app.twin import catalog as cat, people as ppl
from app.twin.engine import Engine
from app.models.twin import TwinNotification

# Response targets per severity, in seconds. Acknowledge matches the escalation rule the engine already applies.
ACK_TARGET_S = {"CRITICAL": 120, "MAJOR": 300, "WARNING": 1800, "INFO": 3600}
RESOLVE_TARGET_S = {"CRITICAL": 4 * 3600, "MAJOR": 12 * 3600, "WARNING": 72 * 3600, "INFO": 7 * 86400}
STAGE = {"OPEN": "New, not acknowledged", "ACKNOWLEDGED": "Acknowledged", "ASSIGNED": "Assigned", "INVESTIGATING": "Being investigated",
         "CORRECTIVE_ACTION": "Fix done, awaiting proof", "VERIFIED": "Closed"}
SEV_RANK = {"CRITICAL": 3, "MAJOR": 2, "WARNING": 1, "INFO": 0}


def _t(v: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(v) if v else None


def _db_notifications(alert_id: int) -> list[dict]:
    with SessionLocal() as s:
        rows = s.scalars(select(TwinNotification).where(TwinNotification.alert_id == alert_id).order_by(TwinNotification.ts))
        return [{"ts": r.ts.isoformat(timespec="seconds"), "recipient": r.recipient, "level": r.level, "message": r.message, "escalated": r.escalated} for r in rows]


def _secs(a: dt.datetime | None, b: dt.datetime | None) -> int | None:
    return int((b - a).total_seconds()) if a and b else None


def issue_view(al: dict, people: dict[str, dict], maint: dict | None, now: dt.datetime, detail: bool = False,
               notes: list[dict] | None = None) -> dict:
    created, ack, closed = _t(al["created_at"]), _t(al.get("acknowledged_at")), _t(al.get("closed_at"))
    is_open = al["status"] != "VERIFIED"
    sev = al["severity"]
    age = _secs(created, now if is_open else closed)
    unacked = _secs(created, now) if (is_open and ack is None) else None
    escalated = any(e["action"] == "escalated" for e in al.get("events", []))
    ack_over = bool(unacked and unacked > ACK_TARGET_S.get(sev, 1800))
    res_over = bool(is_open and age is not None and age > RESOLVE_TARGET_S.get(sev, 72 * 3600))
    eq = cat.BY_ID.get(al["equipment_id"])
    who = people.get(al.get("assigned_to") or "")
    last = (al.get("events") or [None])[-1]
    out = {
        "id": al["id"], "code": al["code"], "title": al["title"], "severity": sev, "status": al["status"], "stage": STAGE.get(al["status"], al["status"]),
        "open": is_open, "utility": al["utility"], "utility_label": cat.UTILITY_LABEL.get(al["utility"], al["utility"]), "source": al.get("source"),
        "where": {"zone": al["zone"], "equipment_id": al["equipment_id"], "equipment_name": eq.name if eq else al["equipment_id"],
                  "consumers": al.get("consumers") or []},
        "what": {"actual": al["actual"], "expected": al["expected"], "description": al["description"], "probable_cause": al["probable_cause"],
                 "certainty": al.get("certainty"), "confidence": al.get("confidence"), "impact": al["impact"]},
        "todo": al["recommendation"],
        "who": ({"name": who["name"], "role": who["role"], "team": who["team"], "shift": who["shift"], "shift_hours": ppl.SHIFT_HOURS.get(who["shift"], ""),
                 "phone_ext": who["phone_ext"], "on_shift_now": ppl.is_on_shift(who, now)}
                if who else {"name": al.get("assigned_to"), "role": None, "team": None, "shift": None, "shift_hours": "", "phone_ext": None, "on_shift_now": None}),
        "time": {"created_at": al["created_at"], "age_s": age, "acknowledged_at": al.get("acknowledged_at"), "time_to_ack_s": _secs(created, ack),
                 "closed_at": al.get("closed_at"), "unacknowledged_for_s": unacked, "ack_target_s": ACK_TARGET_S.get(sev), "resolve_target_s": RESOLVE_TARGET_S.get(sev),
                 "overdue_by_s": (age - RESOLVE_TARGET_S[sev]) if res_over else None},
        "flags": {"unacknowledged_late": ack_over, "overdue": res_over, "escalated": escalated, "needs_attention": is_open and (ack_over or res_over or escalated)},
        "task": ({"id": maint["id"], "status": maint["status"], "priority": maint["priority"], "planned_date": maint["planned_date"], "type": maint["maintenance_type"],
                  "resolution": maint.get("resolution")} if maint else None),
        "last_event": {"ts": last["ts"], "actor": last["actor"], "action": last["action"], "detail": last["detail"]} if last else None,
    }
    if detail:
        evs, prev = [], created
        for e in al.get("events", []):
            ts = _t(e["ts"])
            evs.append({**e, "after_start_s": _secs(created, ts), "since_previous_s": _secs(prev, ts)})
            prev = ts or prev
        out["timeline"] = evs
        out["evidence"] = al.get("evidence") or []
        out["analysis"] = al.get("analysis")
        out["resolution"] = (maint or {}).get("resolution")
        out["notifications"] = notes if notes is not None else _db_notifications(al["id"])
    return out


_PEOPLE: tuple[float, dict[str, dict]] | None = None
PEOPLE_TTL_S = 30


def clear_people_cache() -> None:
    global _PEOPLE
    _PEOPLE = None


def _people() -> dict[str, dict]:
    """The roster by name. Cached briefly: it changes rarely, and the database round trip is the slow part."""
    global _PEOPLE
    now = time.monotonic()
    if _PEOPLE is None or now - _PEOPLE[0] > PEOPLE_TTL_S:
        with SessionLocal() as s:
            _PEOPLE = (now, {p["name"]: p for p in ppl.load_people(s)})
    return _PEOPLE[1]


def _context(eng: Engine) -> tuple[dict[str, dict], dict[int, dict]]:
    with eng.lock:
        maint_by_alert = {m["alert_id"]: dict(m) for m in eng.maint.values() if m["alert_id"] is not None}
    return _people(), maint_by_alert


def _sort_key(r: dict) -> tuple:
    """Open issues first, those needing attention at the top, then the most severe, then the oldest. Closed ones newest first."""
    if r["open"]:
        return (0, 0 if r["flags"]["needs_attention"] else 1, -SEV_RANK.get(r["severity"], 0), -(r["time"]["age_s"] or 0))
    closed = r["time"]["closed_at"]
    return (1, 0, 0, -(dt.datetime.fromisoformat(closed).timestamp() if closed else 0))


def list_issues(eng: Engine, status: str = "all", severity: str | None = None, zone: str | None = None,
                assignee: str | None = None, limit: int = 300) -> list[dict]:
    now = dt.datetime.now()
    people, maint = _context(eng)
    with eng.lock:
        alerts = [dict(a) for a in eng.alerts.values()]
    rows = [issue_view(a, people, maint.get(a["id"]), now) for a in alerts]
    if status == "open":
        rows = [r for r in rows if r["open"]]
    elif status == "closed":
        rows = [r for r in rows if not r["open"]]
    if severity:
        rows = [r for r in rows if r["severity"] == severity.upper()]
    if zone:
        rows = [r for r in rows if r["where"]["zone"] == zone]
    if assignee:
        rows = [r for r in rows if r["who"]["name"] == assignee]
    rows.sort(key=_sort_key)
    return rows[:limit]


def issue_detail(eng: Engine, alert_id: int) -> dict | None:
    people, maint = _context(eng)
    with eng.lock:
        al = eng.alerts.get(alert_id)
        al = {**al, "events": list(al["events"])} if al else None
        notes = [dict(n) for n in eng.notifications if n["alert_id"] == alert_id]
    if al is None:
        return None
    # the engine keeps recent notifications in memory; older issues read theirs from the database
    return issue_view(al, people, maint.get(alert_id), dt.datetime.now(), detail=True, notes=list(reversed(notes)) or None)


def summary(eng: Engine) -> dict:
    rows = list_issues(eng, "all", limit=1000)
    openr = [r for r in rows if r["open"]]
    closed = [r for r in rows if not r["open"]]
    month_ago = dt.datetime.now() - dt.timedelta(days=30)
    recent = [r for r in closed if r["time"]["closed_at"] and dt.datetime.fromisoformat(r["time"]["closed_at"]) >= month_ago]
    acks = [r["time"]["time_to_ack_s"] for r in recent if r["time"]["time_to_ack_s"] is not None]
    durs = [r["time"]["age_s"] for r in recent if r["time"]["age_s"] is not None]
    avg = lambda v: int(sum(v) / len(v)) if v else None      # noqa: E731
    by_zone: dict[str, int] = {}
    by_person: dict[str, int] = {}
    for r in openr:
        by_zone[r["where"]["zone"]] = by_zone.get(r["where"]["zone"], 0) + 1
        if r["who"]["name"]:
            by_person[r["who"]["name"]] = by_person.get(r["who"]["name"], 0) + 1
    return {
        "open": len(openr), "needs_attention": sum(r["flags"]["needs_attention"] for r in openr),
        "unacknowledged": sum(r["status"] == "OPEN" for r in openr), "overdue": sum(r["flags"]["overdue"] for r in openr),
        "by_severity": {s: sum(r["severity"] == s for r in openr) for s in ("CRITICAL", "MAJOR", "WARNING", "INFO")},
        "closed_30d": len(recent), "avg_time_to_acknowledge_s": avg(acks), "avg_time_to_resolve_s": avg(durs),
        "open_by_zone": by_zone, "open_by_person": by_person,
    }


def roster(eng: Engine) -> list[dict]:
    now = dt.datetime.now()
    people = list(_people().values())
    open_by: dict[str, int] = {}
    with eng.lock:
        for a in eng.alerts.values():
            if a["status"] != "VERIFIED" and a.get("assigned_to"):
                open_by[a["assigned_to"]] = open_by.get(a["assigned_to"], 0) + 1
    return [{**p, "shift_hours": ppl.SHIFT_HOURS.get(p["shift"], ""), "on_shift_now": ppl.is_on_shift(p, now), "open_issues": open_by.get(p["name"], 0)} for p in people]
