"""Advisory alerts raised by the agent or the monitoring scan, and their human workflow.

OPEN -> ACKNOWLEDGED -> RESOLVED are set by people. VERIFIED is set only by a telemetry check
(verify_return_to_normal), never by hand. Nothing here operates any equipment.
"""
from __future__ import annotations

import datetime as dt
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UtilityAlert
from app.services import analytics as an

OPEN_STATUSES = ("OPEN", "ACKNOWLEDGED")
ALL_STATUSES = ("OPEN", "ACKNOWLEDGED", "RESOLVED", "VERIFIED")


def _now() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


def alert_dict(a: UtilityAlert) -> dict:
    return {"id": a.id, "created_at": a.created_at, "status": a.status, "severity": a.severity,
            "utility_type": a.utility_type, "plant_id": a.plant_id, "zone": a.zone, "category": a.category,
            "title": a.title, "details": a.details, "recommendation": a.recommendation,
            "assigned_to": a.assigned_to, "source": a.source, "acknowledged_at": a.acknowledged_at,
            "resolved_at": a.resolved_at, "verified_at": a.verified_at, "status_note": a.status_note}


def create_alert(s: Session, *, utility_type: str, title: str, severity: str, category: str = "agent_finding",
                 details: str = "", recommendation: str = "", plant_id: str | None = None, zone: str | None = None,
                 assigned_to: str = "maintenance", source: str = "agent") -> tuple[UtilityAlert, bool]:
    """Create an advisory alert. Returns (alert, created); an identical open alert is returned, not duplicated."""
    ut = an.resolve_utility(s, utility_type)
    if ut is None:
        raise ValueError("utility_type is required for an alert.")
    pl, zn = an.resolve_plant(s, plant_id), an.resolve_zone(s, zone)
    severity = severity.upper().strip()
    if severity not in an.SEVERITY_RANK:
        raise ValueError(f"severity must be one of {list(an.SEVERITY_RANK)}")
    q = select(UtilityAlert).where(UtilityAlert.status.in_(OPEN_STATUSES), UtilityAlert.utility_type == ut,
                                   UtilityAlert.category == category)
    q = q.where(UtilityAlert.plant_id == pl) if pl else q.where(UtilityAlert.plant_id.is_(None))
    q = q.where(UtilityAlert.zone == zn) if zn else q.where(UtilityAlert.zone.is_(None))
    dup = s.scalars(q).first()
    if dup:
        return dup, False
    alert = UtilityAlert(utility_type=ut, plant_id=pl, zone=zn, category=category, severity=severity,
                         title=title[:200], details=details, recommendation=recommendation,
                         assigned_to=assigned_to or "maintenance", source=source, created_at=_now())
    s.add(alert)
    s.commit()
    return alert, True


def list_alerts(s: Session, status: str = "open", utility_type: str | None = None) -> dict:
    q = select(UtilityAlert).order_by(UtilityAlert.created_at.desc(), UtilityAlert.id.desc())
    st = (status or "open").upper()
    if st == "OPEN":
        q = q.where(UtilityAlert.status.in_(OPEN_STATUSES))
    elif st != "ALL":
        if st not in ALL_STATUSES:
            raise ValueError(f"status must be open, all, or one of {ALL_STATUSES}")
        q = q.where(UtilityAlert.status == st)
    ut = an.resolve_utility(s, utility_type) if utility_type else None
    if ut:
        q = q.where(UtilityAlert.utility_type == ut)
    rows = [alert_dict(a) for a in s.scalars(q.limit(50))]
    return {"status_filter": status, "count": len(rows), "alerts": rows}


_TRANSITIONS = {"OPEN": {"ACKNOWLEDGED", "RESOLVED"}, "ACKNOWLEDGED": {"RESOLVED", "OPEN"},
                "RESOLVED": {"OPEN"}, "VERIFIED": {"OPEN"}}


def update_alert_status(s: Session, alert_id: int, status: str, note: str = "", by: str = "user") -> dict:
    a = s.get(UtilityAlert, int(alert_id))
    if a is None:
        raise ValueError(f"Alert {alert_id} not found.")
    new = status.upper()
    if new not in _TRANSITIONS.get(a.status, set()):
        raise ValueError(f"Cannot move alert {a.id} from {a.status} to {new}.")
    now = _now()
    a.status, a.updated_by = new, by
    a.status_note = note or a.status_note
    if new == "ACKNOWLEDGED":
        a.acknowledged_at = now
    elif new == "RESOLVED":
        a.resolved_at = now
        a.acknowledged_at = a.acknowledged_at or now
    s.commit()
    return alert_dict(a)


def assign_alert(s: Session, alert_id: int, assignee: str, by: str = "user") -> dict:
    """Give an open alert to a team or person. A verified alert is closed and cannot be reassigned."""
    a = s.get(UtilityAlert, int(alert_id))
    if a is None:
        raise ValueError(f"Alert {alert_id} not found.")
    if a.status == "VERIFIED":
        raise ValueError(f"Alert {a.id} is verified and closed, so it cannot be reassigned.")
    a.assigned_to, a.updated_by = assignee.strip(), by
    s.commit()
    return alert_dict(a)


def verify_return_to_normal(s: Session, alert_id: int, hours: int = 48) -> dict:
    """Check the latest readings of the alert's utility/plant/zone: no abnormal pattern or alarm cluster, and no
    alarm among the latest readings (a stray alarm earlier in the window is normal). VERIFIED only if people set it RESOLVED."""
    a = s.get(UtilityAlert, int(alert_id))
    if a is None:
        raise ValueError(f"Alert {alert_id} not found.")
    end = an._need_data(s)
    hours = max(6, min(int(hours), 240))
    rows = an._select(an.utility_rows(s), a.utility_type, a.plant_id, a.zone, start=end - dt.timedelta(hours=hours))
    if len(rows) < 3:
        return {"alert_id": a.id, "status": a.status, "normal": None, "readings": len(rows),
                "message": f"Only {len(rows)} reading(s) in the last {hours} h for this scope; not enough to verify."}
    alarms = sum(1 for r in rows if r.is_alarm)
    latest_alarm = any(r.is_alarm for r in rows[-3:])          # still alarming right now?
    findings = an.detect_abnormal_usage(s, days=max(1, math.ceil(hours / 24)), utility_type=a.utility_type,
                                        plant_id=a.plant_id, zone=a.zone)["anomalies"]
    still = [f for f in findings if f["utility_type"] == a.utility_type]
    normal = not latest_alarm and not still
    if normal and a.status == "RESOLVED":
        a.status, a.verified_at, a.updated_by = "VERIFIED", _now(), "utilities-agent"
        a.status_note = f"Return to normal verified from the last {hours} h of telemetry ({len(rows)} readings)."
        s.commit()
        msg = "Telemetry is back to normal; alert marked VERIFIED."
    elif normal:
        msg = (f"Telemetry looks normal, but the alert is {a.status}. It will be VERIFIED once it is marked "
               "RESOLVED and the check is repeated.")
    else:
        msg = "Not back to normal yet; keep the alert open."
    return {"alert_id": a.id, "title": a.title, "status": a.status, "normal": normal, "window_hours": hours,
            "readings": len(rows), "alarms_in_window": alarms, "alarm_in_latest_readings": latest_alarm,
            "still_abnormal": [f["description"] for f in still],
            "message": msg}
