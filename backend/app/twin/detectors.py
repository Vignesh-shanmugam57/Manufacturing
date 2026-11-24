"""Deterministic anomaly rules. Safety-relevant detection never depends on an LLM.

Each rule reads live values and the confirmed (debounced) sensor levels from a `View` and returns anomaly dicts.
Causes are labelled PROBABLE unless a measured status signal proves them (CONFIRMED).
"""
from __future__ import annotations

import statistics
from typing import Protocol

from app.twin import catalog as cat

SEV = {1: "WARNING", 2: "MAJOR", 3: "CRITICAL"}


class View(Protocol):
    values: dict[str, float]
    levels: dict[str, int]

    def hist(self, tag: str, seconds: int) -> list[float]: ...
    def baseline(self, tag: str) -> float: ...


def ev(view: View, tag: str, note: str = "") -> dict:
    e, s = cat.SPEC[tag]
    v = view.values.get(tag)
    return {"tag": tag, "equipment": e.name, "label": s.label, "unit": s.unit, "value": v,
            "expected": cat.band_text(tag, "normal"), "level": view.levels.get(tag, 0), "note": note}


def _fmt(tag: str, v: float) -> str:
    e, s = cat.SPEC[tag]
    return f"{v:.{s.decimals}f} {s.unit}".strip()


def _low(tag: str, v: float) -> bool:
    normal = cat.bands(tag)[0]
    return bool(normal and normal[0] is not None and v < normal[0])


def _high(tag: str, v: float) -> bool:
    normal = cat.bands(tag)[0]
    return bool(normal and normal[1] is not None and v > normal[1])


def _consumers(eq_ids: list[str]) -> list[str]:
    out: list[str] = []
    for i in eq_ids:
        for c in cat.BY_ID[i].consumers:
            if c not in out:
                out.append(c)
    return out


def _anomaly(view: View, *, type: str, equipment_id: str, level: int, title: str, tag: str, description: str,
             cause: str, certainty: str, confidence: float, recommendation: str, maintenance: str, supporting: list[str],
             covers: list[str], min_level: int = 1, extra: dict | None = None) -> dict:
    e = cat.BY_ID[equipment_id]
    tags = [tag] + [t for t in supporting if t != tag]
    consumers = _consumers(covers or [equipment_id])
    lvl = max(min_level, min(3, level))
    return {
        "type": type, "equipment_id": equipment_id, "utility": e.utility, "zone": e.zone, "level": lvl,
        "severity": SEV[lvl], "title": title,
        "actual": _fmt(tag, view.values[tag]), "expected": cat.band_text(tag, "normal"),
        "description": description, "probable_cause": cause, "certainty": certainty, "confidence": round(min(confidence, 0.95), 2),
        "recommendation": recommendation, "maintenance_type": maintenance, "consumers": consumers,
        "impact": (f"Supplies {', '.join(consumers)}. " if consumers else "") +
                  ("Production stoppage or quality risk if the condition continues." if lvl >= 2
                   else "No production impact yet; watch the trend."),
        "sensors": tags, "evidence": [ev(view, t) for t in tags], "covers": covers or [equipment_id], **(extra or {}),
    }


def air_leakage(view: View) -> list[dict]:
    out = []
    for hid in ("CA-HDR-A", "CA-HDR-B"):
        e = cat.BY_ID[hid]
        p_tag, f_tag = e.tag("pressure_bar"), e.tag("flow_m3min")
        p, f = view.values[p_tag], view.values[f_tag]
        base = max(view.baseline(f_tag), 0.1)
        if not (_low(p_tag, p) and f > base * 1.15):
            continue
        cmp_ = cat.BY_ID["CA-CMP-01"]
        load, power = view.values[cmp_.tag("load_pct")], view.values[cmp_.tag("power_kw")]
        support = [cmp_.tag("load_pct"), cmp_.tag("power_kw"), cmp_.tag("pressure_bar"), "CA-RCV-01.pressure_bar"]
        conf = 0.5 + 0.12 * (f > base * 1.3) + 0.1 * (load > 85) + 0.1 * _high(cmp_.tag("power_kw"), power) \
            + 0.1 * _high(cmp_.tag("cycles_hr"), view.values[cmp_.tag("cycles_hr")])
        leak = max(0.0, f - base)
        out.append(_anomaly(
            view, type="compressed_air_leakage", equipment_id=hid, level=view.levels.get(p_tag, 1), tag=p_tag,
            title=f"Possible compressed air leakage in {e.zone}",
            description=(f"Header pressure is {p:.2f} bar (expected {cat.band_text(p_tag)}) while air flow is {f:.1f} m3/min, "
                         f"{(f / base - 1) * 100:.0f}% above its recent baseline of {base:.1f}. Compressor 1 is at {load:.0f}% load "
                         f"and {power:.0f} kW. Estimated extra flow: {leak:.1f} m3/min."),
            cause=(f"Possible air leakage in the distribution piping, or an abnormal demand, in {e.zone}. This is inferred from "
                   "the pressure and flow pattern; the leak location is not confirmed."),
            certainty="PROBABLE", confidence=min(conf, 0.92),
            recommendation=(f"Inspect the compressed air pipeline and connections in {e.zone} for leakage (ultrasonic survey), check "
                            "the compressor loading and unloading cycles, and compare demand with the production schedule. "
                            "Any setpoint change must be made by an authorised operator."),
            maintenance="Leak inspection", supporting=[f_tag] + support,
            covers=[hid, "CA-CMP-01", "CA-CMP-02", "CA-RCV-01"], extra={"leak_est": round(leak, 2)}))
    return out


def steam_instability(view: View) -> list[dict]:
    tag = "ST-HDR-01.pressure_bar"
    h = view.hist(tag, 30)
    if len(h) < 15:
        return []
    sd = statistics.pstdev(h)
    lvl = view.levels.get(tag, 0)
    if sd < 0.3 and lvl < 2:
        return []
    b = cat.BY_ID["ST-BLR-01"]
    return [_anomaly(
        view, type="steam_pressure_instability", equipment_id="ST-HDR-01", level=max(1, lvl, 2 if sd > 0.6 else 1), tag=tag,
        title="Unstable steam header pressure",
        description=(f"Steam header pressure swings between {min(h):.2f} and {max(h):.2f} bar over the last 30 s "
                     f"(standard deviation {sd:.2f} bar, expected band {cat.band_text(tag)}). Boiler 1 temperature is "
                     f"{view.values[b.tag('temp_c')]:.0f} °C and efficiency {view.values[b.tag('efficiency_pct')]:.1f}%."),
        cause=("Probable unstable boiler firing or steam demand swings, possibly a control or burner issue. "
               "No fault has been confirmed."),
        certainty="PROBABLE", confidence=min(0.55 + 0.2 * (sd > 0.6) + 0.1 * (view.levels.get(b.tag("temp_c"), 0) > 0)
                                           + 0.1 * (view.levels.get(b.tag("efficiency_pct"), 0) > 0), 0.9),
        recommendation=("Inspect boiler 1 operating conditions (burner, feedwater and pressure control) and the steam header "
                        "for demand swings. Review the pressure control setpoint with the certified operator."),
        maintenance="Boiler inspection", supporting=[b.tag("pressure_bar"), b.tag("temp_c"), b.tag("efficiency_pct"), b.tag("fuel_nm3hr")],
        covers=["ST-HDR-01", "ST-BLR-01", "ST-BLR-02"])]


def chilled_low_delta_t(view: View) -> list[dict]:
    out = []
    for cid in ("CW-CHL-01", "CW-CHL-02"):
        e = cat.BY_ID[cid]
        t = e.tag("delta_t_c")
        v = view.values[t]
        if not _low(t, v):
            continue
        out.append(_anomaly(
            view, type="chilled_water_low_delta_t", equipment_id=cid, level=view.levels.get(t, 1), tag=t,
            title=f"Low chilled water Delta T on {e.name}",
            description=(f"Delta T is {v:.2f} °C (expected {cat.band_text(t)}): supply {view.values[e.tag('supply_c')]:.1f} °C, "
                         f"return {view.values[e.tag('return_c')]:.1f} °C. Flow is {view.values[e.tag('flow_m3hr')]:.0f} m3/h and "
                         f"power {view.values[e.tag('power_kw')]:.0f} kW."),
            cause=("Probable low Delta T syndrome: excess water flow or bypass, a control valve passing, or poor coil heat "
                   "transfer. Not confirmed."),
            certainty="PROBABLE", confidence=0.6 + 0.1 * _high(e.tag("flow_m3hr"), view.values[e.tag("flow_m3hr")]) + 0.1 * _high(e.tag("power_kw"), view.values[e.tag("power_kw")]),
            recommendation=("Review chilled water supply and return temperatures, check the pump flow and the bypass or control "
                            "valves, and compare coil performance. Balance flow with the certified operator."),
            maintenance="Performance check", supporting=[e.tag("supply_c"), e.tag("return_c"), e.tag("flow_m3hr"), e.tag("power_kw"), "CW-PMP-01.flow_m3hr"],
            covers=[cid, "CW-PMP-01", "CW-PMP-02"]))
    return out


def tower_fan(view: View) -> list[dict]:
    out = []
    for tid in ("CT-TWR-01", "CT-TWR-02"):
        e = cat.BY_ID[tid]
        fan = e.tag("fan_on")
        if view.values[fan] >= 0.5:
            continue
        o = e.tag("outlet_c")
        out.append(_anomaly(
            view, type="cooling_tower_fan_failure", equipment_id=tid, level=max(2, view.levels.get(o, 0)), tag=fan,
            title=f"{e.name} fan stopped",
            description=(f"The fan status signal reads stopped (fan speed {view.values[e.tag('fan_pct')]:.0f}%). Outlet water is "
                         f"{view.values[o]:.1f} °C (expected {cat.band_text(o)}) and inlet {view.values[e.tag('inlet_c')]:.1f} °C."),
            cause=("The fan is confirmed stopped by its status signal. Why it stopped (motor trip, VFD fault, vibration cut-out) "
                   "is a probable cause that needs inspection."),
            certainty="CONFIRMED", confidence=0.95,
            recommendation=(f"Inspect {e.name} fan, motor and drive, check trip and alarm history, and review the tower cooling "
                            "performance. Restarting the fan is a decision for the authorised operator."),
            maintenance="Fan inspection", supporting=[e.tag("fan_pct"), o, e.tag("inlet_c"), e.tag("flow_m3hr")],
            covers=[tid, "CT-PMP-01"], min_level=2))
    return out


def hvac_airflow(view: View) -> list[dict]:
    out = []
    for aid in ("HV-AHU-01", "HV-AHU-02"):
        e = cat.BY_ID[aid]
        a = e.tag("airflow_m3hr")
        v = view.values[a]
        if not _low(a, v):
            continue
        zt = e.tag("zone_temp_c")
        out.append(_anomaly(
            view, type="hvac_airflow_imbalance", equipment_id=aid, level=view.levels.get(a, 1), tag=a,
            title=f"HVAC airflow imbalance on {e.name}",
            description=(f"Airflow is {v:,.0f} m3/h (expected {cat.band_text(a)}). Zone temperature is {view.values[zt]:.1f} °C "
                         f"(expected {cat.band_text(zt)}), return air {view.values[e.tag('return_c')]:.1f} °C, power "
                         f"{view.values[e.tag('power_kw')]:.1f} kW."),
            cause=("Probable restricted airflow (dirty filters, damper position or fan belt/drive) or a balancing problem. "
                   "Not confirmed."),
            certainty="PROBABLE", confidence=0.58 + 0.15 * (view.levels.get(zt, 0) > 0) + 0.1 * _high(e.tag("power_kw"), view.values[e.tag("power_kw")]),
            recommendation=("Check filters, dampers and fan drive, and re-balance the airflow for the zone with the facilities team."),
            maintenance="Airflow balancing", supporting=[zt, e.tag("return_c"), e.tag("supply_c"), e.tag("power_kw")], covers=[aid]))
    return out


def water_leak(view: View) -> list[dict]:
    lv, fl = "WT-TNK-01.level_pct", "WT-MTR-01.flow_m3hr"
    h = view.hist(lv, 30)
    if len(h) < 20:
        return []
    slope = (h[-1] - h[0]) / max(len(h) - 1, 1)             # % per second
    base = max(view.baseline(fl), 0.1)
    flow_high = view.values[fl] > base * 1.2 or _high(fl, view.values[fl])
    if not ((slope < -0.05 and flow_high) or (_low(lv, view.values[lv]) and flow_high)):
        return []
    return [_anomaly(
        view, type="water_leak", equipment_id="WT-TNK-01", level=max(1, view.levels.get(lv, 0), view.levels.get(fl, 0)), tag=lv,
        title="Possible water leakage: tank level falling",
        description=(f"Storage tank level is {view.values[lv]:.1f}% and falling {abs(slope) * 60:.1f}% per minute while main flow is "
                     f"{view.values[fl]:.1f} m3/h, {(view.values[fl] / base - 1) * 100:.0f}% above its baseline of {base:.1f}."),
        cause="Probable leak in the water distribution or tank, or uncontrolled consumption. The location is not confirmed.",
        certainty="PROBABLE", confidence=0.62 + 0.15 * (slope < -0.2) + 0.1 * (view.levels.get("WT-PMP-01.flow_m3hr", 0) > 0),
        recommendation="Inspect the water pipelines, tank connections and booster pump operation; compare with the production water demand.",
        maintenance="Leak inspection", supporting=[fl, "WT-PMP-01.flow_m3hr", "WT-PMP-01.power_kw", "WT-TNK-01.outflow_m3hr"],
        covers=["WT-TNK-01", "WT-TNK-02", "WT-PMP-01", "WT-MTR-01"], extra={"level_slope_pct_min": round(slope * 60, 2)})]


def gas_abnormal(view: View) -> list[dict]:
    f, p, lel = "GS-SKD-01.flow_nm3hr", "GS-SKD-01.pressure_bar", "GS-SKD-01.lel_pct"
    base = max(view.baseline(f), 1.0)
    flow_hi = view.values[f] > base * 1.4 or view.levels.get(f, 0) >= 1
    p_low = _low(p, view.values[p]) or _high(p, view.values[p])
    gas_alarm = view.levels.get(lel, 0) >= 1
    if not (flow_hi or p_low or gas_alarm):
        return []
    level = 3 if view.levels.get(lel, 0) >= 2 else max(2, view.levels.get(f, 0), view.levels.get(p, 0))
    safety = gas_alarm
    return [_anomaly(
        view, type="gas_abnormal_consumption", equipment_id="GS-SKD-01", level=level, tag=lel if gas_alarm else f,
        title="Gas safety alarm: elevated combustible gas reading" if safety else "Abnormal gas consumption",
        description=(f"Gas flow is {view.values[f]:.0f} Nm3/h ({(view.values[f] / base - 1) * 100:+.0f}% vs baseline {base:.0f}), pressure "
                     f"{view.values[p]:.2f} bar (expected {cat.band_text(p)}) and combustible gas {view.values[lel]:.1f}% LEL "
                     f"(expected {cat.band_text(lel)})."),
        cause=("Abnormal gas use by a consumer or a possible gas leak. This is probable only; confirm with a portable gas "
               "detector under the site safety procedure."),
        certainty="PROBABLE", confidence=0.6 + 0.2 * gas_alarm + 0.1 * flow_hi,
        recommendation=("Gas-related alarm: treat as high priority. Follow the site gas-safety procedure, verify the reading with a "
                        "portable detector, and have the certified operator inspect the supply line and consumers."),
        maintenance="Gas safety inspection", supporting=[f, p, lel, "GS-MTR-01.flow_nm3hr"],
        covers=["GS-SKD-01", "GS-MTR-01"], min_level=2, extra={"safety": True})]


COMPOSITE = (air_leakage, steam_instability, chilled_low_delta_t, tower_fan, hvac_airflow, water_leak, gas_abnormal)


def limit_breaches(view: View, covered: set[str]) -> list[dict]:
    """Any equipment with a MAJOR or CRITICAL confirmed reading that no composite rule already explains."""
    out = []
    for e in cat.EQUIPMENT:
        if e.id in covered:
            continue
        worst = max(((view.levels.get(e.tag(s.key), 0), s) for s in e.sensors if not s.cumulative), key=lambda x: x[0], default=(0, None))
        if worst[0] < 2:
            continue
        s = worst[1]
        tag = e.tag(s.key)
        out.append(_anomaly(
            view, type="limit_breach", equipment_id=e.id, level=worst[0], tag=tag,
            title=f"{e.name}: {s.label.lower()} outside engineering limits",
            description=f"{s.label} is {_fmt(tag, view.values[tag])}, outside its normal range {cat.band_text(tag)}.",
            cause="A configured engineering limit is exceeded. The cause is not yet determined.",
            certainty="PROBABLE", confidence=0.5,
            recommendation=f"Inspect {e.name} and check the {s.label.lower()} sensor and operating conditions.",
            maintenance="Inspection", supporting=[], covers=[e.id]))
    return out


def detect(view: View) -> list[dict]:
    found: list[dict] = []
    for rule in COMPOSITE:
        found.extend(rule(view))
    covered = {c for a in found for c in a["covers"]}
    found.extend(limit_breaches(view, covered))
    return found
