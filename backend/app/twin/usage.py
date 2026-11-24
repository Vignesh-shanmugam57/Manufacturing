"""Plant overview: the status of every utility right now, and its usage against normal.

The usage numbers come from a small mock model (a day-shaped curve with a little noise, lower at weekends) because the
plant has no metered history for all seven utilities. The model follows the issues: while an issue is open (or was open
in the last days) the affected utility deviates from normal, so the chart tells the same story as the Issues board.
Everything is computed when asked, so "today" is always today. Read only; nothing here operates equipment.
"""
from __future__ import annotations

import datetime as dt
import math

from app.twin import catalog as cat
from app.twin import issues as iss
from app.twin.engine import ActionError, Engine

TARIFF_INR_PER_KWH = 8.25          # the average the plant data implies

# base: typical load at the middle of the day; kwh: electricity per unit of usage (None = fuel or not metered)
MODEL = {
    "COMPRESSED_AIR": dict(what="Air used", unit="m³/h", base=480.0, kwh=0.11, key="CA-HDR-A.pressure_bar"),
    "STEAM": dict(what="Steam used", unit="kg/h", base=1800.0, kwh=None, key="ST-HDR-01.pressure_bar"),
    "CHILLED_WATER": dict(what="Cooling load", unit="kW", base=650.0, kwh=0.25, key="CW-CHL-01.delta_t_c"),
    "COOLING_TOWER": dict(what="Heat rejected", unit="kW", base=900.0, kwh=None, key="CT-TWR-01.outlet_c"),
    "HVAC": dict(what="Airflow", unit="m³/h", base=16000.0, kwh=0.002, key="HV-AHU-01.airflow_m3hr"),
    "WATER": dict(what="Water used", unit="m³/h", base=38.0, kwh=0.25, key="WT-TNK-01.level_pct"),
    "GAS": dict(what="Gas used", unit="Nm³/h", base=210.0, kwh=None, key="GS-SKD-01.lel_pct"),
}
# how much an issue of this kind moves usage while it lasts (positive = more than normal)
DEVIATION = {
    "compressed_air_leakage": 0.18, "steam_pressure_instability": 0.12, "chilled_water_low_delta_t": 0.22,
    "cooling_tower_fan_failure": -0.25, "hvac_airflow_imbalance": -0.10, "water_leak": 0.15,
    "gas_abnormal_consumption": 0.90, "limit_breach": 0.0,        # a reading outside its limit says nothing about how much is used
}
RAMP_S = 1800.0                    # the deviation builds up over half an hour


def _shape(h: float) -> float:
    return 0.62 + 0.38 * max(0.0, math.sin((h - 5) / 14 * math.pi))


def _normal(utility: str, day: dt.date, hour: int) -> float:
    seed = sum(map(ord, utility)) % 7
    noise = 1 + 0.035 * math.sin(hour * 1.7 + day.toordinal() * 1.3 + seed) + 0.02 * math.sin(hour * 0.6 + day.toordinal() * 2.1 + seed)
    return MODEL[utility]["base"] * _shape(hour) * noise * (0.82 if day.weekday() >= 5 else 1.0)


def _deviation(issues: list[dict], when: dt.datetime) -> float:
    """The combined deviation from normal at a moment, from the issues that were open then."""
    total = 0.0
    for a in issues:
        start = dt.datetime.fromisoformat(a["created_at"])
        end = dt.datetime.fromisoformat(a["closed_at"]) if a.get("closed_at") else None
        if when < start or (end is not None and when >= end):
            continue
        total += DEVIATION.get(a["type"], 0.08) * min(1.0, (when - start).total_seconds() / RAMP_S)
    return total


def _value(utility: str, day: dt.date, hour: int, issues: list[dict], with_issues: bool = True) -> float:
    base = _normal(utility, day, hour)
    if not with_issues:
        return base
    return max(0.0, base * (1 + _deviation(issues, dt.datetime.combine(day, dt.time(hour, 30)))))


def _issues_for(eng: Engine, utility: str) -> list[dict]:
    with eng.lock:
        return [dict(a) for a in eng.alerts.values() if a["utility"] == utility]


def _signal(a: dict, cur: int, today: dt.date) -> dict | None:
    """The reading behind an open issue against its limit, hour by hour today: inside the limit until the issue started, then out."""
    ev = (a.get("evidence") or [None])[0]
    if not ev or ev.get("value") is None or ev["tag"] not in cat.SPEC:
        return None
    tag = ev["tag"]
    lo, hi = cat.bands(tag)[0] or (None, None)
    actual = float(ev["value"])
    mid = (lo + hi) / 2 if lo is not None and hi is not None else hi * 0.5 if hi is not None else lo * 1.2 if lo is not None else actual * 0.8
    span = (hi - lo) if (lo is not None and hi is not None) else (abs(mid) * 0.2 or 1.0)
    start = dt.datetime.fromisoformat(a["created_at"])
    dec = cat.SPEC[tag][1].decimals
    pts = []
    for h in range(cur + 1):
        t = dt.datetime.combine(today, dt.time(h, 30))
        w = 0.0 if t < start else min(1.0, (t - start).total_seconds() / RAMP_S)
        pts.append(round(mid + 0.04 * span * math.sin(h * 1.9 + 3) + (actual - mid) * w, dec))
    return {"tag": tag, "label": f"{ev['equipment']}: {ev['label']}", "unit": ev["unit"], "lo": lo, "hi": hi, "actual": actual,
            "expected": cat.band_text(tag, "normal"), "points": pts, "since": a["created_at"], "level": ev.get("level", 0)}


def usage(eng: Engine, utility: str) -> dict:
    if utility not in MODEL:
        raise ActionError(f"Unknown utility '{utility}'.")
    m = MODEL[utility]
    now = dt.datetime.now()
    today, yday = now.date(), now.date() - dt.timedelta(days=1)
    cur = now.hour
    issues = _issues_for(eng, utility)
    r1 = lambda v: round(v, 1)       # noqa: E731
    today_v = [r1(_value(utility, today, h, issues)) for h in range(cur + 1)]
    yest_v = [r1(_value(utility, yday, h, issues)) for h in range(24)]
    band = [{"lo": r1(_normal(utility, today, h) * 0.9), "hi": r1(_normal(utility, today, h) * 1.1)} for h in range(24)]
    days = []
    for back in range(6, -1, -1):
        d = today - dt.timedelta(days=back)
        hours = range(cur + 1) if back == 0 else range(24)
        days.append({"date": d.isoformat(), "label": "Today" if back == 0 else d.strftime("%a"), "partial": back == 0,
                     "total": r1(sum(_value(utility, d, h, issues) for h in hours)), "hours": len(list(hours))})
    prior = [x["total"] for x in days[:-1]]
    same_y = sum(yest_v[: cur + 1])
    kwh = sum(today_v) * m["kwh"] if m["kwh"] else None
    open_issues = sorted((a for a in issues if a["status"] != "VERIFIED"), key=lambda a: -iss.SEV_RANK.get(a["severity"], 0))
    note, issue_ref, signal = "Within the normal range.", None, None
    if open_issues:
        a = open_issues[0]
        dev = DEVIATION.get(a["type"], 0.08)
        since = dt.datetime.fromisoformat(a["created_at"])
        when = f"since {since:%H:%M}" if since.date() == today else f"since {since:%d %b}"
        signal = _signal(a, cur, today)
        if dev == 0.0 and signal:                      # a reading outside its limit, not a change in usage
            note = (f"{signal['label']} is {signal['actual']:g} {signal['unit']}, outside its limit of {signal['expected']} {when}. "
                    f"Usage itself is normal. Open issue: {a['title']}.")
        else:
            note = f"Usage is about {abs(dev) * 100:.0f}% {'above' if dev > 0 else 'below'} normal {when}. Open issue: {a['title']}."
        issue_ref = {"id": a["id"], "title": a["title"], "severity": a["severity"]}
    return {
        "utility": utility, "label": cat.UTILITY_LABEL[utility], "what": m["what"], "unit": m["unit"], "now_hour": cur,
        "today": today_v, "yesterday": yest_v, "normal": band, "days": days,
        "average_prior_days": r1(sum(prior) / len(prior)) if prior else None,
        "vs_yesterday_pct": round((sum(today_v) / same_y - 1) * 100, 1) if same_y else None,
        "peak_hour": today_v.index(max(today_v)) if today_v else None,
        "energy": {"kwh": round(kwh), "cost_inr": round(kwh * TARIFF_INR_PER_KWH), "estimated": True} if kwh else None,
        "note": note, "issue": issue_ref, "signal": signal, "source": "MOCK",
    }


def overview(eng: Engine) -> dict:
    """One status per utility (live readings and open issues together) and the issues that need attention first."""
    rows = iss.list_issues(eng, "open")
    by_u: dict[str, list[dict]] = {}
    for r in rows:
        by_u.setdefault(r["utility"], []).append(r)
    with eng.lock:
        values, eq_level = dict(eng.values), dict(eng.eq_level)
    out = []
    for u in cat.UTILITIES:
        live = max([0] + [0 if eq_level.get(e.id, 0) == 4 else eq_level.get(e.id, 0) for e in cat.EQUIPMENT if e.utility == u])
        issues = by_u.get(u, [])
        level = max([live] + [iss.SEV_RANK.get(r["severity"], 0) for r in issues])
        key = MODEL[u]["key"]
        e, s = cat.SPEC[key]
        v = values.get(key)
        live_text = f"{v:.{s.decimals}f} {s.unit}".strip() if v is not None else "-"
        out.append({
            "utility": u, "label": cat.UTILITY_LABEL[u], "level": level, "open_issues": len(issues),
            "reading": issues[0]["what"]["actual"] if issues else live_text,
            "reading_label": issues[0]["where"]["equipment_name"] if issues else s.label,
            "worst_issue": {"id": issues[0]["id"], "title": issues[0]["title"]} if issues else None,
        })
    attention = [{"id": r["id"], "title": r["title"], "severity": r["severity"], "zone": r["where"]["zone"], "who": r["who"]["name"],
                  "age_s": r["time"]["age_s"], "needs_attention": r["flags"]["needs_attention"]} for r in rows[:3]]
    return {"utilities": out, "attention": attention, "open": len(rows)}
