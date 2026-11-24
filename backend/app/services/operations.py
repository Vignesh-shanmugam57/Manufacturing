"""Plant operations summary: energy and cost, production and downtime, maintenance (CMMS), quality, utilities and the
issue workflow.

Read-only. Every number is computed from the rows stored in the database (Neon). The window is counted back from the
latest operations reading, so the answer does not depend on the clock. A single day can be chosen from the last seven
days; then every windowed figure covers only that calendar day.
"""
from __future__ import annotations

import datetime as dt
import statistics
from collections import Counter, defaultdict

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import (AssetMachine, EnergyReading, MaintenanceOrder, NcrRecord, Plant, ProductionLine,
                        ProductionRecord, QualityInspection, UtilityAlert, UtilityReading)
from app.services.analytics import memoized

UTILITY_AREAS = {"COMPRESSOR", "CHILLER", "HVAC"}     # energy areas that are utilities themselves
UTILITY_LABELS = {"COMPRESSED_AIR": "Compressed air", "NITROGEN": "Nitrogen", "CHILLED_WATER": "Chilled water",
                  "HVAC": "HVAC", "PROCESS_WATER": "Process water"}
CLOSED_CAPA = {"CLOSED", "VERIFIED"}
ALERT_OPEN = ("OPEN", "ACKNOWLEDGED")
SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
DAYS_BACK = 7                                          # the day filter covers the last seven days of data
MIN_SERIES = 4                                         # fewest readings a plant-zone series needs for a variation figure


def _r(x, n: int = 1):
    return None if x is None else round(float(x), n)


def as_of(s: Session) -> dt.datetime | None:
    """The latest operations reading: the 'now' every window is counted back from."""
    ends = [v for v in (s.scalar(select(func.max(EnergyReading.ts))),
                        s.scalar(select(func.max(ProductionRecord.ts))),
                        s.scalar(select(func.max(QualityInspection.inspection_ts)))) if v is not None]
    return max(ends) if ends else None


def day_options(end: dt.datetime) -> list[dict]:
    """The days the filter offers: the latest day of data and the six before it, newest first."""
    out = []
    for i in range(DAYS_BACK):
        day = end.date() - dt.timedelta(days=i)
        out.append({"date": day.isoformat(), "label": day.strftime("%d %b")})
    return out


def _window(end: dt.datetime, days: int, day: str | None) -> tuple[dt.datetime, dt.datetime]:
    """[lo, hi): one calendar day when a day is chosen, otherwise the last `days` days up to the latest reading."""
    if day:
        lo = dt.datetime.combine(dt.date.fromisoformat(day), dt.time.min)
        return lo, lo + dt.timedelta(days=1)
    return end - dt.timedelta(days=days), end + dt.timedelta(seconds=1)


def _names(s: Session) -> tuple[dict, dict, dict]:
    plants = {p.plant_id: p.plant_name for p in s.scalars(select(Plant))}
    lines = {l.line_id: l.line_type for l in s.scalars(select(ProductionLine))}
    machines = {m.machine_id: m.machine_name for m in s.scalars(select(AssetMachine))}
    return plants, lines, machines


def _energy(s: Session, lo: dt.datetime, hi: dt.datetime, plants: dict) -> dict:
    rows = s.execute(select(EnergyReading.plant_id, EnergyReading.area, func.sum(EnergyReading.consumption_kwh),
                            func.sum(EnergyReading.cost_inr), func.sum(EnergyReading.co2e_kg))
                     .where(EnergyReading.ts >= lo, EnergyReading.ts < hi)
                     .group_by(EnergyReading.plant_id, EnergyReading.area)).all()
    by_area = [{"plant_id": p, "plant_name": plants.get(p, p), "area": a, "utility": a in UTILITY_AREAS,
                "kwh": _r(k, 0), "cost_inr": _r(c, 0), "co2e_kg": _r(e, 0)}
               for p, a, k, c, e in rows]
    by_area.sort(key=lambda x: -(x["kwh"] or 0))
    kwh_plant: dict[str, float] = defaultdict(float)
    for x in by_area:
        kwh_plant[x["plant_id"]] += x["kwh"] or 0
    good = dict(s.execute(select(ProductionRecord.plant_id, func.sum(ProductionRecord.good_qty))
                          .where(ProductionRecord.ts >= lo, ProductionRecord.ts < hi)
                          .group_by(ProductionRecord.plant_id)).all())
    per_unit = [{"plant_id": p, "plant_name": plants.get(p, p), "kwh": _r(kwh_plant[p], 0), "good_units": _r(good[p], 0),
                 "kwh_per_good_unit": _r(kwh_plant[p] / good[p], 2)}
                for p in sorted(kwh_plant) if good.get(p)]
    return {"total_kwh": _r(sum(kwh_plant.values()), 0),
            "total_cost_inr": _r(sum(x["cost_inr"] or 0 for x in by_area), 0),
            "total_co2e_kg": _r(sum(x["co2e_kg"] or 0 for x in by_area), 0),
            "by_area": by_area, "kwh_per_good_unit": per_unit}


def _production(s: Session, lo: dt.datetime, hi: dt.datetime, plants: dict, lines: dict) -> dict:
    rows = s.execute(select(ProductionRecord.plant_id, ProductionRecord.line_id, func.sum(ProductionRecord.target_qty),
                            func.sum(ProductionRecord.actual_qty), func.sum(ProductionRecord.good_qty),
                            func.sum(ProductionRecord.reject_qty), func.sum(ProductionRecord.downtime_min))
                     .where(ProductionRecord.ts >= lo, ProductionRecord.ts < hi)
                     .group_by(ProductionRecord.plant_id, ProductionRecord.line_id)).all()
    out_lines = []
    for p, l, target, actual, good, reject, down in rows:
        out_lines.append({"plant_id": p, "plant_name": plants.get(p, p), "line_id": l, "line_type": lines.get(l, ""),
                          "target": _r(target, 0), "actual": _r(actual, 0), "good": _r(good, 0), "reject": _r(reject, 0),
                          "yield_pct": _r(100 * good / actual) if actual else None, "downtime_min": _r(down, 0)})
    out_lines.sort(key=lambda x: (x["plant_id"], x["line_id"]))
    reasons = s.execute(select(ProductionRecord.downtime_reason, func.sum(ProductionRecord.downtime_min), func.count())
                        .where(ProductionRecord.ts >= lo, ProductionRecord.ts < hi,
                               ProductionRecord.downtime_reason.not_in(["NONE", ""]))
                        .group_by(ProductionRecord.downtime_reason)
                        .order_by(func.sum(ProductionRecord.downtime_min).desc())).all()
    return {"lines": out_lines,
            "downtime_reasons": [{"reason": r, "minutes": _r(m, 0), "events": n} for r, m, n in reasons]}


def _maintenance(s: Session, end: dt.datetime, machines: dict) -> dict:
    """A snapshot of the work orders and each machine against its planned service interval (not day-based)."""
    by_status = dict(s.execute(select(MaintenanceOrder.status, func.count())
                               .group_by(MaintenanceOrder.status)).all())
    by_type = dict(s.execute(select(MaintenanceOrder.maintenance_type, func.count())
                             .group_by(MaintenanceOrder.maintenance_type)).all())
    failures = s.execute(select(MaintenanceOrder.failure_mode, func.count())
                         .where(MaintenanceOrder.failure_mode.not_in(["N/A", ""]))
                         .group_by(MaintenanceOrder.failure_mode)
                         .order_by(func.count().desc()).limit(6)).all()
    avoided = s.scalar(select(func.sum(MaintenanceOrder.downtime_avoided_estimate_min))
                       .where(MaintenanceOrder.status == "COMPLETED"))
    last_done = dict(s.execute(select(MaintenanceOrder.machine_id, func.max(MaintenanceOrder.actual_start))
                               .where(MaintenanceOrder.status == "COMPLETED")
                               .group_by(MaintenanceOrder.machine_id)).all())
    open_orders = dict(s.execute(select(MaintenanceOrder.machine_id, func.count())
                                 .where(MaintenanceOrder.status != "COMPLETED")
                                 .group_by(MaintenanceOrder.machine_id)).all())
    register = []
    overdue = []
    for a in s.scalars(select(AssetMachine).order_by(AssetMachine.machine_id)):
        last = last_done.get(a.machine_id)
        due = last + dt.timedelta(days=a.planned_maintenance_interval_days) if (last and a.planned_maintenance_interval_days) else None
        row = {"machine_id": a.machine_id, "machine_name": a.machine_name, "line_id": a.line_id, "criticality": a.criticality,
               "interval_days": a.planned_maintenance_interval_days,
               "last_completed": last.isoformat(timespec="minutes") if last else None,
               "next_due": due.isoformat(timespec="minutes") if due else None,
               "open_orders": open_orders.get(a.machine_id, 0)}
        register.append(row)
        if a.planned_maintenance_interval_days and (due is None or due < end):
            overdue.append(row)
    overdue.sort(key=lambda x: (x["criticality"] or "Z", x["machine_id"]))
    return {"orders_by_status": by_status, "orders_by_type": by_type,
            "top_failure_modes": [{"failure_mode": f, "orders": n} for f, n in failures],
            "downtime_avoided_min": _r(avoided, 0), "register": register,
            "overdue_service": overdue}


def _quality(s: Session, end: dt.datetime, lo: dt.datetime, hi: dt.datetime, plants: dict) -> dict:
    per_plant = s.execute(select(QualityInspection.plant_id, func.count(),
                                 func.sum(case((QualityInspection.result == "PASS", 1), else_=0)))
                          .where(QualityInspection.inspection_ts >= lo, QualityInspection.inspection_ts < hi)
                          .group_by(QualityInspection.plant_id)).all()
    top_defects = s.execute(select(QualityInspection.defect_code, func.count())
                            .where(QualityInspection.result == "FAIL",
                                   QualityInspection.defect_code.not_in(["NONE", ""]),
                                   QualityInspection.inspection_ts >= lo, QualityInspection.inspection_ts < hi)
                            .group_by(QualityInspection.defect_code)
                            .order_by(func.count().desc()).limit(5)).all()
    ncr_status = dict(s.execute(select(NcrRecord.capa_status, func.count()).group_by(NcrRecord.capa_status)).all())
    due_day = end.date()
    overdue_rows = s.scalars(select(NcrRecord).where(NcrRecord.capa_status.not_in(list(CLOSED_CAPA)),
                                                     NcrRecord.capa_due_date < due_day)
                             .order_by(NcrRecord.capa_due_date).limit(5)).all()
    overdue_n = s.scalar(select(func.count()).select_from(NcrRecord).where(
        NcrRecord.capa_status.not_in(list(CLOSED_CAPA)), NcrRecord.capa_due_date < due_day)) or 0
    return {"by_plant": [{"plant_id": p, "plant_name": plants.get(p, p), "inspections": n, "pass": int(ok or 0),
                          "pass_rate_pct": _r(100 * (ok or 0) / n) if n else None}
                         for p, n, ok in sorted(per_plant)],
            "top_defects": [{"defect_code": d, "fails": n} for d, n in top_defects],
            "ncr_by_status": ncr_status,
            "capa_overdue": overdue_n,
            "capa_overdue_list": [{"ncr_id": r.ncr_id, "defect_code": r.defect_code, "owner_id": r.owner_id,
                                   "capa_due_date": r.capa_due_date.isoformat() if r.capa_due_date else None,
                                   "capa_status": r.capa_status} for r in overdue_rows]}


def _stability(series: list[list[float]]) -> float | None:
    """100 minus 8 times the variation of each series (coefficient of variation), averaged. Same rule as the live view."""
    scores = []
    for h in series:
        if len(h) >= MIN_SERIES and statistics.fmean(h):
            scores.append(max(0.0, 100 - 8 * statistics.pstdev(h) / abs(statistics.fmean(h)) * 100))
    return _r(statistics.fmean(scores)) if scores else None


def _variation(series: list[list[float]]) -> float | None:
    """Variation of each series as a percentage of its mean (coefficient of variation), averaged. Lower is steadier."""
    cvs = [statistics.pstdev(h) / abs(statistics.fmean(h)) * 100 for h in series if len(h) >= MIN_SERIES and statistics.fmean(h)]
    return _r(statistics.fmean(cvs)) if cvs else None


def _utilities(s: Session, lo: dt.datetime, hi: dt.datetime) -> dict:
    """Per utility: how often it was normal, its alarms, and how steady its pressure and temperature were."""
    rows = s.execute(select(UtilityReading.utility_type, UtilityReading.plant_id, UtilityReading.zone,
                            UtilityReading.pressure_bar, UtilityReading.temperature_c, UtilityReading.operating_status,
                            UtilityReading.alarm_code)
                     .where(UtilityReading.ts >= lo, UtilityReading.ts < hi)).all()
    groups: dict = defaultdict(lambda: {"n": 0, "normal": 0, "alarms": Counter(),
                                        "pressure": defaultdict(list), "temp": defaultdict(list)})
    for u, plant, z, p, t, status, alarm in rows:
        g = groups[u]
        g["n"] += 1
        if (status or "NORMAL") == "NORMAL":
            g["normal"] += 1
        if alarm and alarm != "NONE":
            g["alarms"][alarm] += 1
        series_key = (plant, z)                 # one series per plant and zone, so each day's series has ~24 readings
        if p is not None:
            g["pressure"][series_key].append(p)
        if t is not None:
            g["temp"][series_key].append(t)
    out = []
    for u in sorted(groups):
        g = groups[u]
        out.append({"utility": u, "label": UTILITY_LABELS.get(u, u), "readings": g["n"],
                    "availability_pct": _r(100 * g["normal"] / g["n"]) if g["n"] else None,
                    "pressure_stability_pct": _stability(list(g["pressure"].values())),
                    "temperature_stability_pct": _stability(list(g["temp"].values())),
                    "pressure_variation_pct": _variation(list(g["pressure"].values())),
                    "temperature_variation_pct": _variation(list(g["temp"].values())),
                    "alarms": dict(g["alarms"].most_common())})
    return {"by_utility": out}


def _workflow(s: Session) -> dict:
    """The issue workflow: what is open, who owns it, and how long acknowledging and resolving take."""
    alerts = list(s.scalars(select(UtilityAlert)))

    def hours(a, b):
        return (b - a).total_seconds() / 3600 if a and b else None

    ack = [h for a in alerts if (h := hours(a.created_at, a.acknowledged_at)) is not None]
    res = [h for a in alerts if (h := hours(a.created_at, a.resolved_at)) is not None]
    open_items = sorted((a for a in alerts if a.status in ALERT_OPEN),
                        key=lambda a: (-SEVERITY_RANK.get(a.severity, 0), a.created_at or dt.datetime.min))
    return {"by_status": dict(Counter(a.status for a in alerts)),
            "open_by_owner": dict(Counter(a.assigned_to for a in alerts if a.status in ALERT_OPEN).most_common()),
            "avg_hours_to_acknowledge": _r(statistics.fmean(ack)) if ack else None,
            "avg_hours_to_resolve": _r(statistics.fmean(res)) if res else None,
            "open": [{"id": a.id, "title": a.title, "severity": a.severity, "status": a.status, "owner": a.assigned_to,
                      "utility_type": a.utility_type, "recommendation": a.recommendation,
                      "created_at": a.created_at.isoformat(timespec="minutes") if a.created_at else None}
                     for a in open_items[:10]]}


@memoized   # the aggregate queries; only an upload or a clear can change the answer
def _plant_core(s: Session, days: int, day: str | None) -> dict:
    end = as_of(s)
    if end is None:
        return {"empty": True, "message": "No plant operations data loaded yet. Upload the files in docs/ first."}
    days = max(1, min(int(days), 120))
    if day:
        chosen = dt.date.fromisoformat(day)
        first = end.date() - dt.timedelta(days=DAYS_BACK - 1)
        if not (first <= chosen <= end.date()):
            raise ValueError(f"Choose a day in the last {DAYS_BACK} days of data ({first.isoformat()} to {end.date().isoformat()}).")
    lo, hi = _window(end, days, day)
    plants, lines, machines = _names(s)
    return {"empty": False, "as_of": end.isoformat(timespec="minutes"), "day": day,
            "days": 1 if day else days, "day_options": day_options(end),
            "energy": _energy(s, lo, hi, plants),
            "production": _production(s, lo, hi, plants, lines),
            "maintenance": _maintenance(s, end, machines),
            "quality": _quality(s, end, lo, hi, plants),
            "utilities": _utilities(s, lo, hi)}


def plant_summary(s: Session, days: int = 30, day: str | None = None) -> dict:
    """The plant summary, for the last `days` days or for one chosen day. The issue workflow is read fresh each time,
    because alerts change without touching the data cache."""
    core = _plant_core(s, days, day)
    if core.get("empty"):
        return core
    core["workflow"] = _workflow(s)
    return core
