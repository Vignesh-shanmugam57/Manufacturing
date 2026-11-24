"""Mock plant data for the proof of concept: a named team and a believable incident history.

Everything written here is tagged source="MOCK" so the demo reset (which deletes SIMULATED alerts) never touches it,
and `clear_mock` can remove it again. Timestamps are relative to "now", so the open incidents always show sensible
ages ("open for 2 h 14 min") whenever the seed is run. Re-running replaces the previous mock data.

Run:  uv run python cli.py --seed-mock        (or  POST /api/twin/mock/seed )
"""
from __future__ import annotations

import datetime as dt
import random

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.twin import TwinAlert, TwinAlertEvent, TwinMaintenance, TwinNotification, TwinPerson
from app.twin import agent, catalog as cat, people as ppl

SOURCE = "MOCK"
ALL_ZONES = ["*"]
ESCALATE_AFTER = {"CRITICAL": 120, "MAJOR": 300}          # seconds, same rule the live engine uses
ESCALATE_TO = {"CRITICAL": "plant_manager", "MAJOR": "operations_supervisor"}
SEV = {1: "WARNING", 2: "MAJOR", 3: "CRITICAL"}
PLANNED_DAYS = agent.PLANNED_DAYS
PRIORITY = agent.PRIORITY

# name, job title, team, shift, extension, zones covered
ROSTER = [
    ("Ravi Kumar", "Maintenance technician", "Maintenance team", "A", "2101", ["Compressor Room", "Production Hall A", "Production Hall B", "Boiler Room"]),
    ("Arjun Pillai", "Maintenance technician", "Maintenance team", "A", "2104", ["Chiller Plant", "Cooling Tower Area", "Water Plant"]),
    ("Suresh Babu", "Maintenance technician", "Maintenance team", "B", "2102", ["Compressor Room", "Boiler Room", "Chiller Plant", "Cooling Tower Area"]),
    ("Imran Sheikh", "Maintenance technician", "Maintenance team", "C", "2103", ALL_ZONES),
    ("Mohan Das", "Facilities technician", "Facilities team", "A", "2201", ["HVAC Plant", "Water Plant", "Production Hall A", "Production Hall B"]),
    ("Priya Lakshmi", "Facilities technician", "Facilities team", "B", "2202", ["HVAC Plant", "Water Plant", "Production Hall A", "Production Hall B"]),
    ("Anitha Rajan", "Utilities engineer", "Utilities engineer", "A", "2301", ALL_ZONES),
    ("Karthik Menon", "Utilities engineer", "Utilities engineer", "B", "2302", ALL_ZONES),
    ("Deepa Nair", "Utilities engineer", "Utilities engineer", "C", "2303", ALL_ZONES),
    ("Vijay Anand", "Instrument technician", "Instrument technician", "A", "2401", ALL_ZONES),
    ("Rekha Iyer", "Instrument technician", "Instrument technician", "B", "2402", ALL_ZONES),
    ("Farah Khan", "Safety officer", "Safety officer", "A", "2501", ALL_ZONES),
    ("Gopal Sundar", "Safety officer", "Safety officer", "B", "2502", ALL_ZONES),
    ("Naveen Reddy", "Shift supervisor", "Shift supervisor", "A", "2001", ALL_ZONES),
    ("Meera Joshi", "Shift supervisor", "Shift supervisor", "B", "2002", ALL_ZONES),
    ("Salim Qureshi", "Shift supervisor", "Shift supervisor", "C", "2003", ALL_ZONES),
    ("Lakshmi Narayanan", "Plant manager", "Plant manager", "ALL", "2000", ALL_ZONES),
]

COMMENTS = [
    "On site. Isolated the affected section and started checking.",
    "Reading confirmed locally on the gauge. Looking into it now.",
    "Spoke to the line lead. No production impact so far.",
    "Parts requested from the store. Will fit them as soon as they arrive.",
    "Checked the last maintenance record. Nothing unusual before this.",
]

# Each template describes one kind of problem. `main` is the reading that is out of range, `dir` which way, `extras`
# the supporting readings. {eq} is the equipment id.
TEMPLATES = {
    "air": dict(type="compressed_air_leakage", w=6, eqs=["CA-HDR-A", "CA-HDR-B"], main="{eq}.pressure_bar", dir="low",
                extras=[("{eq}.flow_m3min", "high"), ("CA-CMP-01.load_pct", "high")], sev=[1, 1, 2],
                title="Possible compressed air leakage in {zone}", mtype="Leak inspection",
                cause="Possible air leakage in the distribution piping, or an abnormal demand, in {zone}. Inferred from the pressure and flow pattern; the leak location is not confirmed.",
                rec="Inspect the compressed air pipeline and connections in {zone} for leakage (ultrasonic survey), check the compressor loading and unloading cycles, and compare demand with the production schedule. Any setpoint change must be made by an authorised operator.",
                fixes=["Ultrasonic survey found a leaking quick-coupler on drop leg 4. Coupler replaced and the line leak-tested.",
                       "A leaking drain valve on the header was found and replaced. Compressor loading is back to normal.",
                       "Loose flange on the branch line re-torqued and sealed. Pressure recovered."]),
    "steam": dict(type="steam_pressure_instability", w=3, eqs=["ST-HDR-01"], main="ST-HDR-01.pressure_bar", dir="low",
                  extras=[("ST-BLR-01.efficiency_pct", "low"), ("ST-BLR-01.fuel_nm3hr", "high")], sev=[1, 2],
                  title="Unstable steam header pressure in {zone}", mtype="Boiler inspection",
                  cause="Pressure swings at the steam header with falling boiler efficiency. Likely a burner or feedwater control issue; not confirmed.",
                  rec="Inspect the boiler pressure control and burner tuning with the certified operator, and check the feedwater valve for sticking.",
                  fixes=["Burner pressure control re-tuned and the feedwater valve actuator recalibrated by the boiler operator.",
                         "Sticking pressure-control valve cleaned and re-stroked. Header pressure steady again."]),
    "chilled": dict(type="chilled_water_low_delta_t", w=3, eqs=["CW-CHL-01", "CW-CHL-02"], main="{eq}.delta_t_c", dir="low",
                    extras=[("{eq}.power_kw", "high"), ("{eq}.flow_m3hr", "high")], sev=[1, 1, 2],
                    title="Low chilled water Delta T at {eq_name}", mtype="Performance check",
                    cause="Return temperature is close to the supply temperature, so the chiller moves more water for little cooling. Likely a bypass or coil valve issue; not confirmed.",
                    rec="Check the bypass and control valves, then balance the coil flow with the certified operator.",
                    fixes=["Bypass valve found about 20% open. Closed it and balanced the AHU coil valves.",
                           "Two stuck coil valves freed and recalibrated. Delta T back inside range."]),
    "tower": dict(type="cooling_tower_fan_failure", w=3, eqs=["CT-TWR-01", "CT-TWR-02"], main="{eq}.outlet_c", dir="high",
                  extras=[("{eq}.fan_pct", "low"), ("{eq}.inlet_c", "high")], sev=[2], min_level=2, certainty="CONFIRMED",
                  title="Cooling tower fan not running at {eq_name}", mtype="Fan inspection",
                  cause="The fan is not running while the outlet water temperature climbs. A status signal shows the fan is off; the reason still needs inspection.",
                  rec="Inspect the fan motor, drive belt and starter at the tower, and check the condenser water temperature trend.",
                  fixes=["VFD fault cleared and the fan restarted. Belt tension corrected.",
                         "Tripped motor overload reset after a loose terminal was tightened. Fan running normally."]),
    "hvac": dict(type="hvac_airflow_imbalance", w=4, eqs=["HV-AHU-01", "HV-AHU-02"], main="{eq}.airflow_m3hr", dir="low",
                 extras=[("{eq}.zone_temp_c", "high"), ("{eq}.power_kw", "high")], sev=[1, 1, 2],
                 title="HVAC airflow imbalance at {eq_name}", mtype="Airflow balancing",
                 cause="Airflow has dropped while the zone warms up and the unit draws more power. Likely a clogged filter or a damper out of position; not confirmed.",
                 rec="Check the filter bank and damper positions, and balance the airflow with the certified operator.",
                 fixes=["Clogged filter bank replaced and the damper position reset.",
                        "Supply damper actuator re-linked after it slipped. Airflow restored."]),
    "water": dict(type="water_leak", w=3, eqs=["WT-TNK-01"], main="WT-TNK-01.level_pct", dir="low",
                  extras=[("WT-TNK-01.outflow_m3hr", "high"), ("WT-MTR-01.flow_m3hr", "high")], sev=[1, 2],
                  title="Possible water leakage at {eq_name}", mtype="Leak inspection",
                  cause="The tank level keeps falling while main flow and outflow stay high. A leak somewhere in the distribution is likely; the location is not confirmed.",
                  rec="Walk the distribution line from the storage tank, check flanges, valves and drains, and compare the flow with the production schedule.",
                  fixes=["Leaking flange on the booster pump discharge re-gasketed.",
                         "Open drain valve found on the process line and closed. Level stable."]),
    "gas": dict(type="gas_abnormal_consumption", w=2, eqs=["GS-SKD-01"], main="GS-SKD-01.flow_nm3hr", dir="high",
                extras=[("GS-SKD-01.pressure_bar", "low"), ("GS-SKD-01.lel_pct", "high")], sev=[2, 3], safety=True,
                title="Abnormal gas consumption at {eq_name}", mtype="Gas safety inspection",
                cause="Gas flow is far above its baseline, supply pressure is sagging and the combustible-gas reading is up. Treat as a safety matter until inspected.",
                rec="Safety officer to attend. Inspect the regulating skid and downstream joints with a gas detector. Only certified operators may isolate or adjust anything.",
                fixes=["Regulator diaphragm replaced and a weeping joint re-sealed. Gas reading back to zero.",
                       "Burner 2 pilot assembly adjusted and a loose union tightened. Flow normal."]),
    "lim_cmp": dict(type="limit_breach", w=2, eqs=["CA-CMP-01"], main="CA-CMP-01.power_kw", dir="high", extras=[], sev=[1, 1, 2],
                    title=None, mtype="Inspection", cause="A reading has stayed outside its engineering limit. The cause is not yet known.",
                    rec="Inspect the equipment and its supply, and check the sensor reading against a local gauge.",
                    fixes=["Intake filter cleaned. Motor power back inside its limit.", "Sensor drift found and the transmitter recalibrated."]),
    "lim_pump": dict(type="limit_breach", w=2, eqs=["WT-PMP-01"], main="WT-PMP-01.dp_bar", dir="low", extras=[], sev=[1, 1, 2],
                     title=None, mtype="Inspection", cause="A reading has stayed outside its engineering limit. The cause is not yet known.",
                     rec="Inspect the equipment and its supply, and check the sensor reading against a local gauge.",
                     fixes=["Suction strainer cleaned. Differential pressure restored.", "Impeller wear noted; pump re-shimmed and scheduled for overhaul."]),
    "lim_chw": dict(type="limit_breach", w=1, eqs=["CW-PMP-01"], main="CW-PMP-01.power_kw", dir="high", extras=[], sev=[1, 2],
                    title=None, mtype="Inspection", cause="A reading has stayed outside its engineering limit. The cause is not yet known.",
                    rec="Inspect the equipment and its supply, and check the sensor reading against a local gauge.",
                    fixes=["Pump bearing re-greased and alignment checked. Power draw normal."]),
    "lim_hum": dict(type="limit_breach", w=1, eqs=["HV-AHU-01"], main="HV-AHU-01.humidity_pct", dir="high", extras=[], sev=[1, 1],
                    title=None, mtype="Inspection", cause="A reading has stayed outside its engineering limit. The cause is not yet known.",
                    rec="Inspect the equipment and its supply, and check the sensor reading against a local gauge.",
                    fixes=["Humidity sensor recalibrated by the instrument technician.", "Cooling coil drain cleared. Humidity back in range."]),
    "lim_tank2": dict(type="limit_breach", w=1, eqs=["WT-TNK-02"], main="WT-TNK-02.level_pct", dir="low", extras=[], sev=[1, 1],
                      title=None, mtype="Inspection", cause="A reading has stayed outside its engineering limit. The cause is not yet known.",
                      rec="Inspect the equipment and its supply, and check the sensor reading against a local gauge.",
                      fixes=["Inlet valve found partly closed and reopened. Level recovering."]),
    "lim_lel": dict(type="limit_breach", w=0, eqs=["GS-SKD-01"], main="GS-SKD-01.lel_pct", dir="high", extras=[("GS-SKD-01.pressure_bar", "low")],
                    sev=[3], safety=True, min_level=3, title="Combustible-gas reading above its limit at {eq_name}", mtype="Gas safety inspection",
                    cause="The combustible-gas reading is above its limit. Treat as a safety matter until the area has been checked.",
                    rec="Safety officer to attend now. Check the area with a handheld detector, ventilate if needed, and inspect the skid joints. Only certified operators may isolate or adjust anything.",
                    fixes=["Weeping flange on the skid outlet found and re-sealed. Area cleared with a handheld detector."]),
}

OPEN_PLAN = [   # (template, equipment, wanted severity level, minutes ago, final status, minutes to acknowledge, to investigate, to corrective action)
    ("lim_lel", "GS-SKD-01", 3, 9, "OPEN", None, None, None),
    ("chilled", "CW-CHL-02", 2, 134, "INVESTIGATING", 6, 14, None),
    ("air", "CA-HDR-B", 1, 3 * 24 * 60 + 5 * 60, "ASSIGNED", 35, None, None),
    ("tower", "CT-TWR-02", 2, 47, "ACKNOWLEDGED", 11, None, None),
    ("hvac", "HV-AHU-01", 1, 200, "CORRECTIVE_ACTION", 18, 32, 170),
    ("lim_tank2", "WT-TNK-02", 1, 26, "OPEN", None, None, None),
]


# ------------------------------------------------------------------------------------------------ building an incident
def _round(tag: str, v: float) -> float:
    return round(v, cat.SPEC[tag][1].decimals)


def value_for_level(tag: str, direction: str, want: int, rng: random.Random) -> float:
    """A reading just outside the normal band, pushed further out until it reaches the wanted level."""
    spec = cat.SPEC[tag][1]
    lo, hi = (cat.bands(tag)[0] or (None, None))
    edge = lo if direction == "low" else hi
    if edge is None:
        edge = spec.nominal * (0.8 if direction == "low" else 1.2)
    v = edge
    for step in range(1, 60):
        dev = step * 0.02 * rng.uniform(0.9, 1.1)
        v = edge - dev * abs(edge or 1) if direction == "low" else edge + dev * abs(edge or 1)
        if cat.level_of(tag, v) >= want:
            break
    return _round(tag, v)


def _evidence(tag: str, v: float) -> dict:
    e, s = cat.SPEC[tag]
    return {"tag": tag, "equipment": e.name, "label": s.label, "unit": s.unit, "value": v,
            "expected": cat.band_text(tag, "normal"), "level": cat.level_of(tag, v), "note": ""}


def build_incident(rng: random.Random, key: str, eq_id: str, want: int) -> dict:
    t = TEMPLATES[key]
    e = cat.BY_ID[eq_id]
    main = t["main"].format(eq=eq_id)
    v = value_for_level(main, t["dir"], want, rng)
    lvl = min(3, max(1, t.get("min_level", 1), cat.level_of(main, v)))
    ev = [_evidence(main, v)]
    for tag, d in t["extras"]:
        tag = tag.format(eq=eq_id)
        ev.append(_evidence(tag, value_for_level(tag, d, 1, rng)))
    label, unit = ev[0]["label"], ev[0]["unit"]
    title = (t["title"] or f"{label} {'above' if t['dir'] == 'high' else 'below'} its limit: {e.name}").format(zone=e.zone, eq=eq_id, eq_name=e.name)
    actual = f"{v:g} {unit}".strip()
    others = "; ".join(f"{x['label'].lower()} {x['value']:g} {x['unit']}".strip() for x in ev[1:])
    desc = f"{label} is {actual} (expected {ev[0]['expected']})." + (f" Also abnormal: {others}." if others else "")
    consumers = list(e.consumers)
    impact = (f"Supplies {', '.join(consumers)}. " if consumers else "") + (
        "Production stoppage or quality risk if the condition continues." if lvl >= 2 else "No production impact yet; watch the trend.")
    return {
        "type": t["type"], "key": key, "equipment_id": eq_id, "utility": e.utility, "zone": e.zone, "level": lvl, "severity": SEV[lvl],
        "title": title, "actual": actual, "expected": ev[0]["expected"], "description": desc,
        "probable_cause": t["cause"].format(zone=e.zone), "certainty": t.get("certainty", "PROBABLE"),
        "confidence": round(rng.uniform(0.62, 0.9), 2), "recommendation": t["rec"].format(zone=e.zone), "maintenance_type": t["mtype"],
        "consumers": consumers, "impact": impact, "evidence": ev, "safety": t.get("safety", False), "fixes": t["fixes"],
    }


def _analysis(a: dict, created: dt.datetime, verified: dt.datetime | None) -> dict:
    t = created.isoformat(timespec="seconds")
    e = cat.BY_ID[a["equipment_id"]]
    roles = agent.roles_for(a["severity"], a)
    steps = [
        {"key": "collected", "title": "Data collected", "ts": t, "ok": True, "detail": f"{len(a['evidence'])} sensor tags read (last 60 s window)."},
        {"key": "validated", "title": "Sensor readings validated", "ts": t, "ok": True, "detail": "All readings present, fresh and plausible."},
        {"key": "mapped", "title": "Equipment mapped", "ts": t, "ok": True,
         "detail": f"{e.name} ({e.id}) · {cat.UTILITY_LABEL[e.utility]} · {e.zone} · criticality {e.criticality}.", "consumers": a["consumers"]},
        {"key": "detected", "title": "Abnormal condition detected", "ts": t, "ok": True, "detail": a["description"], "rule": a["type"], "evidence": a["evidence"]},
        {"key": "root_cause", "title": "Root cause analysis completed", "ts": t, "ok": True, "detail": a["probable_cause"],
         "certainty": a["certainty"], "confidence": a["confidence"]},
        {"key": "impact", "title": "Production impact assessed", "ts": t, "ok": True, "detail": a["impact"]},
        {"key": "recommended", "title": "Recommendation generated", "ts": t, "ok": True, "detail": a["recommendation"]},
        {"key": "alerted", "title": "Alert sent", "ts": t, "ok": True, "detail": f"{a['severity']} alert raised and sent to: {', '.join(roles)}.", "roles": roles},
        {"key": "verification", "title": "Maintenance verification", "ts": verified.isoformat(timespec="seconds") if verified else None,
         "ok": True if verified else None,
         "detail": "Verified: fresh telemetry is inside the engineering limits." if verified else
                   "Pending: verification needs a recorded corrective action and fresh telemetry within limits."},
    ]
    return {"source": SOURCE, "explanation": agent.explain(a), "confidence": a["confidence"], "certainty": a["certainty"], "metrics": {}, "steps": steps}


# ------------------------------------------------------------------------------------------------ writing to the database
def _build(rng: random.Random, a: dict, created: dt.datetime, people: list[dict], final: str,
           ack: float | None, inv: float | None, corr: float | None, clear: float = 3, verify: float = 2) -> tuple[TwinAlert, list]:
    """One incident with its full audit trail, not yet written. Offsets are minutes after the previous step.
    Returns the alert and its child rows; the caller writes them in batches (one round trip each, not one per row)."""
    person = ppl.choose(people, a["utility"], a["zone"], created)
    who = person["name"] if person else "Unassigned"
    t_ack = created + dt.timedelta(minutes=ack) if ack is not None else None
    t_inv = t_ack + dt.timedelta(minutes=inv) if (t_ack and inv is not None) else None
    t_corr = (t_inv + dt.timedelta(minutes=corr)) if (t_inv and corr is not None) else None
    t_clear = t_corr + dt.timedelta(minutes=clear) if (t_corr and final == "VERIFIED") else None
    t_ver = t_clear + dt.timedelta(minutes=verify) if t_clear else None
    events: list[tuple] = [
        (created, "utilities-agent", "detected", f"{a['severity']} anomaly detected by rule {a['type']}."),
        (created, "utilities-agent", "analysis_completed", f"Root cause analysis completed ({a['certainty'].lower()} cause, confidence {a['confidence']:.0%})."),
        (created, "utilities-agent", "notified", f"Notified: {', '.join(agent.roles_for(a['severity'], a))}."),
    ]
    if person:
        events.append((created, "utilities-agent", "auto_assigned",
                       f"{person['name']} ({person['role']}, shift {person['shift']}) is on shift for {a['zone']} and was notified."))
    limit = ESCALATE_AFTER.get(a["severity"])
    escalated = bool(limit) and (t_ack is None or (t_ack - created).total_seconds() > limit)
    if escalated:
        t_esc = created + dt.timedelta(seconds=limit)
        events.append((t_esc, "utilities-agent", "escalated", f"Not acknowledged in time: escalated to {ESCALATE_TO[a['severity']]}."))
    if t_ack:
        events.append((t_ack, who, "acknowledged", "Alert acknowledged."))
    if final == "ASSIGNED" and t_ack:
        events.append((t_ack, who, "assigned", f"Assigned to {who}."))
    if t_inv:
        events.append((t_inv, who, "investigating", "Investigation started."))
        if a["level"] >= 2 and rng.random() < 0.7:
            events.append((t_inv + dt.timedelta(minutes=2), who, "comment", rng.choice(COMMENTS)))
    fix = rng.choice(a["fixes"])
    if t_corr:
        events.append((t_corr, who, "corrective_action", fix))
    if t_clear:
        events.append((t_clear, "utilities-agent", "condition_cleared", "Telemetry is back inside the engineering limits. Awaiting an inspection record and verification."))
    if t_ver:
        events.append((t_ver, "utilities-agent", "verified", "Recovery verified from telemetry. Alert closed. Fresh telemetry is inside the engineering limits."))
    events.sort(key=lambda x: x[0])
    last = events[-1][0]

    row = TwinAlert(
        created_at=created, updated_at=last, utility=a["utility"], equipment_id=a["equipment_id"], zone=a["zone"], severity=a["severity"],
        anomaly_type=a["type"], title=a["title"][:200], actual=a["actual"][:160], expected=a["expected"][:160], description=a["description"],
        probable_cause=a["probable_cause"], cause_certainty=a["certainty"], confidence=a["confidence"], recommendation=a["recommendation"],
        impact=a["impact"], consumers=a["consumers"], status=final, assigned_to=who if person else None, source=SOURCE,
        acknowledged_at=t_ack, closed_at=t_ver, verification_note="Fresh telemetry is inside the engineering limits." if t_ver else None,
        analysis=_analysis(a, created, t_ver), evidence=a["evidence"])
    kids: list = [TwinAlertEvent(ts=ts, actor=actor, action=action, detail=detail) for ts, actor, action, detail in events]
    for role in agent.roles_for(a["severity"], a):
        kids.append(TwinNotification(ts=created, recipient=role, level=a["severity"],
                                     message=f"{a['severity']}: {a['title']} ({a['equipment_id']})"))
    if person:
        kids.append(TwinNotification(ts=created, recipient=person["name"], level=a["severity"],
                                     message=f"Assigned to you: {a['title']} ({a['equipment_id']})"))
    if escalated:
        kids.append(TwinNotification(ts=created + dt.timedelta(seconds=limit), recipient=ESCALATE_TO[a["severity"]],
                                     level=a["severity"], escalated=True,
                                     message=f"ESCALATED: {a['title']} has not been acknowledged ({a['severity']})."))
    m_status = {"VERIFIED": "VERIFIED", "CORRECTIVE_ACTION": "COMPLETED", "INVESTIGATING": "IN_PROGRESS", "ASSIGNED": "ASSIGNED"}.get(final, "PENDING")
    kids.append(TwinMaintenance(
        equipment_id=a["equipment_id"], maintenance_type=a["maintenance_type"], problem=a["title"][:240],
        recommendation=a["recommendation"], priority=PRIORITY[a["severity"]], assigned_to=who if person else None, status=m_status,
        planned_date=created.date() + dt.timedelta(days=PLANNED_DAYS[a["severity"]]), source=SOURCE, created_at=created,
        resolution=fix if t_corr else None, completed_at=t_corr, verified_at=t_ver))
    return row, kids


def clear_mock(s: Session) -> dict:
    ids = list(s.scalars(select(TwinAlert.id).where(TwinAlert.source == SOURCE)))
    if ids:
        s.execute(delete(TwinNotification).where(TwinNotification.alert_id.in_(ids)))
        s.execute(delete(TwinMaintenance).where(TwinMaintenance.alert_id.in_(ids)))
        s.execute(delete(TwinAlertEvent).where(TwinAlertEvent.alert_id.in_(ids)))
        s.execute(delete(TwinAlert).where(TwinAlert.id.in_(ids)))
    n_people = s.execute(delete(TwinPerson)).rowcount
    return {"alerts_removed": len(ids), "people_removed": n_people}


def seed(closed: int = 26, now: dt.datetime | None = None, rng_seed: int = 7) -> dict:
    """Replace the mock roster and incidents. Safe to run again at any time."""
    now = (now or dt.datetime.now()).replace(microsecond=0)
    rng = random.Random(rng_seed)
    hours = list(range(24))
    weights = [1, 1, 1, 1, 1, 2, 4, 6, 7, 7, 7, 6, 6, 7, 7, 7, 6, 5, 4, 3, 2, 2, 1, 1]
    keys = [k for k, t in TEMPLATES.items() if t["w"] > 0]
    kweights = [TEMPLATES[k]["w"] for k in keys]
    with SessionLocal() as s:
        removed = clear_mock(s)
        for name, role, team, shift, ext, zones in ROSTER:
            s.add(TwinPerson(name=name, role=role, team=team, shift=shift, phone_ext=ext, zones=zones, active=True))
        s.flush()
        people = ppl.load_people(s)

        plans = []
        for _ in range(closed):
            key = rng.choices(keys, kweights)[0]
            t = TEMPLATES[key]
            a = build_incident(rng, key, rng.choice(t["eqs"]), rng.choice(t["sev"]))
            lvl = a["level"]
            ack = rng.uniform(*{1: (4, 35), 2: (2, 12), 3: (1, 4)}[lvl])
            inv = rng.uniform(3, 12)
            corr = rng.uniform(*{1: (60, 300), 2: (30, 150), 3: (20, 90)}[lvl])
            clear, verify = rng.uniform(2, 6), rng.uniform(1, 3)
            span = dt.timedelta(minutes=ack + inv + corr + clear + verify)
            day = rng.uniform(0.4, 29.5)
            base = (now - dt.timedelta(days=day)).replace(hour=rng.choices(hours, weights)[0], minute=rng.randrange(60), second=rng.randrange(60))
            while base + span > now - dt.timedelta(hours=1):
                base -= dt.timedelta(days=1)
            plans.append((base, a, ack, inv, corr, clear, verify))
        plans.sort(key=lambda p: p[0])
        built = []
        for base, a, ack, inv, corr, clear, verify in plans:
            built.append(_build(rng, a, base.replace(microsecond=0), people, "VERIFIED", ack, inv, corr, clear, verify))
        for key, eq, want, ago, final, ack, inv, corr in OPEN_PLAN:
            a = build_incident(rng, key, eq, want)
            built.append(_build(rng, a, now - dt.timedelta(minutes=ago), people, final, ack, inv, corr))
        # write in batches: all alerts at once, then every child row at once
        s.add_all([row for row, _ in built])
        s.flush()
        for row, kids in built:
            row.code = f"ALT-{row.id:05d}"
            for k in kids:
                k.alert_id = row.id
            s.add_all(kids)
        s.commit()
    return {"people": len(ROSTER), "closed_incidents": closed, "open_incidents": len(OPEN_PLAN), "replaced": removed, "as_of": now.isoformat()}
