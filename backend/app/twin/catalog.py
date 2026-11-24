"""Equipment master, sensor tags and engineering limits for the seven utility systems.

Limits are bands around a sensor's value. A value is
  NORMAL    inside `normal`
  WARNING   outside `normal` but inside `warn`     (yellow)
  MAJOR     outside `warn` but inside `crit`        (orange)
  CRITICAL  outside `crit`                          (red)
`None` means unbounded on that side. The numbers are DEMO engineering limits: replace them on the Configuration page
with the site-engineered limits before the agent is used on a real plant.
"""
from __future__ import annotations

from dataclasses import dataclass, field

UTILITIES = ["COMPRESSED_AIR", "STEAM", "CHILLED_WATER", "COOLING_TOWER", "HVAC", "WATER", "GAS"]
UTILITY_LABEL = {
    "COMPRESSED_AIR": "Compressed air", "STEAM": "Steam", "CHILLED_WATER": "Chilled water",
    "COOLING_TOWER": "Cooling tower", "HVAC": "HVAC", "WATER": "Water", "GAS": "Gas",
}
LEVELS = ["NORMAL", "WARNING", "MAJOR", "CRITICAL", "OFFLINE"]       # index = level number used everywhere

Band = tuple[float | None, float | None]


@dataclass(frozen=True)
class SensorSpec:
    key: str
    label: str
    unit: str
    nominal: float
    normal: Band | None = None
    warn: Band | None = None
    crit: Band | None = None
    noise: float = 0.0
    load_gain: float = 0.0       # relative change of the value per +0.1 of production load (simulation only)
    cumulative: bool = False     # a counter (runtime, consumption), never evaluated against limits
    decimals: int = 2
    tau: float = 4.0             # seconds, first-order lag of the simulated value


@dataclass(frozen=True)
class Equipment:
    id: str
    name: str
    utility: str
    category: str                # compressor, boiler, chiller, pump, tower, ahu, tank, header, meter, skid
    zone: str
    criticality: str             # High | Medium | Low
    consumers: tuple[str, ...]
    sensors: tuple[SensorSpec, ...]
    standby: bool = False
    maintenance_interval_days: int = 90
    last_maintenance_days_ago: int = 40
    runtime_h: float = 0.0

    def tag(self, key: str) -> str:
        return f"{self.id}.{key}"


def S(key, label, unit, nominal, normal=None, warn=None, crit=None, noise=0.0, gain=0.0, cum=False, dec=2, tau=4.0):
    return SensorSpec(key, label, unit, nominal, normal, warn, crit, noise, gain, cum, dec, tau)


ZONES = [
    "Production Hall A", "Production Hall B", "Compressor Room", "Boiler Room", "Chiller Plant",
    "Cooling Tower Area", "HVAC Plant", "Water Plant", "Gas Station",
]
CONSUMERS_A = ("Assembly Line A", "Robot Cell A")
CONSUMERS_B = ("Test Line B", "Clean Room B")
ALL_LINES = CONSUMERS_A + CONSUMERS_B


def _compressor(i: int, standby: bool) -> Equipment:
    f = 0.25 if standby else 1.0
    return Equipment(
        f"CA-CMP-0{i}", f"Air Compressor {i}" + (" (standby)" if standby else ""), "COMPRESSED_AIR", "compressor",
        "Compressor Room", "High", ALL_LINES, (
            S("pressure_bar", "Discharge pressure", "bar", 7.0, (6.6, 7.4), (6.3, 7.7), (5.8, 8.2), 0.04, 0.01),
            S("flow_m3min", "Air flow", "m3/min", 8.0 * f, (5.0 * f, 10.5 * f), (3.5 * f, 12.0 * f), (2.0 * f, 14.0 * f), 0.15 * f, 0.6),
            S("power_kw", "Motor power", "kW", 55.0 * f, (35 * f, 70 * f), (25 * f, 78 * f), (15 * f, 90 * f), 0.8 * f, 0.5, dec=1),
            S("load_pct", "Load", "%", 68.0 * f, (40 * f, 88), (30 * f, 95), (15 * f, 100), 1.2, 0.5, dec=0),
            S("cycles_hr", "Load/unload cycles", "/h", 12.0, (4, 20), (2, 28), (0, 40), 0.8, dec=0),
            S("runtime_h", "Running hours", "h", 12480.0 if i == 1 else 9210.0, cum=True, dec=1),
        ), standby=standby, maintenance_interval_days=60, last_maintenance_days_ago=44 + i * 3)


def _boiler(i: int, standby: bool) -> Equipment:
    f = 0.3 if standby else 1.0
    return Equipment(
        f"ST-BLR-0{i}", f"Steam Boiler {i}" + (" (standby)" if standby else ""), "STEAM", "boiler", "Boiler Room", "High",
        ("Cleaning Line", "Lamination Press", "Process Heating"), (
            S("pressure_bar", "Steam pressure", "bar", 10.0, (9.3, 10.7), (8.8, 11.2), (8.0, 12.0), 0.05, 0.01),
            S("temp_c", "Steam temperature", "°C", 184.0, (178, 190), (172, 196), (165, 205), 0.4),
            S("flow_kghr", "Steam flow", "kg/h", 3500.0 * f, (1500 * f, 5200 * f), (800 * f, 5800 * f), (300 * f, 6500 * f), 40 * f, 0.7, dec=0),
            S("fuel_nm3hr", "Fuel gas", "Nm3/h", 260.0 * f, (110 * f, 380 * f), (60 * f, 430 * f), (20 * f, 520 * f), 4 * f, 0.7, dec=0),
            S("efficiency_pct", "Boiler efficiency", "%", 88.0, (84, 95), (80, 96), (70, 100), 0.3, dec=1),
            S("runtime_h", "Running hours", "h", 20310.0 + i * 700, cum=True, dec=1),
        ), standby=standby, maintenance_interval_days=90, last_maintenance_days_ago=70 - i * 20)


def _chiller(i: int) -> Equipment:
    return Equipment(
        f"CW-CHL-0{i}", f"Chiller {i}", "CHILLED_WATER", "chiller", "Chiller Plant", "High",
        ("HVAC Hall A", "HVAC Hall B", "Process Cooling"), (
            S("supply_c", "Supply temperature", "°C", 7.0, (6.0, 8.0), (5.0, 9.0), (4.0, 11.0), 0.07, 0.1),
            S("return_c", "Return temperature", "°C", 12.5, (11.0, 14.5), (10.0, 15.5), (8.5, 17.5), 0.1, 0.2),
            S("delta_t_c", "Delta T (return - supply)", "°C", 5.5, (4.5, 7.5), (3.5, 8.5), (2.0, 10.0), 0.12, dec=2),
            S("power_kw", "Chiller power", "kW", 180.0, (100, 240), (70, 270), (40, 310), 2.5, 0.6, dec=0),
            S("load_kw", "Cooling load", "kW", 650.0, (300, 900), (200, 1000), (100, 1150), 8, 0.8, dec=0),
            S("flow_m3hr", "Water flow", "m3/h", 95.0, (70, 120), (55, 135), (35, 150), 1.2, 0.2, dec=0),
            S("runtime_h", "Running hours", "h", 15210.0 + i * 900, cum=True, dec=1),
        ), maintenance_interval_days=120, last_maintenance_days_ago=33 + i * 12)


def _pump(eq_id, name, utility, zone, consumers, flow, dp, pw, interval=75, ago=51) -> Equipment:
    return Equipment(
        eq_id, name, utility, "pump", zone, "Medium", consumers, (
            S("flow_m3hr", "Flow", "m3/h", flow, (flow * 0.75, flow * 1.25), (flow * 0.6, flow * 1.4), (flow * 0.35, flow * 1.6), flow * 0.012, 0.2),
            S("dp_bar", "Differential pressure", "bar", dp, (dp * 0.8, dp * 1.2), (dp * 0.68, dp * 1.35), (dp * 0.5, dp * 1.6), dp * 0.012),
            S("power_kw", "Motor power", "kW", pw, (pw * 0.6, pw * 1.25), (pw * 0.45, pw * 1.4), (pw * 0.25, pw * 1.6), pw * 0.012, 0.6, dec=1),
            S("runtime_h", "Running hours", "h", 8100.0, cum=True, dec=1),
        ), maintenance_interval_days=interval, last_maintenance_days_ago=ago)


def _tower(i: int) -> Equipment:
    return Equipment(
        f"CT-TWR-0{i}", f"Cooling Tower {i}", "COOLING_TOWER", "tower", "Cooling Tower Area", "High",
        ("Chiller 1", "Chiller 2"), (
            S("inlet_c", "Water inlet temperature", "°C", 35.0, (32, 38), (30, 40), (28, 43), 0.12, 0.1),
            S("outlet_c", "Water outlet temperature", "°C", 29.5, (27, 31.5), (25, 33), (22, 36), 0.1, 0.05),
            S("fan_pct", "Fan speed", "%", 70.0, (35, 95), (20, 100), (0, 105), 1.0, 0.6, dec=0),
            S("fan_on", "Fan status (1 = running)", "", 1.0, (1, 1), (1, 1), (0, 1), 0.0, dec=0, tau=1),
            S("flow_m3hr", "Water flow", "m3/h", 220.0, (160, 260), (130, 290), (90, 330), 2.5, 0.2, dec=0),
            S("makeup_m3hr", "Make-up water", "m3/h", 2.4, (1.0, 4.2), (0.5, 6.0), (0.0, 9.0), 0.08, 0.3),
            S("runtime_h", "Running hours", "h", 7650.0 + i * 400, cum=True, dec=1),
        ), maintenance_interval_days=90, last_maintenance_days_ago=61 - i * 14)


def _ahu(i: int, zone: str) -> Equipment:
    return Equipment(
        f"HV-AHU-0{i}", f"Air Handling Unit {i}", "HVAC", "ahu", "HVAC Plant", "Medium",
        (f"{zone} climate",), (
            S("zone_temp_c", f"{zone} temperature", "°C", 23.0, (21.5, 24.5), (20.0, 26.0), (18.0, 29.0), 0.05, 0.04),
            S("humidity_pct", "Relative humidity", "%", 50.0, (40, 60), (30, 70), (20, 80), 0.4, dec=1),
            S("airflow_m3hr", "Airflow", "m3/h", 18000.0, (15000, 21000), (12000, 23500), (8000, 27000), 120, 0.2, dec=0),
            S("supply_c", "Supply air temperature", "°C", 14.0, (12, 16), (10, 18), (7, 21), 0.1),
            S("return_c", "Return air temperature", "°C", 24.0, (22, 26), (20, 28), (17, 31), 0.1),
            S("outdoor_c", "Outdoor temperature", "°C", 31.0, None, None, None, 0.1, dec=1),
            S("power_kw", "HVAC power", "kW", 22.0, (14, 30), (10, 34), (5, 40), 0.4, 0.5, dec=1),
            S("fan_on", "Fan status (1 = running)", "", 1.0, (1, 1), (1, 1), (0, 1), 0.0, dec=0, tau=1),
            S("runtime_h", "Running hours", "h", 11200.0 + i * 300, cum=True, dec=1),
        ), maintenance_interval_days=90, last_maintenance_days_ago=48 + i * 5)


def _tank(i: int, name: str, level: float) -> Equipment:
    return Equipment(
        f"WT-TNK-0{i}", name, "WATER", "tank", "Water Plant", "Medium", ("Process Water", "Cleaning Line"), (
            S("level_pct", "Tank level", "%", level, (35, 90), (25, 95), (12, 98), 0.15, dec=1, tau=8),
            S("outflow_m3hr", "Outflow", "m3/h", 14.0, (4, 22), (2, 27), (0, 34), 0.3, 0.8),
        ), maintenance_interval_days=180, last_maintenance_days_ago=90)


EQUIPMENT: tuple[Equipment, ...] = (
    _compressor(1, False), _compressor(2, True),
    Equipment("CA-RCV-01", "Air Receiver Tank", "COMPRESSED_AIR", "tank", "Compressor Room", "Medium", ALL_LINES, (
        S("pressure_bar", "Receiver pressure", "bar", 7.1, (6.7, 7.5), (6.4, 7.8), (5.9, 8.3), 0.04, 0.01),
    ), maintenance_interval_days=365, last_maintenance_days_ago=120),
    Equipment("CA-HDR-A", "Air Header - Hall A", "COMPRESSED_AIR", "header", "Production Hall A", "High", CONSUMERS_A, (
        S("pressure_bar", "Header pressure", "bar", 6.8, (6.4, 7.2), (6.1, 7.5), (5.6, 8.0), 0.04, 0.01),
        S("flow_m3min", "Air flow", "m3/min", 5.5, (3.0, 8.0), (2.0, 9.5), (1.0, 11.0), 0.12, 0.9),
    ), maintenance_interval_days=180, last_maintenance_days_ago=70),
    Equipment("CA-HDR-B", "Air Header - Hall B", "COMPRESSED_AIR", "header", "Production Hall B", "High", CONSUMERS_B, (
        S("pressure_bar", "Header pressure", "bar", 6.8, (6.4, 7.2), (6.1, 7.5), (5.6, 8.0), 0.04, 0.01),
        S("flow_m3min", "Air flow", "m3/min", 2.5, (1.0, 4.5), (0.5, 5.5), (0.0, 7.0), 0.08, 0.9),
    ), maintenance_interval_days=180, last_maintenance_days_ago=70),
    _boiler(1, False), _boiler(2, True),
    Equipment("ST-HDR-01", "Steam Header", "STEAM", "header", "Boiler Room", "High",
              ("Cleaning Line", "Lamination Press", "Process Heating"), (
        S("pressure_bar", "Header pressure", "bar", 9.8, (9.1, 10.5), (8.6, 11.0), (7.8, 11.8), 0.05, 0.01),
        S("temp_c", "Header temperature", "°C", 182.0, (176, 188), (170, 194), (163, 203), 0.4),
        S("flow_kghr", "Steam demand", "kg/h", 3400.0, (1400, 5100), (800, 5700), (300, 6400), 35, 0.9, dec=0),
    ), maintenance_interval_days=365, last_maintenance_days_ago=150),
    _chiller(1), _chiller(2),
    _pump("CW-PMP-01", "Chilled Water Pump 1", "CHILLED_WATER", "Chiller Plant", ("HVAC Hall A", "HVAC Hall B"), 95.0, 1.8, 18.5),
    _pump("CW-PMP-02", "Chilled Water Pump 2", "CHILLED_WATER", "Chiller Plant", ("HVAC Hall A", "HVAC Hall B"), 95.0, 1.8, 18.5, ago=64),
    _tower(1), _tower(2),
    _pump("CT-PMP-01", "Condenser Water Pump", "COOLING_TOWER", "Cooling Tower Area", ("Chiller 1", "Chiller 2"), 220.0, 2.4, 30.0),
    _ahu(1, "Hall A"), _ahu(2, "Hall B"),
    _tank(1, "Water Storage Tank", 72.0), _tank(2, "Process Water Tank", 64.0),
    _pump("WT-PMP-01", "Water Booster Pump", "WATER", "Water Plant", ("Process Water", "Cleaning Line"), 28.0, 4.2, 7.5),
    Equipment("WT-MTR-01", "Main Water Meter", "WATER", "meter", "Water Plant", "Medium", ("Process Water", "Cleaning Line"), (
        S("flow_m3hr", "Water flow", "m3/h", 24.0, (8, 38), (4, 45), (1, 55), 0.5, 0.9),
        S("consumed_m3", "Consumption (since start)", "m3", 0.0, cum=True, dec=1),
    ), maintenance_interval_days=365, last_maintenance_days_ago=200),
    Equipment("GS-SKD-01", "Gas Regulating Skid", "GAS", "skid", "Gas Station", "High", ("Steam Boiler 1", "Process Heating"), (
        S("pressure_bar", "Gas pressure", "bar", 4.0, (3.6, 4.4), (3.3, 4.7), (2.8, 5.2), 0.025, 0.01),
        S("flow_nm3hr", "Gas flow", "Nm3/h", 320.0, (120, 480), (60, 560), (10, 650), 5, 0.9, dec=0),
        S("temp_c", "Gas temperature", "°C", 24.0, (10, 38), (5, 44), (0, 52), 0.1, dec=1),
        S("lel_pct", "Combustible gas (% LEL)", "% LEL", 0.4, (0, 5), (0, 10), (0, 25), 0.05, dec=1, tau=2),
    ), maintenance_interval_days=90, last_maintenance_days_ago=36),
    Equipment("GS-MTR-01", "Gas Meter", "GAS", "meter", "Gas Station", "Medium", ("Steam Boiler 1", "Process Heating"), (
        S("flow_nm3hr", "Gas flow", "Nm3/h", 320.0, (120, 480), (60, 560), (10, 650), 5, 0.9, dec=0),
        S("consumed_nm3", "Consumption (since start)", "Nm3", 0.0, cum=True, dec=0),
    ), maintenance_interval_days=365, last_maintenance_days_ago=210),
)

BY_ID = {e.id: e for e in EQUIPMENT}
SPEC = {e.tag(s.key): (e, s) for e in EQUIPMENT for s in e.sensors}
TAGS = list(SPEC)

# Engineering limits can be overridden at run time (Configuration page). key = tag.
OVERRIDES: dict[str, dict] = {}


def bands(tag: str) -> tuple[Band | None, Band | None, Band | None]:
    e, s = SPEC[tag]
    o = OVERRIDES.get(tag, {})
    return (tuple(o["normal"]) if o.get("normal") else s.normal,
            tuple(o["warn"]) if o.get("warn") else s.warn,
            tuple(o["crit"]) if o.get("crit") else s.crit)


def _inside(v: float, band: Band | None) -> bool:
    if band is None:
        return True
    lo, hi = band
    return (lo is None or v >= lo) and (hi is None or v <= hi)


def level_of(tag: str, value: float) -> int:
    """0 NORMAL, 1 WARNING, 2 MAJOR, 3 CRITICAL for one reading."""
    e, s = SPEC[tag]
    if s.cumulative:
        return 0
    normal, warn, crit = bands(tag)
    if normal is None:
        return 0
    if _inside(value, normal):
        return 0
    if warn is None or _inside(value, warn):
        return 1
    if crit is None or _inside(value, crit):
        return 2
    return 3


def band_text(tag: str, which: str = "normal") -> str:
    """Human text of a limit band, e.g. '6.4 - 7.2 bar'."""
    e, s = SPEC[tag]
    normal, warn, crit = bands(tag)
    b = {"normal": normal, "warn": warn, "crit": crit}[which]
    if b is None:
        return "-"
    lo, hi = b
    u = f" {s.unit}" if s.unit else ""
    if lo is None:
        return f"<= {hi:g}{u}"
    if hi is None:
        return f">= {lo:g}{u}"
    return f"{lo:g} - {hi:g}{u}"


def catalog_json() -> dict:
    return {
        "utilities": [{"id": u, "label": UTILITY_LABEL[u]} for u in UTILITIES],
        "zones": ZONES,
        "equipment": [
            {"id": e.id, "name": e.name, "utility": e.utility, "category": e.category, "zone": e.zone,
             "criticality": e.criticality, "consumers": list(e.consumers), "standby": e.standby,
             "maintenance_interval_days": e.maintenance_interval_days,
             "sensors": [{"key": s.key, "tag": e.tag(s.key), "label": s.label, "unit": s.unit, "decimals": s.decimals,
                          "cumulative": s.cumulative, "nominal": s.nominal,
                          "normal": band_text(e.tag(s.key), "normal") if not s.cumulative else None,
                          "limits": {k: list(b) if b else None for k, b in zip(("normal", "warn", "crit"), bands(e.tag(s.key)))}
                          if not s.cumulative else None}
                         for s in e.sensors]}
            for e in EQUIPMENT],
    }
