"""Tools that let the chat agent answer the plant team's questions from the same facts the Issues board, Plant map and
Plant overview show: what is wrong, where, who has to go, how long it has been open, what to do, who is on shift, and
whether usage is normal. All read only: the agent cannot acknowledge, assign or change anything here. Use the Issues page."""
from __future__ import annotations

import datetime as dt
import json
import re

from langchain_core.tools import tool

from app.twin import catalog as cat
from app.twin import issues as iss
from app.twin import usage as use
from app.twin.engine import get_engine


def _j(obj) -> str:
    return json.dumps(obj, default=str, separators=(",", ":"))


def _ago(sec) -> str:
    if sec is None:
        return "unknown"
    s = max(0, int(sec))
    d, h, m = s // 86400, (s % 86400) // 3600, (s % 3600) // 60
    return f"{d}d {h}h" if d else f"{h}h {m}m" if h else f"{m}m"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _utility_code(text: str) -> str | None:
    """COMPRESSED_AIR from 'compressed air', 'air', 'COMPRESSED_AIR'."""
    n = _norm(text)
    if not n:
        return None
    for code in cat.UTILITIES:
        if n in (_norm(code), _norm(cat.UTILITY_LABEL[code])):
            return code
    for code in cat.UTILITIES:
        if n in _norm(code) or n in _norm(cat.UTILITY_LABEL[code]):
            return code
    return None


def _brief(i: dict) -> dict:
    who = i["who"]
    return {
        "id": i["id"], "code": i["code"], "severity": i["severity"], "stage": i["stage"], "title": i["title"],
        "utility": i["utility_label"], "zone": i["where"]["zone"], "equipment": i["where"]["equipment_name"],
        "reading": f"{i['what']['actual']} (expected {i['what']['expected']})",
        "owner": (f"{who['name']}, {who['role']}, ext {who['phone_ext']}, shift {who['shift']}" + ("" if who["on_shift_now"] is not False else " (shift has ended)")) if who["name"] else "nobody assigned",
        "open_for": _ago(i["time"]["age_s"]), "acknowledged_after": _ago(i["time"]["time_to_ack_s"]) if i["time"]["time_to_ack_s"] is not None else "not acknowledged",
        "flags": [k for k, v in i["flags"].items() if v and k != "needs_attention"], "needs_attention": i["flags"]["needs_attention"],
        "what_to_do": i["todo"],
    }


@tool
def get_plant_status() -> str:
    """The status of every utility right now (compressed air, steam, chilled water, cooling tower, HVAC, water, gas): level,
    key reading and open issue count, plus the issues that need attention first. Start here for 'what is wrong now',
    'how is the plant' or 'what needs attention' questions."""
    eng = get_engine()
    ov = use.overview(eng)
    levels = ["Normal", "Warning", "Major", "Critical"]
    return _j({"as_of": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "open_issues": ov["open"],
               "utilities": [{"utility": u["label"], "status": levels[min(u["level"], 3)], "reading": u["reading"], "open_issues": u["open_issues"]} for u in ov["utilities"]],
               "needs_attention_first": [{"code": a["id"], "title": a["title"], "severity": a["severity"], "zone": a["zone"], "owner": a["who"], "open_for": _ago(a["age_s"])} for a in ov["attention"]]})


@tool
def list_open_issues(severity: str = "", zone: str = "", utility: str = "", owner: str = "") -> str:
    """Open issues, most urgent first, each with what is wrong (reading vs expected), where (zone and equipment), who has to go
    (name, role, extension, whether their shift has ended), how long it has been open, flags (escalated, not acknowledged
    in time, overdue) and what to do. Filters, all optional: severity CRITICAL, MAJOR or WARNING; zone e.g. 'Gas Station';
    utility e.g. 'chilled water'; owner a person's name."""
    eng = get_engine()
    code = _utility_code(utility)
    rows = iss.list_issues(eng, "open", severity or None, zone or None, owner or None)
    if utility and code:
        rows = [r for r in rows if r["utility"] == code]
    return _j({"count": len(rows), "issues": [_brief(r) for r in rows[:15]]}) if rows else "No open issues match."


@tool
def get_issue(issue: str) -> str:
    """The full story of one issue: what happened, probable cause, impact, where, who, notified people, the maintenance task and
    the timeline of every action with times. `issue` is its code (for example ALT-00067) or number. Also works for closed issues."""
    eng = get_engine()
    m = re.search(r"\d+", str(issue))
    if not m:
        return "ERROR: give the issue code, for example ALT-00067."
    num = int(m.group())
    aid = num if num in eng.alerts else next((a["id"] for a in eng.alerts.values() if a["code"] and a["code"].endswith(f"{num:05d}")), None)
    d = iss.issue_detail(eng, aid) if aid is not None else None
    if d is None:
        return f"No issue found for '{issue}'."
    out = _brief(d)
    out.update({"cause": d["what"]["probable_cause"], "impact": d["what"]["impact"], "supplies": d["where"]["consumers"],
                "notified": sorted({n["recipient"] for n in d.get("notifications", [])}),
                "task": d["task"] and {"type": d["task"]["type"], "priority": d["task"]["priority"], "status": d["task"]["status"], "planned": d["task"]["planned_date"]},
                "fix_recorded": d.get("resolution"),
                "timeline": [f"+{_ago(e['after_start_s'])} {e['actor']}: {e['detail']}" for e in d["timeline"][-14:]]})
    return _j(out)


@tool
def get_team_on_shift(zone: str = "", team: str = "") -> str:
    """Who is on shift right now, with role, team, extension, the zones they cover and how many issues they hold. Optional filters:
    zone (for example 'Gas Station') shows only people who cover it; team (for example 'maintenance', 'safety', 'facilities').
    Also lists people who still own open issues but whose shift has ended, so a handover can be arranged."""
    eng = get_engine()
    people = iss.roster(eng)
    now = dt.datetime.now()

    def covers(p):
        return not zone or "*" in p["zones"] or zone.lower() in [z.lower() for z in p["zones"]]

    def match(p):
        return not team or _norm(team) in _norm(p["team"]) or _norm(team) in _norm(p["role"])

    on = [p for p in people if p["on_shift_now"] and covers(p) and match(p)]
    handover = [p for p in people if not p["on_shift_now"] and p["open_issues"] > 0]
    show = lambda p: {"name": p["name"], "role": p["role"], "team": p["team"], "ext": p["phone_ext"], "shift": p["shift_hours"],  # noqa: E731
                      "zones": "all zones" if "*" in p["zones"] else p["zones"], "open_issues": p["open_issues"]}
    return _j({"now": now.strftime("%H:%M"), "on_shift": [show(p) for p in on],
               "shift_ended_but_still_own_open_issues": [{"name": p["name"], "role": p["role"], "ext": p["phone_ext"], "open_issues": p["open_issues"], "their_shift": p["shift_hours"]} for p in handover]})


@tool
def get_usage_vs_normal(utility: str) -> str:
    """Usage of one utility today against yesterday and its normal range, the last 7 days, the peak hour and an energy cost estimate
    where there is an electricity meter. utility: compressed air, steam, chilled water, cooling tower, HVAC, water or gas.
    The usage figures come from a usage model (mock data); say so briefly when quoting numbers."""
    code = _utility_code(utility)
    if not code:
        return "ERROR: choose one of: " + ", ".join(cat.UTILITY_LABEL.values()) + "."
    u = use.usage(get_engine(), code)
    h = u["now_hour"]
    now_v, band = u["today"][-1], u["normal"][h]
    where = "above" if now_v > band["hi"] else "below" if now_v < band["lo"] else "within"
    return _j({"utility": u["label"], "measure": f"{u['what']} ({u['unit']})", "now": now_v, "normal_range_now": [band["lo"], band["hi"]], "position": f"{where} the normal range",
               "vs_same_time_yesterday_pct": u["vs_yesterday_pct"], "peak_hour_today": u["peak_hour"],
               "last_7_days_totals": [{d["label"]: d["total"]} for d in u["days"]], "average_previous_days": u["average_prior_days"],
               "energy_today": u["energy"], "explanation": u["note"], "related_issue": u["issue"],
               "reading_behind_the_issue": u["signal"] and {"reading": u["signal"]["label"], "now": f"{u['signal']['actual']:g} {u['signal']['unit']}", "limit": u["signal"]["expected"], "since": u["signal"]["since"]},
               "source": "usage model (mock data)"})


@tool
def get_issue_history(days: int = 30) -> str:
    """How issues have gone over the last days (default 30): how many were closed, average time to acknowledge and to close, which
    equipment and utilities have the most problems, and the slowest ones to close. Use it for 'what keeps going wrong' and
    'how quickly do we respond' questions."""
    eng = get_engine()
    cutoff = dt.datetime.now() - dt.timedelta(days=max(1, min(int(days or 30), 90)))
    rows = [r for r in iss.list_issues(eng, "all", limit=1000) if dt.datetime.fromisoformat(r["time"]["created_at"]) >= cutoff]
    closed = [r for r in rows if not r["open"]]
    acks = [r["time"]["time_to_ack_s"] for r in closed if r["time"]["time_to_ack_s"] is not None]
    durs = [r["time"]["age_s"] for r in closed if r["time"]["age_s"] is not None]
    by_eq: dict[str, list] = {}
    by_u: dict[str, int] = {}
    for r in rows:
        by_eq.setdefault(r["where"]["equipment_name"], []).append(r)
        by_u[r["utility_label"]] = by_u.get(r["utility_label"], 0) + 1
    avg = lambda v: _ago(sum(v) / len(v)) if v else "n/a"          # noqa: E731
    return _j({"days": days, "issues_raised": len(rows), "closed": len(closed), "still_open": len(rows) - len(closed),
               "average_time_to_acknowledge": avg(acks), "average_time_to_close": avg(durs),
               "most_issues_by_equipment": sorted(({"equipment": k, "issues": len(v), "zone": v[0]["where"]["zone"]} for k, v in by_eq.items()), key=lambda x: -x["issues"])[:5],
               "issues_by_utility": dict(sorted(by_u.items(), key=lambda kv: -kv[1])),
               "slowest_to_close": [{"code": r["code"], "title": r["title"], "took": _ago(r["time"]["age_s"])} for r in sorted(closed, key=lambda r: -(r["time"]["age_s"] or 0))[:3]]})


PLANT_TOOLS = [get_plant_status, list_open_issues, get_issue, get_team_on_shift, get_usage_vs_normal, get_issue_history]
