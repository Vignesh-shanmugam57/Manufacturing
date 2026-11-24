"""What the agent did: a feed of its recorded actions (detections, hand-offs to the person on shift, escalations, clearings and
verifications), with summary counts. Built from the audit trail every issue already keeps, so it can never disagree with
the Issues board. Read only: the agent has no action that operates equipment, and the count of those is always 0."""
from __future__ import annotations

import datetime as dt

from app.twin.engine import Engine

AGENT = "utilities-agent"
KIND = {"detected": "detected", "escalated": "escalated", "severity_raised": "raised", "condition_cleared": "cleared",
        "verified": "verified", "verification_failed": "failed"}


def _t(v: str) -> dt.datetime:
    return dt.datetime.fromisoformat(v)


def activity(eng: Engine, days: int = 7, limit: int = 40) -> dict:
    now = dt.datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = now - dt.timedelta(days=max(1, min(int(days), 30)))
    with eng.lock:
        alerts = [{**a, "events": list(a["events"])} for a in eng.alerts.values()]
    feed: list[dict] = []
    counts = {"detected": 0, "handed_off": 0, "escalated": 0, "verified": 0}
    for a in alerts:
        evs = a["events"]
        handed = next((e for e in evs if e["action"] == "auto_assigned"), None)
        who = handed["detail"].split(" is on shift")[0] if handed else None
        for e in evs:
            if e["actor"] != AGENT or e["action"] not in KIND:
                continue
            ts = _t(e["ts"])
            kind = KIND[e["action"]]
            if ts >= today:
                counts["detected"] += kind == "detected"
                counts["handed_off"] += kind == "detected" and bool(who)
                counts["escalated"] += kind == "escalated"
                counts["verified"] += kind == "verified"
            if ts < since:
                continue
            where = f"{a['zone']}, {a['severity'].lower()}."
            head, sub = {
                "detected": (f"Detected: {a['title']}", f"{where}" + (f" Sent to {who}." if who else "")),
                "escalated": (f"Escalated: {a['title']}", e["detail"].replace("Not acknowledged in time: ", "").rstrip(".").capitalize() + "."),
                "raised": (f"Got worse: {a['title']}", e["detail"]),
                "cleared": (f"Readings back inside limits: {a['equipment_id']}", "Waiting for the fix to be recorded and confirmed."),
                "verified": (f"Verified: {a['title']}", "Fresh readings inside the limits. Closed."),
                "failed": (f"Not back to normal yet: {a['title']}", e["detail"]),
            }[kind]
            feed.append({"ts": e["ts"], "kind": kind, "title": head, "text": sub, "issue_id": a["id"], "code": a["code"], "severity": a["severity"]})
    feed.sort(key=lambda x: x["ts"], reverse=True)
    return {"as_of": now.isoformat(timespec="seconds"), "days": days, "today": counts, "actions_on_equipment": 0, "feed": feed[:limit]}
