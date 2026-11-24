"""Monitoring scan: turn deterministic findings into de-duplicated advisory alerts.

Runs without the LLM, so it can be scheduled (cron / Task Scheduler / Domo workflow):
    uv run python cli.py --scan   (from backend/)
Alerts go to facilities/maintenance. Nothing here (or anywhere in the agent) actuates equipment.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.services import alerts as al
from app.services import analytics as an


def _owner(category: str, metric: str, utility_type: str) -> str:
    if category == "alarm_cluster":
        return "maintenance"
    if metric == "flow" or utility_type == "HVAC":
        return "facilities"
    return "maintenance"


def run_scan(s: Session, days: int = 7) -> dict:
    created, existing = [], []

    def push(**kw):
        alert, is_new = al.create_alert(s, source="scan", **kw)
        (created if is_new else existing).append(alert)

    result = an.detect_abnormal_usage(s, days=days)
    for f in result["anomalies"]:
        if an.SEVERITY_RANK[f["severity"]] < an.SEVERITY_RANK["MEDIUM"]:
            continue
        push(utility_type=f["utility_type"], plant_id=f["plant_id"], zone=f["zone"],
             category=f"{f['type']}:{f['metric']}", severity=f["severity"], title=f["description"],
             details=json.dumps({"evidence": f["evidence"], "likely_cause": f["likely_cause"]}, default=str),
             recommendation=f["recommendation"], assigned_to=_owner(f["type"], f["metric"], f["utility_type"]))

    corr = an.downtime_correlation(s) if an.downtime_rows(s) else None
    for x in (corr or {}).get("by_utility_type", []):
        if x["verdict"] == "possible link":
            push(utility_type=x["utility_type"], category="downtime_link", severity="MEDIUM",
                 title=f"{x['utility_type'].replace('_', ' ').title()}: downtime starts more often after its alarms "
                       f"(lift {x['lift']})",
                 details=json.dumps(x, default=str),
                 recommendation="Review utility alarm history against the downtime log with maintenance and production.",
                 assigned_to="maintenance")

    return {"as_of": result["as_of"], "created_count": len(created), "already_open_count": len(existing),
            "created": [al.alert_dict(a) for a in created], "already_open_ids": [a.id for a in existing],
            "conclusion": ("Scan complete: no abnormal patterns needing an alert." if not (created or existing)
                           else f"{len(created)} alert(s) raised, {len(existing)} already open.")}
