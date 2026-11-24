export const UTILITY_LABEL = {
  COMPRESSED_AIR: "Compressed air", STEAM: "Steam", CHILLED_WATER: "Chilled water", COOLING_TOWER: "Cooling tower",
  HVAC: "HVAC", WATER: "Water", GAS: "Gas",
};
export const UTILITIES = Object.keys(UTILITY_LABEL);
export const UTILITY_COLOR = {
  COMPRESSED_AIR: "#60a5fa", STEAM: "#cbd5e1", CHILLED_WATER: "#22d3ee", COOLING_TOWER: "#f59e0b",
  HVAC: "#34d399", WATER: "#3b82f6", GAS: "#facc15",
};
// The tags that tell the story of each utility (used for the utility pages and quick summaries).
export const KEY_TAGS = {
  COMPRESSED_AIR: ["CA-HDR-A.pressure_bar", "CA-HDR-A.flow_m3min", "CA-CMP-01.power_kw", "CA-CMP-01.load_pct"],
  STEAM: ["ST-HDR-01.pressure_bar", "ST-HDR-01.temp_c", "ST-HDR-01.flow_kghr", "ST-BLR-01.efficiency_pct"],
  CHILLED_WATER: ["CW-CHL-01.supply_c", "CW-CHL-01.return_c", "CW-CHL-01.delta_t_c", "CW-CHL-01.power_kw"],
  COOLING_TOWER: ["CT-TWR-01.inlet_c", "CT-TWR-01.outlet_c", "CT-TWR-01.fan_pct", "CT-TWR-01.flow_m3hr"],
  HVAC: ["HV-AHU-01.zone_temp_c", "HV-AHU-02.zone_temp_c", "HV-AHU-01.airflow_m3hr", "HV-AHU-02.airflow_m3hr"],
  WATER: ["WT-TNK-01.level_pct", "WT-MTR-01.flow_m3hr", "WT-PMP-01.pressure_bar", "WT-PMP-01.dp_bar"],
  GAS: ["GS-SKD-01.pressure_bar", "GS-SKD-01.flow_nm3hr", "GS-SKD-01.lel_pct", "GS-SKD-01.temp_c"],
};
export const UTILITY_DETECTS = {
  COMPRESSED_AIR: "Leakage, abnormal baseload, pressure instability, excessive compressor runtime, inefficient operation",
  STEAM: "Abnormal consumption, pressure instability, temperature deviation, steam leakage, boiler efficiency",
  CHILLED_WATER: "Low Delta T, abnormal consumption, pump inefficiency, cooling performance",
  COOLING_TOWER: "Fan failure, abnormal cooling performance, high water consumption, temperature deviation",
  HVAC: "Abnormal temperature, excessive energy, airflow imbalance, equipment inefficiency",
  WATER: "Leakage, abnormal consumption, tank overflow risk, pump inefficiency",
  GAS: "Abnormal consumption, pressure instability, unexpected usage, safety alarms (always high priority)",
};

export function formatWhen(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function timeAgoShort(iso) {
  if (!iso) return "";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export const STATUS_STEPS = ["OPEN", "ACKNOWLEDGED", "ASSIGNED", "INVESTIGATING", "CORRECTIVE_ACTION", "VERIFIED"];
export const STATUS_LABEL = {
  OPEN: "Open", ACKNOWLEDGED: "Acknowledged", ASSIGNED: "Assigned", INVESTIGATING: "Investigating",
  CORRECTIVE_ACTION: "Corrective action", VERIFIED: "Verified & closed",
};
