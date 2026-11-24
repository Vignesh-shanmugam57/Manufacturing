"""Deterministic utility analytics on the uploaded CSV data.

The LLM never calculates these numbers. Tools call these functions and the model explains the results,
so every figure in an answer traces back to rows in PostgreSQL. All functions are read-only.

Notes on the source data this module is written for:
  * utility readings are hourly but sparse: each plant/utility/zone series has a reading about every 4 hours;
  * consumption_unit changes from row to row for the same utility, so flow_rate is treated as a relative
    load index (compared with itself over time), never summed across rows into an absolute volume;
  * the data has no site-engineered operating limits, so "abnormal" means statistically different from the
    series' own history, plus the alarms the plant itself raised.
"""
from __future__ import annotations

import copy
import datetime as dt
import difflib
import functools
import math
import statistics
import threading
import time
from collections import Counter, defaultdict, namedtuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DataUpload, DowntimeEvent, MachineReading, UtilityReading

# --------------------------------------------------------------------------- tunables
BASELINE_MIN_N = 30          # readings needed in the baseline for a series to be tested
RECENT_MIN_N = 8             # readings needed in the recent window
Z_THRESHOLD = 3.0            # Welch z needed for a level shift of a whole utility
Z_SERIES = 3.5               # stricter for the 40 single plant/zone series (many tests -> fewer false alarms)
ALARM_P_UTILITY = 0.005      # Poisson tail probability for an alarm cluster, utility level
ALARM_P_SERIES = 0.0005      # ...and per series
MIN_CHANGE_PCT = {"flow": 10.0, "pressure": 5.0, "temperature": 10.0}
MAX_ITEMS = 25
SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
STATUS_RANK = {"NORMAL": 0, "WATCH": 1, "ALARM": 2}

UtilRow = namedtuple("UtilRow", "ts plant utype zone flow pressure temp unit equip status alarm is_alarm")
MachRow = namedtuple("MachRow", "ts plant machine line state is_anomaly")
DownRow = namedtuple("DownRow", "ts plant machine line minutes reason impact maint status")

_ALIASES = {
    "AIR": "COMPRESSED_AIR", "CA": "COMPRESSED_AIR", "COMPRESSOR": "COMPRESSED_AIR", "COMPRESSORS": "COMPRESSED_AIR",
    "CHW": "CHILLED_WATER", "CHILLER": "CHILLED_WATER", "CHILLERS": "CHILLED_WATER",
    "AC": "HVAC", "AHU": "HVAC", "AIR_CONDITIONING": "HVAC",
    "WATER": "PROCESS_WATER", "PW": "PROCESS_WATER", "N2": "NITROGEN",
}

ADVICE = {  # utility -> (what a flow rise usually means, what to inspect)
    "COMPRESSED_AIR": "air leaks or open blow-offs / tools left pressurised",
    "CHILLED_WATER": "chiller or heat-exchanger fouling, or a stuck-open control valve",
    "HVAC": "schedule/setpoint drift or filters and dampers out of adjustment",
    "PROCESS_WATER": "a leak, an open valve or a rinse/cleaning cycle running longer than needed",
    "NITROGEN": "purge flows left on or a leak downstream of the meter",
}


# =========================================================================== helpers
def _r(x, n: int = 2):
    return None if x is None else round(float(x), n)


def _mean(v):
    return sum(v) / len(v) if v else None


def _sd(v) -> float:
    return statistics.stdev(v) if len(v) > 1 else 0.0


def _pct(new, old):
    return None if (new is None or not old) else (new - old) / abs(old) * 100.0      # a series with no recent readings has no change to report


def _linreg(ys: list[float]) -> float:
    """Slope of y against 0..n-1."""
    n = len(ys)
    if n < 2:
        return 0.0
    mx, my = (n - 1) / 2, sum(ys) / n
    den = sum((i - mx) ** 2 for i in range(n))
    return sum((i - mx) * (y - my) for i, y in enumerate(ys)) / den


def _floor_hour(ts: dt.datetime) -> dt.datetime:
    return ts.replace(minute=0, second=0, microsecond=0)


# --- row cache -------------------------------------------------------------------------------------------
# Reading 55k rows from a remote PostgreSQL (Neon) takes many seconds, so the rows are cached in the server process
# and dropped on every upload (invalidate_cache). At most every CACHE_TTL_S seconds the cache is re-validated with
# one cheap query: the upload log plus the newest reading of each table. That is how other workers, and anything
# that writes readings straight into the database (a live feed), show up on the dashboard within seconds.
CACHE_TTL_S = 10.0
#
# The finished analyses (health board, trends, anomalies, ...) are cached the same way (see `memoized`): they
# are a pure function of these rows, so they stay valid until the data changes. Without this every request
# recomputed them, and each database round trip to Neon costs about a second.
_cache: dict = {"version": None, "checked": 0.0, "u": None, "m": None, "d": None, "memo": {}, "gen": 0}
_cache_lock = threading.RLock()


def invalidate_cache() -> None:
    with _cache_lock:
        _cache.update(version=None, checked=0.0, u=None, m=None, d=None, memo={}, gen=_cache["gen"] + 1)


def _fresh(s: Session) -> None:
    now = time.monotonic()
    with _cache_lock:
        if _cache["version"] is not None and now - _cache["checked"] < CACHE_TTL_S:
            return
        version = tuple(s.execute(select(
            select(func.max(DataUpload.id)).scalar_subquery(),
            select(func.max(UtilityReading.ts)).scalar_subquery(),
            select(func.max(MachineReading.ts)).scalar_subquery(),
            select(func.max(DowntimeEvent.start_ts)).scalar_subquery(),
        )).one())
        if version != _cache["version"]:
            _cache.update(version=version, u=None, m=None, d=None, memo={}, gen=_cache["gen"] + 1)
        _cache["checked"] = now


def memoized(fn):
    """Cache a read-only analysis until the data changes (an upload, a clear, or a change seen in the upload log).

    Nothing in these analyses reads the clock (the "now" is the latest reading), so the result is a pure function of
    the cached rows. Callers get a deep copy because some of them add fields to what they receive. A call that
    raises is not cached, and a result computed while the data changed underneath it is not stored.
    """
    @functools.wraps(fn)
    def wrapper(s: Session, *args, **kwargs):
        key = (fn.__name__, args, tuple(sorted(kwargs.items())))
        try:
            hash(key)
        except TypeError:                       # unhashable argument: just compute
            return fn(s, *args, **kwargs)
        with _cache_lock:
            _fresh(s)
            if key in _cache["memo"]:
                return copy.deepcopy(_cache["memo"][key])
            gen = _cache["gen"]
        result = fn(s, *args, **kwargs)
        with _cache_lock:
            if _cache["gen"] == gen:
                _cache["memo"][key] = result
        return copy.deepcopy(result)
    return wrapper


def utility_rows(s: Session) -> list[UtilRow]:
    """All utility readings (cached)."""
    with _cache_lock:
        _fresh(s)
        if _cache["u"] is None:
            q = select(UtilityReading.ts, UtilityReading.plant_id, UtilityReading.utility_type, UtilityReading.zone,
                       UtilityReading.flow_rate, UtilityReading.pressure_bar, UtilityReading.temperature_c,
                       UtilityReading.consumption_unit, UtilityReading.equipment_id, UtilityReading.operating_status,
                       UtilityReading.alarm_code).order_by(UtilityReading.ts)
            _cache["u"] = [UtilRow(*r, is_alarm=(r[9] == "ALARM") or bool(r[10] and r[10] != "NONE"))
                           for r in s.execute(q)]
        return _cache["u"]


def machine_rows(s: Session) -> list[MachRow]:
    with _cache_lock:
        _fresh(s)
        if _cache["m"] is None:
            q = select(MachineReading.ts, MachineReading.plant_id, MachineReading.machine_id, MachineReading.line_id,
                       MachineReading.machine_state, MachineReading.is_anomaly).order_by(MachineReading.ts)
            _cache["m"] = [MachRow(*r) for r in s.execute(q)]
        return _cache["m"]


def downtime_rows(s: Session) -> list[DownRow]:
    with _cache_lock:
        _fresh(s)
        if _cache["d"] is None:
            q = select(DowntimeEvent.start_ts, DowntimeEvent.plant_id, DowntimeEvent.machine_id, DowntimeEvent.line_id,
                       DowntimeEvent.duration_min, DowntimeEvent.reason_code, DowntimeEvent.impact_units,
                       DowntimeEvent.maintenance_required, DowntimeEvent.closure_status).order_by(DowntimeEvent.start_ts)
            _cache["d"] = [DownRow(*r) for r in s.execute(q)]
        return _cache["d"]


def warm_cache() -> None:
    """Load everything now (called in the background at startup and after an upload)."""
    from app.db.session import SessionLocal
    try:
        with SessionLocal() as s:
            utility_rows(s), machine_rows(s), downtime_rows(s)
    except Exception:  # noqa: BLE001 - best effort; the first request will load it
        pass


def as_of(s: Session) -> dt.datetime | None:
    """The 'now' of the analysis: the latest utility reading (the data may be historical)."""
    rows = utility_rows(s)
    return rows[-1].ts if rows else None


def _need_data(s: Session) -> dt.datetime:
    end = as_of(s)
    if end is None:
        raise ValueError("No utility telemetry has been uploaded yet. Upload fact_utility_telemetry_hourly.csv "
                         "on the Data page first.")
    return end


def _resolve(value: str | None, choices, label: str) -> str | None:
    """Map free text to a value present in the data ('chw' -> CHILLED_WATER, 'tn' -> IN-TN-01). None = all."""
    if value is None:
        return None
    v = str(value).strip().upper().replace(" ", "_")
    if v in ("", "ALL", "*", "ANY", "NONE", "ALL_SYSTEMS"):
        return None
    options = sorted(set(choices))
    if v in options:
        return v
    if _ALIASES.get(v) in options:
        return _ALIASES[v]
    plural = v.rstrip("S")
    hits = [o for o in options if v in o.replace("-", "_") or plural in o.replace("-", "_")]
    if len(hits) == 1:
        return hits[0]
    near = difflib.get_close_matches(v, options, n=1, cutoff=0.6)
    if near:
        return near[0]
    raise ValueError(f"Unknown {label} '{value}'. Available: {', '.join(options)}")


def resolve_utility(s: Session, value: str | None) -> str | None:
    return _resolve(value, {r.utype for r in utility_rows(s)}, "utility type")


def resolve_plant(s: Session, value: str | None) -> str | None:
    return _resolve(value, {r.plant for r in utility_rows(s)}, "plant")


def resolve_zone(s: Session, value: str | None) -> str | None:
    return _resolve(value, {r.zone for r in utility_rows(s)}, "zone")


def _select(rows, utype=None, plant=None, zone=None, start=None, end=None):
    return [r for r in rows
            if (utype is None or r.utype == utype) and (plant is None or r.plant == plant)
            and (zone is None or r.zone == zone) and (start is None or r.ts > start) and (end is None or r.ts <= end)]


def _vals(rows, attr: str) -> list[float]:
    return [v for v in (getattr(r, attr) for r in rows) if v is not None]


def _poisson_sf(k: int, lam: float) -> float:
    """P(X >= k) for X ~ Poisson(lam)."""
    if k <= 0:
        return 1.0
    term, cdf = math.exp(-lam), 0.0
    for i in range(k):
        cdf += term
        term *= lam / (i + 1)
    return max(0.0, 1.0 - cdf)


def _label(u: str) -> str:
    return u if u == "HVAC" else u.replace("_", " ").lower()


def _welch(recent: list[float], base: list[float]) -> float | None:
    if len(recent) < RECENT_MIN_N or len(base) < BASELINE_MIN_N:
        return None
    se = math.sqrt(_sd(base) ** 2 / len(base) + _sd(recent) ** 2 / len(recent))
    return None if se == 0 else (_mean(recent) - _mean(base)) / se


# =========================================================================== data overview
@memoized
def data_overview(s: Session) -> dict:
    """What data is loaded, its coverage and quality problems the analysis has to be careful about."""
    from app.services.ingest import dataset_status
    out: dict = {"datasets": dataset_status(s), "as_of": as_of(s)}
    rows = utility_rows(s)
    if not rows:
        out["message"] = "No utility telemetry uploaded yet."
        return out
    mach, down = machine_rows(s), downtime_rows(s)
    out.update(
        plants=sorted({r.plant for r in rows}), utility_types=sorted({r.utype for r in rows}),
        zones=sorted({r.zone for r in rows}), utility_equipment=sorted({r.equip for r in rows if r.equip}),
        machines=len({m.machine for m in mach}), lines=sorted({m.line for m in mach if m.line}),
        downtime_reason_codes=dict(Counter(d.reason for d in down).most_common()))

    notes: list[str] = []
    units: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        units[r.utype][r.unit] += 1
    mixed = {u: dict(c) for u, c in units.items() if len(c) > 1}
    if mixed:
        notes.append("consumption_unit changes from row to row for the same utility (" +
                     "; ".join(f"{u}: {', '.join(sorted(c))}" for u, c in mixed.items()) +
                     "). flow_rate is therefore used as a relative load index (this series vs its own history), "
                     "never added up into an absolute volume or cost. Fix the unit at the source to get volumes.")
    series = {(r.plant, r.utype, r.zone) for r in rows}
    hours = max(1, int((rows[-1].ts - rows[0].ts).total_seconds() // 3600) + 1)
    per_series = len(rows) / len(series)
    notes.append(f"{len(series)} series (plant x utility x zone) with {per_series:.0f} readings each over {hours} h: "
                 f"one reading about every {hours / per_series:.1f} h per series, so short windows hold few readings.")
    keys = Counter((r.ts, r.plant, r.utype, r.zone, r.equip) for r in rows)
    dups = sum(c - 1 for c in keys.values() if c > 1)
    if dups:
        notes.append(f"{dups} readings repeat the same timestamp/plant/utility/zone/equipment with different values.")
    pl_alarm = [r for r in rows if r.alarm == "PRESSURE_LOW" and r.pressure is not None]
    normal = [r.pressure for r in rows if not r.is_alarm and r.pressure is not None]
    if len(pl_alarm) >= 20 and normal:
        a, n = _mean([r.pressure for r in pl_alarm]), _mean(normal)
        if a >= n - 0.2:
            notes.append(f"PRESSURE_LOW alarms do not coincide with low pressure: alarm rows average {a:.2f} bar vs "
                         f"{n:.2f} bar for normal rows. Check the alarm configuration or the pressure sensors.")
    out["data_quality"] = notes
    return out


# =========================================================================== consumption trends
@memoized
def consumption_trends(s: Session, utility_type: str | None = None, plant_id: str | None = None,
                       zone: str | None = None, period: str = "week", periods: int = 8,
                       group_by: str = "utility_type") -> dict:
    end = _need_data(s)
    ut, pl, zn = resolve_utility(s, utility_type), resolve_plant(s, plant_id), resolve_zone(s, zone)
    period = (period or "week").lower()
    if period not in ("day", "week"):
        raise ValueError("period must be 'day' or 'week'.")
    group_by = (group_by or "utility_type").lower()
    if group_by not in ("utility_type", "plant", "zone"):
        raise ValueError("group_by must be utility_type, plant or zone.")
    periods = max(2, min(int(periods), 30 if period == "day" else 26))

    def bucket(ts: dt.datetime) -> dt.date:
        d = ts.date()
        return d if period == "day" else d - dt.timedelta(days=d.weekday())

    rows = _select(utility_rows(s), ut, pl, zn)
    last_bucket = bucket(end)
    step = dt.timedelta(days=1 if period == "day" else 7)
    wanted = [last_bucket - step * i for i in range(periods - 1, -1, -1)]
    keyf = {"utility_type": lambda r: r.utype, "plant": lambda r: r.plant, "zone": lambda r: r.zone}[group_by]
    groups: dict[str, dict[dt.date, list[UtilRow]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        b = bucket(r.ts)
        if b in wanted:
            groups[keyf(r)][b].append(r)

    out = []
    for g, by_b in sorted(groups.items()):
        series = []
        for b in wanted:
            rr = by_b.get(b, [])
            if not rr:
                continue
            series.append({"period_start": b, "avg_flow": _r(_mean(_vals(rr, "flow"))),
                           "peak_flow": _r(max(_vals(rr, "flow"), default=None)),
                           "avg_pressure_bar": _r(_mean(_vals(rr, "pressure"))),
                           "avg_temperature_c": _r(_mean(_vals(rr, "temp"))), "readings": len(rr),
                           "alarms": sum(1 for x in rr if x.is_alarm)})
        flows = [p["avg_flow"] for p in series if p["avg_flow"] is not None]
        if len(flows) < 2:
            continue
        change = _pct(flows[-1], flows[-2])
        slope = _linreg(flows)
        overall = _mean(flows)
        slope_pct = slope / overall * 100 if overall else 0.0
        direction = "flat" if abs(change or 0) < 3 and abs(slope_pct) < 1 else ("up" if (change or 0) > 0 else "down")
        out.append({"group": g, "series": series, "avg_flow_overall": _r(overall),
                    "last_vs_previous_pct": _r(change, 1), "trend_pct_per_period": _r(slope_pct, 2),
                    "direction": direction})
    return {"as_of": end, "period": period, "periods": periods, "group_by": group_by,
            "filters": {"utility_type": ut, "plant_id": pl, "zone": zn},
            "note": "avg_flow is flow_rate as stored; units differ between rows, so read it as a relative load index.",
            "groups": out}


# =========================================================================== abnormal usage
def _recommend(utype: str, metric: str, direction: str) -> tuple[str, str]:
    cause_flow_up = ADVICE.get(utype, "uncontrolled demand or a leak")
    if metric == "flow" and direction == "up":
        return (f"Higher demand than this series' history: typically {cause_flow_up}.",
                f"Inspect the area for {cause_flow_up}; compare against the production schedule; confirm the meter.")
    if metric == "flow":
        return ("Demand fell versus history: lower production load, a blocked line or a meter/sensor fault.",
                "Confirm the production schedule; if production was normal, check the line and the meter.")
    if metric == "pressure" and direction == "down":
        return ("Supply pressure is lower than usual: capacity shortfall, restriction or a leak.",
                "Check supply capacity, filters, regulators and leaks; review with the certified operator.")
    if metric == "pressure":
        return ("Pressure is above usual: over-supply wastes energy and can stress equipment.",
                "Review the pressure setpoint with a certified operator (this agent never changes setpoints).")
    return ("Temperature moved away from its usual level: heat-exchanger/cooling problem or a sensor drift.",
            "Inspect cooling/heat-exchange equipment and check the temperature sensor calibration.")


def _finding(utype, plant, zone, metric, base, recent, z, base_n, rec_n, z_min=Z_THRESHOLD) -> dict | None:
    pct = _pct(_mean(recent), _mean(base))
    if z is None or pct is None or abs(z) < z_min or abs(pct) < MIN_CHANGE_PCT[metric]:
        return None
    direction = "up" if pct > 0 else "down"
    big = abs(pct) >= 2 * MIN_CHANGE_PCT[metric] and abs(z) >= 4
    cause, action = _recommend(utype, metric, direction)
    unit = {"flow": "flow_rate", "pressure": "bar", "temperature": "C"}[metric]
    return {"type": "level_shift", "severity": "HIGH" if big else "MEDIUM", "utility_type": utype,
            "plant_id": plant, "zone": zone, "metric": metric, "direction": direction,
            "evidence": {"recent_mean": _r(_mean(recent)), "baseline_mean": _r(_mean(base)), "unit": unit,
                         "change_pct": _r(pct, 1), "z_score": _r(z, 1), "recent_readings": rec_n,
                         "baseline_readings": base_n},
            "likely_cause": cause, "recommendation": action,
            "description": f"{utype.replace('_', ' ').title()}"
                           f"{'' if plant is None else ' ' + plant}{'' if zone is None else ' ' + zone}: "
                           f"{metric} {direction} {abs(pct):.0f}% vs history"}


@memoized
def detect_abnormal_usage(s: Session, days: int = 7, utility_type: str | None = None, plant_id: str | None = None,
                          zone: str | None = None) -> dict:
    """Compare the last `days` of every utility/plant/zone series with its own earlier history."""
    end = _need_data(s)
    ut, pl, zn = resolve_utility(s, utility_type), resolve_plant(s, plant_id), resolve_zone(s, zone)
    days = max(1, min(int(days), 60))
    start = end - dt.timedelta(days=days)
    rows = _select(utility_rows(s), ut, pl, zn)
    recent_all = [r for r in rows if r.ts > start]
    base_all = [r for r in rows if r.ts <= start]
    findings: list[dict] = []
    tested = 0

    def test_scope(utype, plant, zone_, strict=False):
        nonlocal tested
        z_min = Z_SERIES if strict else Z_THRESHOLD
        rec = [r for r in recent_all if r.utype == utype and (plant is None or r.plant == plant)
               and (zone_ is None or r.zone == zone_)]
        base = [r for r in base_all if r.utype == utype and (plant is None or r.plant == plant)
                and (zone_ is None or r.zone == zone_)]
        for metric, attr in (("flow", "flow"), ("pressure", "pressure"), ("temperature", "temp")):
            b, r_ = _vals(base, attr), _vals(rec, attr)
            z = _welch(r_, b)
            if z is not None:
                tested += 1
            f = _finding(utype, plant, zone_, metric, b, r_, z, len(b), len(r_), z_min)
            if f:
                findings.append(f)
        # Alarm cluster: more alarms than the utility's baseline alarm rate predicts (exact Poisson tail).
        if len(rec) >= RECENT_MIN_N:
            pool = [x for x in base_all if x.utype == utype]          # baseline rate pooled over the whole utility
            if len(pool) >= BASELINE_MIN_N:
                p0 = sum(1 for x in pool if x.is_alarm) / len(pool)
                k = sum(1 for x in rec if x.is_alarm)
                lam = len(rec) * p0
                tested += 1
                p_val = _poisson_sf(k, lam)
                if k >= 5 and p_val < (ALARM_P_SERIES if strict else ALARM_P_UTILITY):
                    findings.append({
                        "type": "alarm_cluster", "severity": "MEDIUM", "utility_type": utype, "plant_id": plant,
                        "zone": zone_, "metric": "alarms", "direction": "up",
                        "evidence": {"alarms_recent": k, "readings_recent": len(rec), "alarms_expected": _r(lam, 1),
                                     "alarm_rate_recent_pct": _r(k / len(rec) * 100, 1),
                                     "alarm_rate_baseline_pct": _r(p0 * 100, 1), "p_value": float(f"{p_val:.2g}")},
                        "likely_cause": "Repeated utility alarms, more than this utility normally raises.",
                        "recommendation": "Review the alarm log for this equipment and its alarm set-points with maintenance.",
                        "description": (f"{_label(utype).title() if utype != 'HVAC' else 'HVAC'} "
                                        f"{plant or ''} {zone_ or ''}: {k} alarms in {days} d "
                                        f"(about {lam:.0f} expected)").replace("  ", " ")})

    types = sorted({r.utype for r in rows})
    plants = sorted({r.plant for r in rows})
    zones = sorted({r.zone for r in rows})
    for u in types:
        test_scope(u, pl, zn)                      # utility level (or the filtered scope)
        if pl is None and zn is None:
            for p in plants:
                for z_ in zones:
                    if any(r.utype == u and r.plant == p and r.zone == z_ for r in rows):
                        test_scope(u, p, z_, strict=True)   # every plant/zone series
    findings.sort(key=lambda f: (-SEVERITY_RANK[f["severity"]], -abs(f["evidence"].get("z_score") or 0)))

    alarms = [r for r in recent_all if r.is_alarm]
    by_type = Counter(r.utype for r in alarms)
    by_plant = Counter(r.plant for r in alarms)
    n_recent = len(recent_all)
    return {
        "as_of": end, "window": {"from": start, "to": end, "days": days}, "filters": {
            "utility_type": ut, "plant_id": pl, "zone": zn},
        "readings_in_window": n_recent, "readings_in_baseline": len(base_all), "tests_run": tested,
        "method": (f"Each series' last {days} d is compared with its earlier history (Welch z >= {Z_THRESHOLD:g} "
                   f"and a change of at least flow {MIN_CHANGE_PCT['flow']:g}%, pressure "
                   f"{MIN_CHANGE_PCT['pressure']:g}%, temperature {MIN_CHANGE_PCT['temperature']:g}%)."),
        "anomaly_count": len(findings), "anomalies": findings[:MAX_ITEMS],
        "alarms_in_window": {"count": len(alarms), "rate_pct": _r(len(alarms) / n_recent * 100, 1) if n_recent else None,
                             "by_utility_type": dict(by_type.most_common()), "by_plant": dict(by_plant.most_common())},
        "conclusion": ("No statistically abnormal consumption, pressure or temperature in this window."
                       if not findings else f"{len(findings)} abnormal pattern(s) found, highest severity "
                                            f"{findings[0]['severity']}."),
    }


# =========================================================================== downtime correlation
def _two_rate_z(k1: int, n1: float, k2: int, n2: float) -> float:
    """z for the difference of two Poisson rates (k events over n exposure units)."""
    if n1 <= 0 or n2 <= 0 or (k1 + k2) == 0:
        return 0.0
    pooled = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pooled * (1 / n1 + 1 / n2))
    return (k1 / n1 - k2 / n2) / se if se else 0.0


@memoized
def downtime_correlation(s: Session, utility_type: str | None = None, plant_id: str | None = None,
                         window_hours: int = 2, days: int | None = None) -> dict:
    """Do downtime events start more often just after utility alarms? Compared per utility type."""
    end = _need_data(s)
    pl = resolve_plant(s, plant_id)
    ut = resolve_utility(s, utility_type)
    window_hours = max(0, min(int(window_hours), 12))
    start = end - dt.timedelta(days=int(days)) if days else None
    urows = _select(utility_rows(s), None, pl, None, start=start)
    drows = [d for d in downtime_rows(s) if (pl is None or d.plant == pl) and (start is None or d.ts > start)]
    mrows = [m for m in machine_rows(s) if (pl is None or m.plant == pl) and (start is None or m.ts > start)]
    if not drows:
        return {"as_of": end, "message": "No downtime events uploaded for this scope. Upload fact_downtime_event.csv.",
                "downtime_summary": None}

    plants = sorted({r.plant for r in urows} | {d.plant for d in drows})
    first = _floor_hour(min(min(r.ts for r in urows), min(d.ts for d in drows)))
    last = _floor_hour(end)
    all_hours = {(p, first + dt.timedelta(hours=i)) for p in plants
                 for i in range(int((last - first).total_seconds() // 3600) + 1)}

    # downtime summary
    reasons = defaultdict(lambda: [0, 0.0])
    lines = defaultdict(lambda: [0, 0.0])
    for d in drows:
        reasons[d.reason or "UNKNOWN"][0] += 1
        reasons[d.reason or "UNKNOWN"][1] += d.minutes or 0
        lines[d.line or "UNKNOWN"][0] += 1
        lines[d.line or "UNKNOWN"][1] += d.minutes or 0
    summary = {
        "events": len(drows), "total_minutes": _r(sum(d.minutes or 0 for d in drows), 0),
        "open_events": sum(1 for d in drows if d.status == "OPEN"),
        "maintenance_required": sum(1 for d in drows if d.maint),
        "by_reason": [{"reason": k, "events": v[0], "minutes": _r(v[1], 0)}
                      for k, v in sorted(reasons.items(), key=lambda kv: -kv[1][1])],
        "by_line": [{"line": k, "events": v[0], "minutes": _r(v[1], 0)}
                    for k, v in sorted(lines.items(), key=lambda kv: -kv[1][1])],
        "reason_note": ("None of the downtime reason codes names a utility cause, so the link to utilities is "
                        "tested on timing: did downtime start soon after a utility alarm at the same plant?")}

    def analyse(types: list[str] | None) -> dict:
        alarm_rows = [r for r in urows if r.is_alarm and (types is None or r.utype in types)]
        exposed = {(r.plant, _floor_hour(r.ts) + dt.timedelta(hours=k)) for r in alarm_rows
                   for k in range(window_hours + 1)} & all_hours
        ev_exp = [d for d in drows if (d.plant, _floor_hour(d.ts)) in exposed]
        ev_not = len(drows) - len(ev_exp)
        h_exp, h_not = len(exposed), len(all_hours) - len(exposed)
        r1 = len(ev_exp) / h_exp if h_exp else 0.0
        r2 = ev_not / h_not if h_not else 0.0
        z = _two_rate_z(len(ev_exp), h_exp, ev_not, h_not)
        lift = r1 / r2 if r2 else None
        linked = lift is not None and lift >= 1.5 and z >= 2.5 and len(ev_exp) >= 10
        mach_exp = [m for m in mrows if (m.plant, _floor_hour(m.ts)) in exposed]
        mach_not = [m for m in mrows if (m.plant, _floor_hour(m.ts)) not in exposed]
        down_share = lambda ms: _r(sum(1 for m in ms if m.state == "DOWN") / len(ms) * 100, 1) if ms else None  # noqa: E731
        return {
            "utility_alarms": len(alarm_rows), "hours_after_alarm": h_exp, "hours_without_alarm": h_not,
            "downtime_events_after_alarm": len(ev_exp), "downtime_events_otherwise": ev_not,
            "events_per_100h_after_alarm": _r(r1 * 100), "events_per_100h_otherwise": _r(r2 * 100),
            "lift": _r(lift), "z_score": _r(z, 1),
            "minutes_after_alarm": _r(sum(d.minutes or 0 for d in ev_exp), 0),
            "machine_down_share_pct_after_alarm": down_share(mach_exp),
            "machine_down_share_pct_otherwise": down_share(mach_not),
            "verdict": "possible link" if linked else "no meaningful link"}

    scopes = [ut] if ut else sorted({r.utype for r in urows})
    per_type = [{"utility_type": u, **analyse([u])} for u in scopes]
    per_type.sort(key=lambda x: -x["z_score"])
    overall = analyse([ut] if ut else None)
    possible = [x["utility_type"] for x in per_type if x["verdict"] == "possible link"]
    if possible:
        conclusion = ("Downtime starts more often right after alarms on: " + ", ".join(possible) +
                      ". Treat as a lead to investigate, not proof of cause.")
    else:
        conclusion = (f"No utility shows a meaningful link to downtime: events start at about the same rate "
                      f"({overall['events_per_100h_after_alarm']} vs {overall['events_per_100h_otherwise']} per 100 h) "
                      f"whether or not a utility alarm occurred in the previous {window_hours} h.")
    return {"as_of": end, "scope": {"plant_id": pl, "utility_type": ut, "days": days, "window_hours": window_hours},
            "method": (f"For each plant-hour: 'after alarm' = a utility alarm at that plant in the same or previous "
                       f"{window_hours} h. Downtime start rates are compared (lift >= 1.5, z >= 2.5, >= 10 events)."),
            "overall": overall, "by_utility_type": per_type, "downtime_summary": summary, "conclusion": conclusion}


# =========================================================================== efficiency
@memoized
def efficiency_opportunities(s: Session) -> dict:
    """Where do utilities waste energy: demand that ignores idle machines, flat day/night load, outlier zones."""
    end = _need_data(s)
    urows, mrows = utility_rows(s), machine_rows(s)
    findings: list[dict] = []
    recs: list[dict] = []

    # 1. Does utility demand fall when machines are idle/down/in setup?
    per_hour: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for m in mrows:
        c = per_hour[(m.plant, _floor_hour(m.ts))]
        c[0] += 1
        c[1] += 0 if m.state == "RUNNING" else 1
    idle_share = {k: v[1] / v[0] for k, v in per_hour.items() if v[0]}
    idle_block = []
    if idle_share:
        for u in sorted({r.utype for r in urows}):
            low, high = [], []
            for r in urows:
                if r.utype != u or r.flow is None:
                    continue
                sh = idle_share.get((r.plant, _floor_hour(r.ts)))
                if sh is None:
                    continue
                if sh <= 0.15:
                    low.append((r.flow, sh))
                elif sh >= 0.35:
                    high.append((r.flow, sh))
            if len(low) < 50 or len(high) < 50:
                continue
            f_low, f_high = _mean([x[0] for x in low]), _mean([x[0] for x in high])
            i_low, i_high = _mean([x[1] for x in low]), _mean([x[1] for x in high])
            expected = f_low * (1 - i_high) / (1 - i_low)
            saving = max(0.0, (f_high - expected) / f_high * 100) if f_high else 0.0
            item = {"utility_type": u, "avg_flow_when_machines_busy": _r(f_low), "avg_flow_when_many_idle": _r(f_high),
                    "demand_ratio_idle_vs_busy": _r(f_high / f_low, 2), "machines_idle_share_busy_pct": _r(i_low * 100, 0),
                    "machines_idle_share_idle_pct": _r(i_high * 100, 0), "potential_saving_pct": _r(saving, 1),
                    "readings_busy": len(low), "readings_idle": len(high)}
            idle_block.append(item)
    flat_idle = [x for x in idle_block if x["demand_ratio_idle_vs_busy"] >= 0.9 and x["potential_saving_pct"] >= 5]
    if flat_idle:
        top = max(x["potential_saving_pct"] for x in flat_idle)
        x0 = flat_idle[0]
        recs.append({
            "priority": "HIGH" if top >= 15 else "MEDIUM", "owner": "Facilities + Production",
            "utility_type": None,
            "action": "Add idle-time shutdown/setback for " + ", ".join(_label(x["utility_type"]) for x in flat_idle),
            "why": f"Demand does not fall when machines stop: it stays at about {x0['demand_ratio_idle_vs_busy'] * 100:.0f}% "
                   f"of the busy level while {x0['machines_idle_share_idle_pct']:.0f}% of machines are idle/down "
                   f"(vs {x0['machines_idle_share_busy_pct']:.0f}% when busy). Upper bound if demand tracked running "
                   f"machines fully: up to about {top:.0f}% less in those hours. The real saving is lower because "
                   "some load is always needed."})
    findings.append({"check": "demand_vs_idle_machines", "results": idle_block,
                     "meaning": "If utilities used less when machines are idle, the ratio would be well below 1. "
                                "potential_saving_pct is an upper bound, not a forecast."})

    # 2. Night vs day load
    night_block = []
    for u in sorted({r.utype for r in urows}):
        night = [r.flow for r in urows if r.utype == u and r.flow is not None and (r.ts.hour >= 22 or r.ts.hour < 6)]
        day = [r.flow for r in urows if r.utype == u and r.flow is not None and 6 <= r.ts.hour < 22]
        if len(night) >= 50 and len(day) >= 50:
            ratio = _mean(night) / _mean(day)
            night_block.append({"utility_type": u, "avg_night_flow": _r(_mean(night)), "avg_day_flow": _r(_mean(day)),
                                "night_to_day_ratio": _r(ratio, 2)})
    flat = [n for n in night_block if n["night_to_day_ratio"] >= 0.9]
    if flat:
        recs.append({"priority": "MEDIUM", "owner": "Facilities", "utility_type": None,
                     "action": "Introduce a night/weekend setback schedule",
                     "why": "Night-time (22:00-06:00) load is at least 90% of daytime load for " +
                            ", ".join(_label(n["utility_type"]) for n in flat) +
                            ", so little is switched down outside production hours."})
    findings.append({"check": "night_vs_day", "results": night_block})

    # 3. Zones that use noticeably more than their peers
    outliers = []
    for u in sorted({r.utype for r in urows}):
        avg = {}
        for key in {(r.plant, r.zone) for r in urows if r.utype == u}:
            v = [r.flow for r in urows if r.utype == u and (r.plant, r.zone) == key and r.flow is not None]
            if len(v) >= 50:
                avg[key] = _mean(v)
        if len(avg) < 3:
            continue
        med = statistics.median(avg.values())
        for (p, z_), a in avg.items():
            if med and (a - med) / med >= 0.10:
                outliers.append({"utility_type": u, "plant_id": p, "zone": z_, "avg_flow": _r(a),
                                 "peer_median": _r(med), "above_peers_pct": _r((a - med) / med * 100, 1)})
    outliers.sort(key=lambda x: -x["above_peers_pct"])
    for o in outliers[:3]:
        recs.append({"priority": "MEDIUM", "owner": "Facilities", "utility_type": o["utility_type"],
                     "action": f"Audit {_label(o['utility_type'])} use in {o['plant_id']} {o['zone']}",
                     "why": f"Uses {o['above_peers_pct']:.0f}% more than the median zone ({o['avg_flow']} vs {o['peer_median']})."})
    findings.append({"check": "zones_above_peers", "results": outliers[:10]})

    # 4. Equipment that alarms more than its peers
    eq = defaultdict(lambda: [0, 0])
    for r in urows:
        if r.equip:
            eq[r.equip][0] += 1
            eq[r.equip][1] += 1 if r.is_alarm else 0
    total_n = sum(v[0] for v in eq.values())
    base = sum(v[1] for v in eq.values()) / total_n if total_n else 0
    hot = []
    for e, (n, k) in eq.items():
        sd = math.sqrt(n * base * (1 - base)) if 0 < base < 1 else 0
        if sd and k >= 5 and (k - n * base) / sd >= Z_THRESHOLD:
            hot.append({"equipment_id": e, "readings": n, "alarms": k, "alarm_rate_pct": _r(k / n * 100, 1),
                        "fleet_rate_pct": _r(base * 100, 1)})
    for h in hot:
        recs.append({"priority": "MEDIUM", "owner": "Maintenance", "utility_type": None,
                     "action": f"Inspect utility equipment {h['equipment_id']}",
                     "why": f"Alarm rate {h['alarm_rate_pct']}% vs {h['fleet_rate_pct']}% across all utility equipment."})
    findings.append({"check": "alarm_hotspot_equipment", "results": hot,
                     "meaning": "Equipment whose alarm rate is statistically above the fleet rate."})

    recs.sort(key=lambda r: -SEVERITY_RANK[r["priority"]])
    return {"as_of": end, "findings": findings, "recommendations": recs,
            "conclusion": (f"{len(recs)} efficiency opportunit{'y' if len(recs) == 1 else 'ies'} found."
                           if recs else "No significant efficiency opportunity found in this data."),
            "caveat": "Savings are estimates that assume demand should scale with running machines; "
                      "validate with site engineers before acting."}


# =========================================================================== health board
@memoized
def health_board(s: Session) -> dict:
    """One-screen status per utility type, KPIs and the top findings."""
    end = as_of(s)
    if end is None:
        return {"as_of": None, "empty": True,
                "message": "No data yet. Upload the three CSV files on the Data page."}
    rows = utility_rows(s)
    ab = detect_abnormal_usage(s, days=7)
    last24 = [r for r in rows if r.ts > end - dt.timedelta(hours=24)]
    prev7 = [r for r in rows if end - dt.timedelta(days=8) < r.ts <= end - dt.timedelta(hours=24)]
    last7 = [r for r in rows if r.ts > end - dt.timedelta(days=7)]
    utilities = []
    for u in sorted({r.utype for r in rows}):
        f24, f7, fp = (_select(x, u) for x in (last24, last7, prev7))
        flow24, flowp = _mean(_vals(f24, "flow")), _mean(_vals(fp, "flow"))
        finds = [a for a in ab["anomalies"] if a["utility_type"] == u]
        status = "NORMAL"
        if any(a["severity"] in ("HIGH", "CRITICAL") for a in finds):
            status = "ALARM"
        elif finds:
            status = "WATCH"
        a7 = sum(1 for r in f7 if r.is_alarm)
        reasons = [a["description"] for a in finds[:3]]
        if not reasons:
            reasons = ["No abnormal pattern against its own history."]
        utilities.append({
            "utility_type": u, "status": status, "reasons": reasons,
            "avg_flow_24h": _r(flow24), "avg_flow_prev_7d": _r(flowp), "flow_change_pct": _r(_pct(flow24, flowp), 1),
            "avg_pressure_bar_24h": _r(_mean(_vals(f24, "pressure"))),
            "avg_temperature_c_24h": _r(_mean(_vals(f24, "temp"))),
            "alarms_24h": sum(1 for r in f24 if r.is_alarm), "alarms_7d": a7,
            "alarm_rate_7d_pct": _r(a7 / len(f7) * 100, 1) if f7 else None, "readings_7d": len(f7)})
    utilities.sort(key=lambda x: (-STATUS_RANK[x["status"]], x["utility_type"]))
    overall = max(utilities, key=lambda x: STATUS_RANK[x["status"]])["status"]

    down = [d for d in downtime_rows(s) if d.ts > end - dt.timedelta(days=7)]
    corr = downtime_correlation(s) if downtime_rows(s) else None
    eff = efficiency_opportunities(s) if machine_rows(s) else None
    return {
        "as_of": end, "empty": False, "overall_status": overall, "utilities": utilities,
        "kpis": {"readings_7d": len(last7), "alarms_7d": sum(1 for r in last7 if r.is_alarm),
                 "alarm_rate_7d_pct": _r(sum(1 for r in last7 if r.is_alarm) / len(last7) * 100, 1) if last7 else None,
                 "abnormal_patterns_7d": ab["anomaly_count"], "downtime_events_7d": len(down),
                 "downtime_minutes_7d": _r(sum(d.minutes or 0 for d in down), 0)},
        "anomalies": ab["anomalies"][:10], "anomaly_conclusion": ab["conclusion"],
        "downtime_link": None if not corr or "overall" not in corr else {
            "conclusion": corr["conclusion"], "by_utility_type": [
                {k: x[k] for k in ("utility_type", "lift", "z_score", "verdict", "downtime_events_after_alarm")}
                for x in corr["by_utility_type"]]},
        "efficiency": None if eff is None else {"conclusion": eff["conclusion"], "recommendations": eff["recommendations"][:5]},
        "data_quality": data_overview(s).get("data_quality", []),
    }
