"""Synthetic CSV files in the same format as the real ones, with known planted patterns.

Plants P1/P2, utilities COMPRESSED_AIR and HVAC, zones SMT and TEST, hourly for 30 days (2026-09-01..09-30).
Planted:
  * COMPRESSED_AIR at P1/SMT uses 40 % more flow during the last 5 days  -> abnormal usage
  * HVAC at P2/SMT raises an alarm at 05:00 every day and a downtime event starts 1 h later at P2 -> downtime link
  * COMPRESSED_AIR alarms are random and unrelated to downtime               -> no link
  * machine idle/down hours that the utility demand ignores                  -> idle-load recommendation
"""
import csv
import datetime as dt
import io
import random

START = dt.datetime(2026, 9, 1)
HOURS = 30 * 24
END = START + dt.timedelta(hours=HOURS - 1)          # 2026-09-30 23:00
ANOMALY_FROM = dt.datetime(2026, 9, 26)

UTILITY_COLS = ["utility_reading_id", "timestamp", "plant_id", "utility_type", "zone", "flow_rate", "pressure_bar",
                "temperature_c", "consumption_unit", "equipment_id", "operating_status", "alarm_code"]
MACHINE_COLS = ["telemetry_id", "timestamp", "date", "machine_id", "plant_id", "line_id", "shift_id", "temperature_c",
                "vibration_mm_s", "motor_current_a", "pressure_bar", "rpm", "machine_state", "alarm_code",
                "sensor_health", "is_anomaly"]
DOWNTIME_COLS = ["downtime_id", "machine_id", "plant_id", "line_id", "start_ts", "duration_min", "reason_code",
                 "impact_units", "maintenance_required", "acknowledged_by", "closure_status"]


def _csv(cols, rows) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    w.writerows(rows)
    return buf.getvalue().encode()


def make_csvs(seed: int = 7) -> dict[str, bytes]:
    rnd = random.Random(seed)
    util, mach, down = [], [], []
    n = 0
    for h in range(HOURS):
        ts = START + dt.timedelta(hours=h)
        for plant in ("P1", "P2"):
            for utype in ("COMPRESSED_AIR", "HVAC"):
                for zone in ("SMT", "TEST"):
                    n += 1
                    flow = rnd.gauss(70, 5)
                    if (plant, utype, zone) == ("P1", "COMPRESSED_AIR", "SMT") and ts >= ANOMALY_FROM:
                        flow *= 1.4
                    alarm = rnd.random() < 0.03
                    if (plant, utype, zone) == ("P2", "HVAC", "SMT"):
                        alarm = ts.hour == 5
                    util.append([f"UT-{n:07d}", ts.isoformat(), plant, utype, zone, round(flow, 2),
                                 round(rnd.gauss(6, 0.2), 2), round(rnd.gauss(22, 1), 2), rnd.choice(["m3", "L", "kWh"]),
                                 f"UTL-{rnd.randint(1, 4):02d}", "ALARM" if alarm else "NORMAL",
                                 "PRESSURE_LOW" if alarm else "NONE"])
        for plant, line in (("P1", "SMT-L1"), ("P2", "SMT-L2")):
            for m in range(4):
                state = rnd.choices(["RUNNING", "IDLE", "DOWN"], [85, 10, 5])[0]
                mach.append([f"TEL-{len(mach) + 1:07d}", ts.isoformat(), ts.date().isoformat(), f"M-{plant}-{m}", plant,
                             line, "A", 55.0, 2.0, 8.0, 6.0, 3000.0, state, "NONE", "GOOD", "False"])
    d = 0
    for day in range(30):                                  # linked: P2 downtime 1 h after the 05:00 HVAC alarm
        d += 1
        t = START + dt.timedelta(days=day, hours=6)
        down.append([f"DT-{d:05d}", "M-P2-0", "P2", "SMT-L2", t.isoformat(), 10, "EQUIPMENT_FAULT", 40, "False",
                     "EMP-1", "CLOSED"])
    for _ in range(60):                                    # background downtime, random hours, both plants
        d += 1
        t = START + dt.timedelta(hours=rnd.randrange(HOURS))
        plant = rnd.choice(["P1", "P2"])
        down.append([f"DT-{d:05d}", f"M-{plant}-1", plant, "SMT-L1" if plant == "P1" else "SMT-L2", t.isoformat(),
                     rnd.choice([5, 10, 20]), rnd.choice(["MICRO_STOP", "CHANGEOVER", "NO_MATERIAL"]), 20,
                     "False", "EMP-2", "OPEN"])
    return {"utility": _csv(UTILITY_COLS, util), "machine": _csv(MACHINE_COLS, mach),
            "downtime": _csv(DOWNTIME_COLS, down)}
