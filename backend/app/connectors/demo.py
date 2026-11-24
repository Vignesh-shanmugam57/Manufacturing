"""A built-in sample source, so the whole connect, test and pull flow can be shown without any outside system.

It behaves like a plant historian: it hands out hourly utility readings in the format of the "Utility telemetry" dataset,
with fresh timestamps up to the current hour. Row ids are fixed per hour, so pulling again never creates duplicates.
The same rows are also served by /api/demo/utility.json and /api/demo/utility.csv, so the REST and CSV connectors can
be pointed at this app itself for a demonstration.
"""
from __future__ import annotations

import datetime as dt
import math
import time

from app.connectors.base import Adapter, PullResult, TestResult

COLUMNS = ["utility_reading_id", "timestamp", "plant_id", "utility_type", "zone", "flow_rate", "pressure_bar", "temperature_c",
           "consumption_unit", "equipment_id", "operating_status", "alarm_code"]
PLANTS = ["IN-KA-01", "IN-TN-01"]
UTILITIES = [("COMPRESSED_AIR", "kWh", 83.0, 5.9, 18.0), ("CHILLED_WATER", "m3", 72.0, 4.6, 26.0), ("HVAC", "kWh", 80.0, 7.1, 18.0),
             ("PROCESS_WATER", "m3", 90.0, 4.8, 28.0), ("NITROGEN", "m3", 60.0, 6.2, 20.0)]
INITIAL_HOURS = 48


def _shape(h: int) -> float:
    return 0.62 + 0.38 * max(0.0, math.sin((h - 5) / 14 * math.pi))


def rows_between(first: dt.datetime, last: dt.datetime) -> list[dict]:
    """One reading per plant and utility for every full hour from `first` to `last` inclusive."""
    first, last = first.replace(minute=0, second=0, microsecond=0), last.replace(minute=0, second=0, microsecond=0)
    out: list[dict] = []
    t = first
    while t <= last:
        for p, plant in enumerate(PLANTS):
            for u, (name, unit, flow, bar, temp) in enumerate(UTILITIES):
                k = t.toordinal() * 31 + t.hour * 7 + u * 3 + p
                out.append({
                    "utility_reading_id": f"UT-DEMO-{t:%Y%m%d%H}-{p}{u}", "timestamp": t.isoformat(), "plant_id": plant,
                    "utility_type": name, "zone": "DEMO", "flow_rate": round(flow * _shape(t.hour) * (1 + 0.04 * math.sin(k)), 2),
                    "pressure_bar": round(bar * (1 + 0.02 * math.sin(k * 1.3)), 2), "temperature_c": round(temp * (1 + 0.03 * math.sin(k * 0.7)), 2),
                    "consumption_unit": unit, "equipment_id": f"UTL-D{u}", "operating_status": "NORMAL", "alarm_code": "NONE"})
        t += dt.timedelta(hours=1)
    return out


class DemoGateway(Adapter):
    def test(self, cfg: dict, secrets: dict) -> TestResult:
        t0 = time.monotonic()
        now = dt.datetime.now()
        sample = rows_between(now, now)[:3]
        return TestResult(True, "The built-in demo gateway is reachable. It provides hourly utility readings.", None, COLUMNS, sample,
                          int((time.monotonic() - t0) * 1000))

    def pull(self, cfg: dict, secrets: dict, cursor: dict | None, limit: int) -> PullResult:
        now = dt.datetime.now().replace(minute=0, second=0, microsecond=0)
        start = dt.datetime.fromisoformat(cursor["value"]) + dt.timedelta(hours=1) if cursor and cursor.get("value") else now - dt.timedelta(hours=INITIAL_HOURS - 1)
        rows = rows_between(start, now) if start <= now else []
        rows = rows[:limit]
        last = dt.datetime.fromisoformat(rows[-1]["timestamp"]) if rows else None
        new_cursor = {"value": last.isoformat(), "type": "datetime"} if last else cursor
        return PullResult(rows, new_cursor, f"Read {len(rows):,} new reading{'s' if len(rows) != 1 else ''} up to {now:%H:00}." if rows else "Nothing new since the last pull.")
