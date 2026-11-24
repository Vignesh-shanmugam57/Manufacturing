"""SIMULATED telemetry source. Nothing here is a measurement of a real plant.

It produces plausible, continuously moving readings for every sensor in the catalog (production load swings through
the day, noise, lag) and can inject one of seven utility faults. The engine treats it like any other adapter; a real
SCADA/BMS/IoT gateway replaces it by pushing readings to /api/twin/ingest.
"""
from __future__ import annotations

import datetime as dt
import math
import random

from app.twin import catalog as cat

# effect: (mode, amount[, period_s]).  add / mul / set / osc, scaled by the scenario progress 0..1 (and intensity).
SCENARIOS: dict[str, dict] = {
    "compressed_air_leak": {
        "title": "Compressed air leakage", "utility": "COMPRESSED_AIR", "equipment": "CA-HDR-A", "ramp_s": 40,
        "text": "Pressure drops in Hall A while airflow stays high, the compressor loads up and uses more power.",
        "effects": {
            "CA-HDR-A.pressure_bar": ("add", -0.75), "CA-HDR-A.flow_m3min": ("mul", 1.55),
            "CA-CMP-01.pressure_bar": ("add", -0.6), "CA-CMP-01.flow_m3min": ("mul", 1.4),
            "CA-CMP-01.load_pct": ("add", 26), "CA-CMP-01.power_kw": ("mul", 1.3), "CA-CMP-01.cycles_hr": ("add", 10),
            "CA-RCV-01.pressure_bar": ("add", -0.55),
        }},
    "steam_pressure_instability": {
        "title": "Steam pressure instability", "utility": "STEAM", "equipment": "ST-HDR-01", "ramp_s": 30,
        "text": "Steam header pressure swings, the boiler temperature drifts and efficiency falls.",
        "effects": {
            "ST-HDR-01.pressure_bar": ("osc", 2.6, 9), "ST-BLR-01.pressure_bar": ("osc", 2.2, 9),
            "ST-BLR-01.temp_c": ("add", 9), "ST-BLR-01.efficiency_pct": ("add", -7.5), "ST-BLR-01.fuel_nm3hr": ("mul", 1.18),
        }},
    "chilled_water_low_delta_t": {
        "title": "Chilled water low Delta T", "utility": "CHILLED_WATER", "equipment": "CW-CHL-01", "ramp_s": 35,
        "text": "Return temperature falls toward the supply temperature, so Delta T collapses while flow and power rise.",
        "effects": {
            "CW-CHL-01.return_c": ("add", -2.8), "CW-CHL-01.flow_m3hr": ("mul", 1.22), "CW-CHL-01.power_kw": ("mul", 1.18),
            "CW-PMP-01.flow_m3hr": ("mul", 1.2), "CW-PMP-01.power_kw": ("mul", 1.25),
        }},
    "cooling_tower_fan_failure": {
        "title": "Cooling tower fan failure", "utility": "COOLING_TOWER", "equipment": "CT-TWR-01", "ramp_s": 20,
        "text": "The tower 1 fan stops, so the outlet water temperature climbs.",
        "effects": {
            "CT-TWR-01.fan_on": ("set", 0), "CT-TWR-01.fan_pct": ("set", 0),
            "CT-TWR-01.outlet_c": ("add", 5.5), "CT-TWR-01.inlet_c": ("add", 2.0),
        }},
    "hvac_airflow_imbalance": {
        "title": "HVAC airflow imbalance", "utility": "HVAC", "equipment": "HV-AHU-02", "ramp_s": 35,
        "text": "Airflow falls in Hall B, the zone warms up and the unit draws more power.",
        "effects": {
            "HV-AHU-02.airflow_m3hr": ("mul", 0.62), "HV-AHU-02.zone_temp_c": ("add", 3.2),
            "HV-AHU-02.return_c": ("add", 2.5), "HV-AHU-02.power_kw": ("add", 4.0),
        }},
    "water_leak": {
        "title": "Water leakage", "utility": "WATER", "equipment": "WT-TNK-01", "ramp_s": 60,
        "text": "The storage tank level keeps falling while main flow and booster pump flow stay high.",
        "effects": {
            "WT-TNK-01.level_pct": ("add", -46), "WT-MTR-01.flow_m3hr": ("mul", 1.75),
            "WT-PMP-01.flow_m3hr": ("mul", 1.5), "WT-PMP-01.power_kw": ("mul", 1.3), "WT-TNK-01.outflow_m3hr": ("mul", 1.8),
        }},
    "gas_abnormal_consumption": {
        "title": "Abnormal gas consumption", "utility": "GAS", "equipment": "GS-SKD-01", "ramp_s": 30,
        "text": "Gas flow roughly doubles, supply pressure sags and the combustible-gas reading rises.",
        "effects": {
            "GS-SKD-01.flow_nm3hr": ("mul", 1.95), "GS-MTR-01.flow_nm3hr": ("mul", 1.95),
            "GS-SKD-01.pressure_bar": ("add", -0.55), "GS-SKD-01.lel_pct": ("add", 9.0),
        }},
}


class Simulator:
    """Steps every sensor forward in time. Deterministic when `seed` is given."""

    def __init__(self, seed: int | None = None, start: dt.datetime | None = None):
        self.rng = random.Random(seed)
        self.t = 0.0                                   # seconds since start
        self.values: dict[str, float] = {}
        self.scenario: str | None = None
        self.intensity = 1.0
        self.phase = "idle"                            # idle | ramping | active | recovering
        self.progress = 0.0
        self.counters = {"air_m3": 0.0, "steam_kg": 0.0, "chilled_kwh_th": 0.0, "cooling_makeup_m3": 0.0,
                         "hvac_kwh": 0.0, "water_m3": 0.0, "gas_nm3": 0.0, "energy_kwh": 0.0, "units": 0.0}
        self._walk = 0.0
        now = start or dt.datetime.now()
        load = self.production_load(now)
        for tag, (e, s) in cat.SPEC.items():
            self.values[tag] = self._base(e, s, load) if not s.cumulative else s.nominal
        self._derive()

    # ------------------------------------------------------------------ production
    def production_load(self, now: dt.datetime) -> float:
        """0.45-0.95: a day/night shift pattern with a slow wobble. SIMULATED MES demand."""
        h = now.hour + now.minute / 60
        shift = 0.17 * math.sin(2 * math.pi * (h - 9) / 24)
        return max(0.45, min(0.95, 0.68 + shift + 0.03 * math.sin(self.t / 37) + self._walk))

    def _base(self, e: cat.Equipment, s: cat.SensorSpec, load: float) -> float:
        rel = s.load_gain * (load - 0.7) / 0.7
        return s.nominal * (1 + rel)

    # ------------------------------------------------------------------ scenarios
    def start(self, name: str, intensity: float = 1.0) -> None:
        if name not in SCENARIOS:
            raise ValueError(f"Unknown scenario '{name}'. Use one of {list(SCENARIOS)}.")
        self.scenario, self.intensity, self.phase, self.progress = name, max(0.3, min(2.0, intensity)), "ramping", 0.0

    def fix(self) -> bool:
        """Simulated corrective action: the telemetry returns to normal. Real interventions stay with operators."""
        if self.scenario and self.phase in ("ramping", "active"):
            self.phase = "recovering"
            return True
        return False

    def reset(self) -> None:
        self.scenario, self.phase, self.progress, self.intensity = None, "idle", 0.0, 1.0

    def _advance_scenario(self, dt_s: float) -> None:
        if not self.scenario:
            return
        ramp = SCENARIOS[self.scenario]["ramp_s"]
        if self.phase == "ramping":
            self.progress = min(1.0, self.progress + dt_s / ramp)
            if self.progress >= 1.0:
                self.phase = "active"
        elif self.phase == "recovering":
            self.progress = max(0.0, self.progress - dt_s / 12.0)
            if self.progress <= 0.0:
                self.scenario, self.phase = None, "idle"

    def state(self) -> dict:
        sc = SCENARIOS.get(self.scenario) if self.scenario else None
        return {"active": self.scenario, "phase": self.phase, "progress": round(self.progress, 3),
                "intensity": self.intensity, "title": sc["title"] if sc else None,
                "utility": sc["utility"] if sc else None, "equipment": sc["equipment"] if sc else None}

    # ------------------------------------------------------------------ one step
    def step(self, dt_s: float, now: dt.datetime) -> dict[str, float]:
        self.t += dt_s
        self._walk = max(-0.08, min(0.08, self._walk + self.rng.gauss(0, 0.004)))
        self._advance_scenario(dt_s)
        load = self.production_load(now)
        fx = SCENARIOS[self.scenario]["effects"] if self.scenario else {}
        p = self.progress
        for tag, (e, s) in cat.SPEC.items():
            if s.cumulative:
                continue
            target = self._base(e, s, load)
            eff = fx.get(tag)
            if eff:
                mode, amt = eff[0], eff[1]
                k = p * (1.0 if mode == "set" else self.intensity)
                if mode == "add":
                    target += amt * k
                elif mode == "mul":
                    target *= 1 + (amt - 1) * k
                elif mode == "set":
                    target = target * (1 - p) + amt * p
                elif mode == "osc":
                    target += amt * math.sin(2 * math.pi * self.t / eff[2]) * k
            a = 1 - math.exp(-dt_s / max(s.tau, 0.5))
            v = self.values[tag] + (target - self.values[tag]) * a
            self.values[tag] = v
        self._derive()
        self._counters(dt_s, load)
        out = {}
        for tag, (e, s) in cat.SPEC.items():
            v = self.values[tag]
            if not s.cumulative and s.noise:
                v += self.rng.gauss(0, s.noise)
            v = max(0.0, v) if s.unit not in ("°C",) else v
            if s.unit == "%":
                v = min(100.0, v)            # a percentage reading cannot exceed 100
            out[tag] = round(v, s.decimals)
        return out

    def _derive(self) -> None:
        for e in cat.EQUIPMENT:
            if e.category == "chiller":
                self.values[e.tag("delta_t_c")] = self.values[e.tag("return_c")] - self.values[e.tag("supply_c")]

    def _counters(self, dt_s: float, load: float) -> None:
        h = dt_s / 3600
        c, v = self.counters, self.values
        for e in cat.EQUIPMENT:
            if e.category == "compressor":
                c["air_m3"] += v[e.tag("flow_m3min")] * 60 * h
                v[e.tag("runtime_h")] += h * max(0.0, min(1.0, v[e.tag("load_pct")] / 100)) * (0.25 if e.standby else 1)
            elif e.category == "boiler":
                c["steam_kg"] += v[e.tag("flow_kghr")] * h
                v[e.tag("runtime_h")] += h * (0.3 if e.standby else 1)
            elif e.category == "chiller":
                c["chilled_kwh_th"] += v[e.tag("load_kw")] * h
                v[e.tag("runtime_h")] += h
            elif e.category == "tower":
                c["cooling_makeup_m3"] += v[e.tag("makeup_m3hr")] * h
                v[e.tag("runtime_h")] += h * (1 if v[e.tag("fan_on")] > 0.5 else 0.2)
            elif e.category == "ahu":
                c["hvac_kwh"] += v[e.tag("power_kw")] * h
                v[e.tag("runtime_h")] += h
            elif e.category == "pump":
                v[e.tag("runtime_h")] += h
            elif e.id == "WT-MTR-01":
                c["water_m3"] += v[e.tag("flow_m3hr")] * h
                v[e.tag("consumed_m3")] += v[e.tag("flow_m3hr")] * h
            elif e.id == "GS-MTR-01":
                c["gas_nm3"] += v[e.tag("flow_nm3hr")] * h
                v[e.tag("consumed_nm3")] += v[e.tag("flow_nm3hr")] * h
            if "power_kw" in {s.key for s in e.sensors}:
                c["energy_kwh"] += v[e.tag("power_kw")] * h
        c["units"] += 165 * (load / 0.7) * h              # SIMULATED MES production count
