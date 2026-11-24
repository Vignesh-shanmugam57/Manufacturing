"""The agent workflow for one anomaly: collect, validate, map, detect, root cause, impact, recommend, alert, verify.

Everything here is deterministic and traceable to the readings in the evidence list. Causes are PROBABLE unless a
status signal proves them. The agent never produces an instruction to operate equipment, only a recommendation.
"""
from __future__ import annotations

import datetime as dt
import statistics

from app.twin import catalog as cat

NOTIFY = {"WARNING": ["maintenance"], "MAJOR": ["facilities", "maintenance"],
          "CRITICAL": ["facilities", "maintenance", "plant_manager"]}
PRIORITY = {"WARNING": "LOW", "MAJOR": "HIGH", "CRITICAL": "URGENT"}
PLANNED_DAYS = {"WARNING": 3, "MAJOR": 1, "CRITICAL": 0}


def roles_for(severity: str, anomaly: dict) -> list[str]:
    roles = list(NOTIFY.get(severity, ["maintenance"]))
    if anomaly.get("safety") and "safety_officer" not in roles:      # gas safety alarms always reach the safety officer
        roles.append("safety_officer")
    return roles


def validate(view, tags: list[str], now_ts: float, stale: dict[str, float]) -> dict:
    checks, issues = [], 0
    for tag in tags:
        e, s = cat.SPEC[tag]
        v = view.values.get(tag)
        age = now_ts - stale.get(tag, 0.0)
        ok_present = v is not None
        ok_fresh = ok_present and age <= 15
        ok_range = ok_present and v >= 0 and (s.nominal == 0 or v <= max(abs(s.nominal) * 10, 50))
        h = view.hist(tag, 30)
        stuck = bool(s.noise and len(h) >= 25 and len(set(h)) == 1)
        bad = not (ok_present and ok_fresh and ok_range) or stuck
        issues += bad
        checks.append({"tag": tag, "label": f"{e.name}: {s.label}", "ok": not bad,
                       "detail": "missing" if not ok_present else "stale" if not ok_fresh else "out of physical range" if not ok_range
                       else "value stuck (possible sensor fault)" if stuck else "present, fresh, plausible"})
    return {"checks": checks, "issues": issues, "quality": "GOOD" if issues == 0 else "DEGRADED"}


def build_analysis(a: dict, view, now: dt.datetime, now_ts: float, stamps: dict[str, float], source: str) -> dict:
    """The analysis timeline stored with the alert and shown on the AI analysis page."""
    t = now.isoformat(timespec="seconds")
    e = cat.BY_ID[a["equipment_id"]]
    q = validate(view, a["sensors"], now_ts, stamps)
    roles = roles_for(a["severity"], a)
    explanation = explain(a)
    return {
        "source": source,
        "explanation": explanation,
        "confidence": a["confidence"], "certainty": a["certainty"],
        "metrics": {"leak_est": a.get("leak_est")},
        "steps": [
            {"key": "collected", "title": "Data collected", "ts": t, "ok": True,
             "detail": f"{len(a['sensors'])} sensor tags read from the {source} source (last 60 s window)."},
            {"key": "validated", "title": "Sensor readings validated", "ts": t, "ok": q["quality"] == "GOOD",
             "detail": "All readings present, fresh and plausible." if q["issues"] == 0
             else f"{q['issues']} reading(s) failed validation; confidence is reduced.", "checks": q["checks"]},
            {"key": "mapped", "title": "Equipment mapped", "ts": t, "ok": True,
             "detail": f"{e.name} ({e.id}) · {cat.UTILITY_LABEL[e.utility]} · {e.zone} · criticality {e.criticality}.",
             "consumers": list(a["consumers"])},
            {"key": "detected", "title": "Abnormal condition detected", "ts": t, "ok": True,
             "detail": a["description"], "rule": a["type"], "evidence": a["evidence"]},
            {"key": "root_cause", "title": "Root cause analysis completed", "ts": t, "ok": True,
             "detail": a["probable_cause"], "certainty": a["certainty"], "confidence": a["confidence"]},
            {"key": "impact", "title": "Production impact assessed", "ts": t, "ok": True, "detail": a["impact"]},
            {"key": "recommended", "title": "Recommendation generated", "ts": t, "ok": True, "detail": a["recommendation"]},
            {"key": "alerted", "title": "Alert sent", "ts": t, "ok": True,
             "detail": f"{a['severity']} alert raised and sent to: {', '.join(roles)}.", "roles": roles},
            {"key": "verification", "title": "Maintenance verification", "ts": None, "ok": None,
             "detail": "Pending: verification needs a recorded corrective action and fresh telemetry within limits."},
        ],
    }


def explain(a: dict) -> str:
    """Plain-language explanation built only from the evidence. No LLM needed for threshold violations."""
    ev = [x for x in a["evidence"] if x["value"] is not None]
    bits = []
    for x in ev[:5]:
        flag = {0: "", 1: " (outside normal)", 2: " (abnormal)", 3: " (critical)"}.get(x["level"], "")
        v = f"{x['value']:.2f}".rstrip("0").rstrip(".")
        bits.append(f"{x['label'].lower()} {v} {x['unit']}".strip() + flag)
    cert = ("This cause is confirmed by a status signal; the reason behind it still needs inspection."
            if a["certainty"] == "CONFIRMED" else
            "This is a probable cause inferred from the readings, not a confirmed fault.")
    return (f"{a['title']}. Supporting readings: {'; '.join(bits)}. {a['probable_cause']} {cert} "
            f"Recommended action: {a['recommendation']}")
