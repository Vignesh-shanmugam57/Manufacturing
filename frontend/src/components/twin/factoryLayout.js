// Where everything stands in the 3D plant (metres). Equipment ids and tags come from the backend catalog;
// this file only decides placement, pipe routes and which sensor drives each pipe's flow animation.

export const UTIL_COLOR = {
  COMPRESSED_AIR: 0x60a5fa, STEAM: 0xe2e8f0, CHILLED_WATER: 0x22d3ee, COOLING_TOWER: 0xf59e0b,
  HVAC: 0x34d399, WATER: 0x3b82f6, GAS: 0xfacc15,
};

// equipment id -> [x, z, rotationY]
export const PLACE = {
  "CA-CMP-01": [8, -31], "CA-CMP-02": [15, -31], "CA-RCV-01": [22.5, -31],
  "CA-HDR-A": [-38, -13.5], "CA-HDR-B": [-16, -13.5],
  "ST-BLR-01": [33, -31], "ST-BLR-02": [41, -31], "ST-HDR-01": [37, -21],
  "CW-CHL-01": [54, -31], "CW-CHL-02": [62, -31], "CW-PMP-01": [54, -22], "CW-PMP-02": [62, -22],
  "CT-TWR-01": [56, -7], "CT-TWR-02": [64, -7], "CT-PMP-01": [60, -15],
  "HV-AHU-01": [-42, 35], "HV-AHU-02": [-16, 35],
  "WT-TNK-01": [18, 22], "WT-TNK-02": [28, 22], "WT-PMP-01": [23, 32], "WT-MTR-01": [23, 27],
  "GS-SKD-01": [63, 22], "GS-MTR-01": [55, 22],
};

// Pipe routes. flow: the tag whose value (against its nominal) sets the particle speed. equip: equipment whose
// status colours the pipe. leak: where a suspected leak puff is drawn while a leak alert is open on that equipment.
export const PIPES = [
  { id: "air-cmp1", utility: "COMPRESSED_AIR", r: 0.16, pts: [[8, 2.4, -31], [8, 6, -31], [21, 6, -31]], flow: "CA-CMP-01.flow_m3min", equip: ["CA-CMP-01"] },
  { id: "air-cmp2", utility: "COMPRESSED_AIR", r: 0.14, pts: [[15, 2.4, -31], [15, 6, -31]], flow: "CA-CMP-02.flow_m3min", equip: ["CA-CMP-02"] },
  { id: "air-trunk-a", utility: "COMPRESSED_AIR", r: 0.2, pts: [[22.5, 4.8, -31], [22.5, 7, -31], [22.5, 7, -13.5], [-38, 7, -13.5], [-38, 3.2, -13.5]],
    flow: "CA-HDR-A.flow_m3min", equip: ["CA-RCV-01", "CA-HDR-A"], leak: [-30, 7, -13.5], leakFor: ["CA-HDR-A"] },
  { id: "air-branch-b", utility: "COMPRESSED_AIR", r: 0.16, pts: [[-16, 7, -13.5], [-16, 3.2, -13.5]], flow: "CA-HDR-B.flow_m3min", equip: ["CA-HDR-B"], leak: [-16, 5, -13.5], leakFor: ["CA-HDR-B"] },
  { id: "steam-b1", utility: "STEAM", r: 0.17, pts: [[33, 4.6, -31], [33, 7.2, -31], [37, 7.2, -31], [37, 7.2, -21], [37, 3.4, -21]], flow: "ST-BLR-01.flow_kghr", equip: ["ST-BLR-01"] },
  { id: "steam-b2", utility: "STEAM", r: 0.14, pts: [[41, 4.6, -31], [41, 7.2, -31], [37, 7.2, -31]], flow: "ST-BLR-02.flow_kghr", equip: ["ST-BLR-02"] },
  { id: "steam-dist", utility: "STEAM", r: 0.2, pts: [[37, 3.4, -21], [37, 6, -21], [37, 6, -17.5], [-24, 6, -17.5], [-24, 6, -9]], flow: "ST-HDR-01.flow_kghr", equip: ["ST-HDR-01", "ST-BLR-01"] },
  { id: "chw-main", utility: "CHILLED_WATER", r: 0.22, pts: [[54, 1.6, -26], [54, 1.6, -22], [58, 1.2, -19], [67, 1.2, -19], [67, 1.2, 40], [-16, 1.2, 40], [-16, 1.2, 36]], flow: "CW-PMP-01.flow_m3hr", equip: ["CW-CHL-01", "CW-PMP-01", "CW-CHL-02", "CW-PMP-02"] },
  { id: "chw-ahu1", utility: "CHILLED_WATER", r: 0.17, pts: [[-16, 1.2, 40], [-42, 1.2, 40], [-42, 1.2, 36]], flow: "CW-PMP-01.flow_m3hr", equip: ["CW-PMP-01", "CW-CHL-01"] },
  { id: "ct-loop-1", utility: "COOLING_TOWER", r: 0.2, pts: [[56, 1.5, -10], [56, 1.5, -15], [60, 1.5, -15], [60, 1.5, -26], [54, 3.6, -26]], flow: "CT-PMP-01.flow_m3hr", equip: ["CT-TWR-01", "CT-PMP-01"] },
  { id: "ct-loop-2", utility: "COOLING_TOWER", r: 0.2, pts: [[64, 1.5, -10], [64, 1.5, -15], [60, 1.5, -15], [62, 3.6, -26]], flow: "CT-TWR-02.flow_m3hr", equip: ["CT-TWR-02", "CT-PMP-01"] },
  { id: "hvac-1", utility: "HVAC", r: 0.55, pts: [[-42, 5.2, 33], [-42, 5.2, 29]], flow: "HV-AHU-01.airflow_m3hr", equip: ["HV-AHU-01"] },
  { id: "hvac-2", utility: "HVAC", r: 0.55, pts: [[-16, 5.2, 33], [-16, 5.2, 29]], flow: "HV-AHU-02.airflow_m3hr", equip: ["HV-AHU-02"] },
  { id: "water-in", utility: "WATER", r: 0.18, pts: [[18, 0.9, 24.5], [18, 0.9, 30], [22, 0.9, 32]], flow: "WT-MTR-01.flow_m3hr", equip: ["WT-TNK-01"] },
  { id: "water-dist", utility: "WATER", r: 0.2, pts: [[23, 1.4, 32], [23, 1.4, 38], [-5, 1.4, 38], [-5, 1.4, 30], [-5, 1.8, 26]], flow: "WT-MTR-01.flow_m3hr", equip: ["WT-PMP-01", "WT-MTR-01", "WT-TNK-01"],
    leak: [10, 1.4, 38], leakFor: ["WT-TNK-01", "WT-MTR-01", "WT-PMP-01"] },
  { id: "gas-main", utility: "GAS", r: 0.17, pts: [[63, 1.3, 22], [55, 1.3, 22], [47, 1.3, 22], [47, 1.3, -19.5], [38, 1.3, -19.5], [34, 1.3, -26], [33, 1.3, -28]], flow: "GS-SKD-01.flow_nm3hr", equip: ["GS-SKD-01", "GS-MTR-01"],
    leak: [47, 1.3, 2], leakFor: ["GS-SKD-01"] },
];

// Production consumers inside the main hall [x, z, w, d]
export const CONSUMERS = {
  "Assembly Line A": [-44, 0, 11, 4], "Robot Cell A": [-44, 14, 9, 6],
  "Test Line B": [-23, 0, 11, 4], "Clean Room B": [-23, 14, 11, 8],
  "Cleaning Line": [-33, 7, 6, 3], "Lamination Press": [-12, 6, 5, 4], "Process Heating": [-12, 16, 5, 4],
};

export const HALL = { x0: -52, x1: -4, z0: -11, z1: 29, h: 12 };
export const BUILDINGS = [
  { name: "Compressor room", x0: 2, x1: 28, z0: -38, z1: -25, h: 8.5 },
  { name: "Boiler room", x0: 29, x1: 47, z0: -38, z1: -25, h: 10 },
  { name: "Chiller plant", x0: 49, x1: 67, z0: -38, z1: -25, h: 8.5 },
];

export const CAMERA_HOME = { pos: [62, 88, 108], target: [8, 0, -2] };

/** Camera position that keeps the whole plant in view: pull back when the stage is narrow. */
export function homeFor(aspect) {
  const k = aspect < 1.25 ? Math.pow(1.25 / Math.max(aspect, 0.5), 0.55) : 1;
  const [tx, ty, tz] = CAMERA_HOME.target;
  const [px, py, pz] = CAMERA_HOME.pos;
  return { pos: [tx + (px - tx) * k, ty + (py - ty) * k, tz + (pz - tz) * k], target: CAMERA_HOME.target };
}
