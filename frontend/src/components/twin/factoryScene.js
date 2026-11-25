import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { LEVELS, LEVEL_COLOR } from "../../lib/twin.js";
import { BUILDINGS, CONSUMERS, HALL, PIPES, PLACE, UTIL_COLOR, homeFor, walkRoute } from "./factoryLayout.js";

const hex = (s) => parseInt(s.slice(1), 16);
const LV = LEVEL_COLOR.map(hex);                          // normal, warning, major, critical, offline
const std = (color, o = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.5, metalness: 0.5, ...o });
const glass = (color, opacity) => new THREE.MeshStandardMaterial({ color, roughness: 0.15, metalness: 0.1, transparent: true, opacity, depthWrite: false, side: THREE.DoubleSide });
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

function shadow(m) { m.castShadow = true; m.receiveShadow = true; return m; }
function box(g, w, h, d, mat, x = 0, y = 0, z = 0) {
  const m = shadow(new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat));
  m.position.set(x, y, z); g.add(m); return m;
}
function cyl(g, rt, rb, h, mat, x = 0, y = 0, z = 0, axis = "y", seg = 28) {
  const m = shadow(new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), mat));
  m.position.set(x, y, z);
  if (axis === "x") m.rotation.z = Math.PI / 2;
  if (axis === "z") m.rotation.x = Math.PI / 2;
  g.add(m); return m;
}
function sph(g, r, mat, x, y, z, sx = 1, sy = 1, sz = 1, half = false) {
  const geo = half ? new THREE.SphereGeometry(r, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2) : new THREE.SphereGeometry(r, 24, 16);
  const m = shadow(new THREE.Mesh(geo, mat));
  m.position.set(x, y, z); m.scale.set(sx, sy, sz); g.add(m); return m;
}
function blades(g, n, len, w, mat) {
  const grp = new THREE.Group();
  for (let i = 0; i < n; i += 1) {
    const holder = new THREE.Group();
    holder.rotation.y = (i / n) * Math.PI * 2;
    box(holder, len, 0.08, w, mat, len / 2, 0, 0);
    grp.add(holder);
  }
  g.add(grp);
  return grp;
}

function dotTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const x = c.getContext("2d");
  const g = x.createRadialGradient(32, 32, 2, 32, 32, 30);
  g.addColorStop(0, "rgba(255,255,255,1)"); g.addColorStop(1, "rgba(255,255,255,0)");
  x.fillStyle = g; x.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
}

// the surroundings in each app theme; equipment, pipes and status colours are the same in both
const PALETTE = {
  light: { bg: 0xe8eef7, ground: 0xdbe3ef, grid1: 0xaab8cf, grid2: 0xc3cede, pad: 0xc3cede, wall: 0xa3b2ca, roof: 0x64748b, hall: 0x4f78b8, hallOp: 0.16, roofOp: 0.1, steel: 0x8292aa,
    base: 0x93a4c1, accent: 0xb3c0d6, sky: 0xffffff, under: 0xc2cde0, hemi: 1.15, sun: 1.15, fill: 0.15, exposure: 1.0, signBg: "rgba(255,255,255,.92)", signText: "#0f172a", puff: 0x64748b },
  dark: { bg: 0x0a1122, ground: 0x172033, grid1: 0x2a3a5e, grid2: 0x1c2a47, pad: 0x253150, wall: 0x334155, roof: 0x94a3b8, hall: 0x9db8e6, hallOp: 0.13, roofOp: 0.08, steel: 0x64748b,
    base: 0x3b4a66, accent: 0x64748b, sky: 0x9bb7ff, under: 0x0f172a, hemi: 0.95, sun: 1.35, fill: 0.6, exposure: 1.05, signBg: "rgba(11,18,38,.72)", signText: "#dbe7ff", puff: 0xe0f2fe },
};
const themeName = () => (document.documentElement.dataset.theme === "dark" ? "dark" : "light");

function drawSign(c, text, p) {
  const x = c.getContext("2d");
  x.clearRect(0, 0, c.width, c.height);
  x.font = "600 44px Inter, Segoe UI, sans-serif";
  x.textAlign = "center"; x.textBaseline = "middle";
  x.fillStyle = p.signBg; x.fillRect(0, 8, 512, 80);
  x.fillStyle = p.signText; x.fillText(text, 256, 50);
}

function makeLabel(text, scale = 1) {
  const c = document.createElement("canvas");
  c.width = 512; c.height = 96;
  drawSign(c, text, PALETTE[themeName()]);
  const tex = new THREE.CanvasTexture(c);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
  s.scale.set(11 * scale, 2.06 * scale, 1);
  s.userData.sign = { canvas: c, text };
  return s;
}

// ------------------------------------------------------------------------------------------- equipment models
// Each builder fills group g and returns { h: beacon height, r: ring radius, tint: [materials], update({v, nom, t, dt}) }.
const BUILD = {
  compressor(g) {
    const body = std(0x2f6fb3), dark = std(0x2b3342), green = std(0x24805f);
    box(g, 8, 0.4, 3, dark, 0, 0.2, 0);
    cyl(g, 1, 1, 3.8, body, 0.8, 1.7, 0, "x");
    cyl(g, 0.82, 0.82, 2, green, -2.8, 1.5, 0, "x");
    box(g, 1.3, 1.2, 1.3, dark, 3, 1.0, -0.6);
    cyl(g, 0.22, 0.22, 1.4, std(0x9ca3af), 1.4, 3.2, 0);
    const fly = new THREE.Group(); fly.position.set(2.8, 1.7, 1.28);
    cyl(fly, 0.9, 0.9, 0.16, std(0xd1d5db), 0, 0, 0, "z");
    box(fly, 1.7, 0.12, 0.12, dark, 0, 0, 0.12); box(fly, 0.12, 1.7, 0.12, dark, 0, 0, 0.12);
    g.add(fly);
    return { h: 4, r: 4.8, tint: [body], update: ({ v, dt }) => { fly.rotation.z -= dt * clamp(v("load_pct") / 100, 0, 1.1) * 9 * (v("flow_m3min") > 0.2 ? 1 : 0); } };
  },
  tank(g, e) {
    if (e.utility === "WATER") {
      const shell = glass(0x9fb4c9, 0.22), liquid = std(0x2f80ed, { transparent: true, opacity: 0.8, metalness: 0.1, roughness: 0.2 });
      cyl(g, 2.2, 2.2, 5, shell, 0, 2.6, 0);
      sph(g, 2.2, shell, 0, 5.1, 0, 1, 0.35, 1, true);
      const water = shadow(new THREE.Mesh(new THREE.CylinderGeometry(2.1, 2.1, 1, 28), liquid)); g.add(water);
      cyl(g, 0.12, 0.12, 5.4, std(0x6b7280), 2.5, 2.7, 0);
      box(g, 5.2, 0.3, 5.2, std(0x374151), 0, 0.15, 0);
      return { h: 6.6, r: 3.6, tint: [shell, liquid], update: ({ v }) => { const h = Math.max(0.05, 4.8 * clamp(v("level_pct") / 100, 0, 1)); water.scale.y = h; water.position.y = 0.3 + h / 2; } };
    }
    const m = std(0x607d8b);                                          // compressed air receiver
    cyl(g, 1.35, 1.35, 4.2, m, 0, 2.6, 0);
    sph(g, 1.35, m, 0, 4.7, 0, 1, 0.7, 1, true);
    for (let i = 0; i < 3; i += 1) { const a = (i / 3) * Math.PI * 2; box(g, 0.25, 0.7, 0.25, std(0x374151), Math.cos(a) * 1.1, 0.35, Math.sin(a) * 1.1); }
    cyl(g, 0.4, 0.4, 0.14, std(0xf3f4f6), 0, 3.4, 1.4, "z");
    return { h: 6.3, r: 2.6, tint: [m], update() {} };
  },
  header(g, e) {
    const cab = std(0x374151), pipe = std(UTIL_COLOR[e.utility]);
    box(g, 1.8, 2.2, 1.2, cab, 0, 1.1, 0);
    cyl(g, 0.22, 0.22, 3, pipe, 0, 3.2, 0.2);
    const dial = cyl(g, 0.5, 0.5, 0.12, std(0xf9fafb), 0, 1.6, 0.66, "z");
    const needle = new THREE.Group(); needle.position.set(0, 1.6, 0.76);
    box(needle, 0.06, 0.42, 0.04, std(0xdc2626), 0, 0.18, 0); g.add(needle);
    return { h: 4.4, r: 2.4, tint: [cab, dial.material], update: ({ v }) => { needle.rotation.z = -(clamp((v("pressure_bar") - 5) / 3, 0, 1) - 0.5) * Math.PI * 1.5; } };
  },
  meter(g) {
    const m = std(0x374151);
    box(g, 1.5, 1.6, 1, m, 0, 0.8, 0);
    cyl(g, 0.45, 0.45, 0.1, std(0xf9fafb), 0, 1.1, 0.55, "z");
    return { h: 2.8, r: 1.8, tint: [m], update() {} };
  },
  boiler(g) {
    const shell = std(0xb45309), dark = std(0x4b5563);
    box(g, 8, 0.4, 3.4, dark, 0, 0.2, 0);
    cyl(g, 1.9, 1.9, 6.4, shell, 0, 2.7, 0, "x");
    sph(g, 1.9, shell, 3.2, 2.7, 0, 0.45, 1, 1);
    sph(g, 1.9, shell, -3.2, 2.7, 0, 0.45, 1, 1);
    cyl(g, 0.5, 0.62, 7.5, std(0x6b7280), -1.6, 7, 0);
    box(g, 1.6, 1.8, 1.8, dark, 4.3, 1.4, 0);
    const puff = new THREE.MeshBasicMaterial({ color: 0xf1f5f9, transparent: true, opacity: 0.5, depthWrite: false });
    const wisps = Array.from({ length: 7 }, () => { const s = new THREE.Mesh(new THREE.SphereGeometry(0.6, 10, 8), puff.clone()); g.add(s); return s; });
    return {
      h: 11.4, r: 5, tint: [shell],
      update: ({ v, nom, t }) => {
        const flow = clamp(v("flow_kghr") / (nom("flow_kghr") || 1), 0, 2);
        wisps.forEach((w, i) => { const s = (t * 0.35 + i / wisps.length) % 1; w.position.set(-1.6 + Math.sin(s * 6 + i) * 0.5, 11 + s * 5, 0); w.scale.setScalar(0.5 + s * 1.5); w.material.opacity = 0.55 * (1 - s) * Math.min(1, flow); });
      },
    };
  },
  chiller(g) {
    const body = std(0x0e7490), steel = std(0x9ca3af), dark = std(0x1f2937);
    box(g, 8, 0.4, 3.4, dark, 0, 0.2, 0);
    box(g, 7, 2.7, 2.6, body, 0, 1.75, 0);
    cyl(g, 0.7, 0.7, 5.6, steel, 0, 3.55, 0.7, "x");
    cyl(g, 0.7, 0.7, 5.6, steel, 0, 3.55, -0.7, "x");
    box(g, 1.4, 1.6, 0.3, dark, -2.2, 1.7, 1.45);
    const lamp = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.2, 0.1), new THREE.MeshBasicMaterial({ color: 0x22c55e })); lamp.position.set(-2.2, 2.3, 1.62); g.add(lamp);
    return { h: 5.2, r: 5.2, tint: [body], update: ({ v, nom, t }) => { lamp.visible = v("power_kw") > 5 && Math.sin(t * 3) > -0.6; } };
  },
  pump(g, e) {
    const motor = std(0x1e40af), steel = std(0x9ca3af), dark = std(0x1f2937);
    box(g, 4, 0.3, 1.8, dark, 0, 0.15, 0);
    cyl(g, 0.55, 0.55, 1.8, motor, -1.1, 0.95, 0, "x");
    cyl(g, 0.8, 0.8, 1, steel, 1.1, 0.95, 0, "x");
    cyl(g, 0.22, 0.22, 1.6, std(UTIL_COLOR[e.utility]), 1.1, 1.9, 0);
    const cpl = new THREE.Group(); cpl.position.set(0, 0.95, 0.35);
    cyl(cpl, 0.34, 0.34, 0.1, std(0xe5e7eb), 0, 0, 0, "z"); box(cpl, 0.6, 0.08, 0.06, dark, 0, 0, 0.08);
    g.add(cpl);
    return { h: 3.6, r: 2.8, tint: [motor], update: ({ v, nom, dt }) => { cpl.rotation.z -= dt * clamp(v("flow_m3hr") / (nom("flow_m3hr") || 1), 0, 2) * 11; } };
  },
  tower(g) {
    const body = glass(0x7aa6c2, 0.55), conc = std(0x6b7280), steel = std(0x9ca3af), drop = new THREE.MeshBasicMaterial({ color: 0x7dd3fc, transparent: true, opacity: 0.8 });
    box(g, 6.4, 0.9, 6.4, conc, 0, 0.45, 0);
    cyl(g, 2.8, 3.3, 5.6, body, 0, 3.7, 0);
    const ring = new THREE.Mesh(new THREE.TorusGeometry(2.5, 0.16, 10, 36), steel); ring.rotation.x = Math.PI / 2; ring.position.y = 6.7; g.add(ring);
    const fan = blades(g, 4, 2.3, 0.7, std(0x374151)); fan.position.y = 6.6;
    cyl(g, 0.35, 0.35, 0.5, std(0x111827), 0, 6.6, 0);
    const N = 26, drops = new THREE.InstancedMesh(new THREE.SphereGeometry(0.1, 6, 5), drop, N); g.add(drops);
    const seeds = Array.from({ length: N }, () => [Math.random() * Math.PI * 2, Math.random() * 2.1, Math.random()]);
    const m4 = new THREE.Matrix4();
    return {
      h: 8.4, r: 4.6, tint: [conc],
      update: ({ v, nom, t, dt }) => {
        const on = v("fan_on") > 0.5 ? 1 : 0, spd = clamp(v("fan_pct") / 100, 0, 1.1) * on;
        fan.rotation.y += dt * spd * 7;
        const flow = clamp(v("flow_m3hr") / (nom("flow_m3hr") || 1), 0, 1.6);
        seeds.forEach((s, i) => { const k = (t * 0.5 * flow + s[2]) % 1; m4.makeTranslation(Math.cos(s[0]) * s[1], 6 - k * 5, Math.sin(s[0]) * s[1]); drops.setMatrixAt(i, m4); });
        drops.instanceMatrix.needsUpdate = true;
      },
    };
  },
  ahu(g) {
    const body = std(0xcbd5e1, { metalness: 0.3 }), dark = std(0x475569);
    box(g, 6.4, 3, 2.6, body, 0, 1.7, 0);
    box(g, 6.6, 0.25, 2.8, dark, 0, 3.3, 0);
    const fans = [-1.6, 1.6].map((x) => {
      const f = blades(g, 5, 0.8, 0.35, std(0x1f2937)); f.rotation.x = Math.PI / 2; f.position.set(x, 1.8, 1.34);
      cyl(g, 0.9, 0.9, 0.1, glass(0x94a3b8, 0.35), x, 1.8, 1.3, "z"); return f;
    });
    box(g, 1.4, 1.4, 1.4, dark, 0, 4.2, 0);
    return { h: 5.6, r: 4.6, tint: [body], update: ({ v, nom, dt }) => { const s = clamp(v("airflow_m3hr") / (nom("airflow_m3hr") || 1), 0, 1.6) * (v("fan_on") > 0.5 ? 1 : 0); fans.forEach((f) => { f.rotation.y -= dt * s * 9; }); } };
  },
  skid(g) {
    const tank = std(0xd9a406), dark = std(0x374151), steel = std(0x9ca3af);
    box(g, 7, 0.3, 4, dark, 0, 0.15, 0);
    for (const z of [-1.1, 1.1]) { cyl(g, 0.85, 0.85, 4.2, tank, 0, 1.4, z, "x"); sph(g, 0.85, tank, 2.1, 1.4, z); sph(g, 0.85, tank, -2.1, 1.4, z); }
    box(g, 1.8, 1.6, 1.4, steel, 3.4, 1, 0);
    box(g, 0.5, 2.4, 0.5, dark, -3.2, 1.5, 1.6);
    return { h: 3.6, r: 5, tint: [tank], update() {} };
  },
};

// ------------------------------------------------------------------------------------------- the scene
export function createFactory(container, { catalog, getState, onSelect, onHover, onLabelsClosed }) {
  const W = () => container.clientWidth || 800, H = () => container.clientHeight || 500;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
  renderer.setSize(W(), H());
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  container.appendChild(renderer.domElement);
  renderer.domElement.className = "f-canvas";

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a1122);
  scene.fog = new THREE.Fog(0x0a1122, 150, 360);
  const camera = new THREE.PerspectiveCamera(42, W() / H(), 0.5, 600);
  const home0 = homeFor(W() / H());
  camera.position.set(...home0.pos);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(...home0.target);
  controls.enableDamping = true; controls.dampingFactor = 0.08;
  controls.maxPolarAngle = Math.PI * 0.47; controls.minDistance = 14; controls.maxDistance = 190;
  controls.screenSpacePanning = false;
  controls.update();

  scene.add(new THREE.HemisphereLight(0x9bb7ff, 0x0f172a, 0.95));
  const sun = new THREE.DirectionalLight(0xfff2dd, 1.35);
  sun.position.set(50, 90, 40); sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -95, right: 95, top: 80, bottom: -80, near: 10, far: 260 });
  sun.shadow.bias = -0.0004;
  scene.add(sun);
  const fill = new THREE.PointLight(0x4f8cff, 0.6, 160); fill.position.set(-30, 30, 40); scene.add(fill);

  const disposables = [];
  const keep = (o) => { disposables.push(o); return o; };

  // ground, pads and the production hall
  const ground = new THREE.Mesh(keep(new THREE.PlaneGeometry(190, 140)), std(0x172033, { roughness: 0.95, metalness: 0.05 }));
  ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true; scene.add(ground);
  const grid = new THREE.GridHelper(190, 38, 0x2a3a5e, 0x1c2a47); grid.position.y = 0.03; scene.add(grid);
  const padMat = std(0x253150, { roughness: 0.9, metalness: 0.1 });
  const themed = [];                                       // [material, palette key]
  const tone = (mat, key) => { themed.push([mat, key]); return mat; };
  tone(ground.material, "ground"); tone(padMat, "pad");
  const pad = (x0, x1, z0, z1) => { const m = box(scene, x1 - x0, 0.25, z1 - z0, padMat, (x0 + x1) / 2, 0.12, (z0 + z1) / 2); m.castShadow = false; };
  pad(HALL.x0 - 1, HALL.x1 + 1, HALL.z0 - 1, HALL.z1 + 1);
  BUILDINGS.forEach((b) => pad(b.x0, b.x1, b.z0, b.z1));
  pad(11, 34, 17, 36); pad(49, 70, 15, 29); pad(50, 70, -13, -2);

  const hallGlass = tone(glass(0x9db8e6, 0.13), "hall"), steelMat = tone(std(0x64748b), "steel");
  const cx = (HALL.x0 + HALL.x1) / 2, cz = (HALL.z0 + HALL.z1) / 2, hw = HALL.x1 - HALL.x0, hd = HALL.z1 - HALL.z0;
  box(scene, hw, HALL.h, 0.3, hallGlass, cx, HALL.h / 2, HALL.z0).castShadow = false;
  box(scene, hw, HALL.h, 0.3, hallGlass, cx, HALL.h / 2, HALL.z1).castShadow = false;
  box(scene, 0.3, HALL.h, hd, hallGlass, HALL.x0, HALL.h / 2, cz).castShadow = false;
  box(scene, 0.3, HALL.h, hd, hallGlass, HALL.x1, HALL.h / 2, cz).castShadow = false;
  const hallRoof = tone(glass(0x9db8e6, 0.08), "hall");
  box(scene, hw, 0.25, hd, hallRoof, cx, HALL.h, cz).castShadow = false;
  for (let x = HALL.x0; x <= HALL.x1 + 0.1; x += 12) for (const z of [HALL.z0, HALL.z1]) box(scene, 0.55, HALL.h, 0.55, steelMat, x, HALL.h / 2, z);
  const hallLabel = makeLabel("Production Hall A + B", 1.1); hallLabel.position.set(cx, HALL.h + 3, cz); scene.add(hallLabel);

  BUILDINGS.forEach((b) => {
    const w = b.x1 - b.x0, d = b.z1 - b.z0, mid = (b.x0 + b.x1) / 2, wall = tone(std(0x334155, { roughness: 0.8 }), "wall");
    box(scene, w, b.h, 0.4, wall, mid, b.h / 2, b.z0);
    box(scene, 0.4, b.h, d, wall, b.x0, b.h / 2, (b.z0 + b.z1) / 2);
    box(scene, 0.4, b.h, d, wall, b.x1, b.h / 2, (b.z0 + b.z1) / 2);
    box(scene, w, 0.3, d, tone(glass(0x94a3b8, 0.12), "roof"), mid, b.h, (b.z0 + b.z1) / 2).castShadow = false;
    const l = makeLabel(b.name); l.position.set(mid, b.h + 3.2, (b.z0 + b.z1) / 2); scene.add(l);
  });
  [["Cooling tower area", 60, 8, -2], ["HVAC plant", -29, 6.5, 41], ["Water plant", 23, 8, 27], ["Gas station", 59, 6, 29]].forEach(([n, x, y, z]) => { const l = makeLabel(n); l.position.set(x, y + 3, z); scene.add(l); });

  // production consumers
  const consumers = {};
  Object.entries(CONSUMERS).forEach(([name, [x, z, w, d]]) => {
    const g = new THREE.Group(); g.position.set(x + w / 2, 0.3, z + d / 2);
    const base = tone(std(0x3b4a66), "base"), accent = tone(std(0x64748b), "accent");
    const clean = name === "Clean Room B";
    if (clean) box(g, w, 3.6, d, glass(0xbfdbfe, 0.2), 0, 1.8, 0);
    box(g, w, 0.7, d * (clean ? 0.5 : 0.7), base, 0, 0.35, 0);
    for (let i = 0; i < Math.max(2, Math.floor(w / 3)); i += 1) box(g, 1.6, 1.5 + (i % 2) * 0.8, 1.5, accent, -w / 2 + 1.6 + i * 3, 1.2, 0);
    if (name.startsWith("Robot")) { box(g, 0.5, 2.6, 0.5, std(0xf97316), 0, 1.6, 1.2); box(g, 2.2, 0.4, 0.4, std(0xf97316), 0.9, 2.9, 1.2); }
    scene.add(g);
    const mats = []; g.traverse((o) => { if (o.isMesh && !mats.includes(o.material)) mats.push(o.material); });
    consumers[name] = { group: g, mats: mats.filter((m) => m.emissive) };
  });

  // equipment
  const items = {};
  const pickables = [];
  catalog.equipment.forEach((e) => {
    const place = PLACE[e.id];
    const build = BUILD[e.category];
    if (!place || !build) return;
    const g = new THREE.Group();
    g.position.set(place[0], 0.25, place[1]);
    g.userData = { equipId: e.id, utility: e.utility };
    const spec = build(g, e);
    const beacon = new THREE.Mesh(new THREE.SphereGeometry(0.5, 16, 12), new THREE.MeshBasicMaterial({ color: LV[0] }));
    beacon.position.y = spec.h + 1.1; g.add(beacon);
    const ring = new THREE.Mesh(new THREE.RingGeometry(spec.r * 0.9, spec.r, 56), new THREE.MeshBasicMaterial({ color: LV[0], transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }));
    ring.rotation.x = -Math.PI / 2; ring.position.y = 0.08; g.add(ring);
    const sel = new THREE.Mesh(new THREE.RingGeometry(spec.r * 1.02, spec.r * 1.14, 56), new THREE.MeshBasicMaterial({ color: 0x60a5fa, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }));
    sel.rotation.x = -Math.PI / 2; sel.position.y = 0.09; g.add(sel);
    scene.add(g);
    const mats = [];
    g.traverse((o) => { if (o.isMesh && o.material !== beacon.material && o.material !== ring.material && o.material !== sel.material && !mats.includes(o.material)) mats.push(o.material); });
    mats.forEach((m) => { m.userData.baseOpacity = m.opacity; m.userData.baseTransparent = m.transparent; m.userData.baseDepth = m.depthWrite; });
    const nomMap = Object.fromEntries(e.sensors.map((s) => [s.key, s.nominal]));
    items[e.id] = { e, group: g, spec, beacon, ring, sel, mats, nomMap, utility: e.utility, h: spec.h + 1.5, labelTag: (e.sensors.find((s) => !s.cumulative && s.normal) || e.sensors[0]).tag };
    pickables.push(g);
  });

  // pipes with flow particles
  const pipes = PIPES.map((p) => {
    const curve = new THREE.CurvePath();
    for (let i = 0; i < p.pts.length - 1; i += 1) curve.add(new THREE.LineCurve3(new THREE.Vector3(...p.pts[i]), new THREE.Vector3(...p.pts[i + 1])));
    const base = new THREE.Color(UTIL_COLOR[p.utility]);
    const mat = std(base, { roughness: 0.35, metalness: 0.6, emissive: base.clone().multiplyScalar(0.25), emissiveIntensity: 0.5 });
    const mesh = shadow(new THREE.Mesh(keep(new THREE.TubeGeometry(curve, p.pts.length * 10, p.r, 10, false)), mat));
    mesh.castShadow = false;
    scene.add(mesh);
    p.pts.slice(1, -1).forEach((q) => { const j = new THREE.Mesh(keep(new THREE.SphereGeometry(p.r * 1.25, 12, 10)), mat); j.position.set(...q); scene.add(j); });
    const len = curve.getLength();
    const n = Math.max(6, Math.round(len / 5));
    const pm = new THREE.MeshBasicMaterial({ color: base.clone().lerp(new THREE.Color(0xffffff), 0.55) });
    const inst = new THREE.InstancedMesh(keep(new THREE.SphereGeometry(p.r * 1.55, 8, 6)), pm, n);
    scene.add(inst);
    let puff = null;
    if (p.leak) {
      const N = 36, pos = new Float32Array(N * 3), seeds = Array.from({ length: N }, () => [Math.random(), Math.random() * Math.PI * 2, Math.random() * 1.1]);
      const geo = keep(new THREE.BufferGeometry()); geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      puff = new THREE.Points(geo, new THREE.PointsMaterial({ color: 0xe0f2fe, size: 1.5, map: dotTexture(), transparent: true, opacity: 0.9, depthWrite: false }));
      puff.visible = false; puff.userData = { seeds, N }; scene.add(puff);
    }
    return { ...p, curve, mat, mesh, inst, n, base, pm, puff, level: 0 };
  });
  const m4 = new THREE.Matrix4(), tmp = new THREE.Vector3();

  // labels (HTML) that follow equipment
  const labelRoot = document.createElement("div");
  labelRoot.className = "f-labels"; container.appendChild(labelRoot);
  const labelEls = {};
  const labelFor = (id) => {
    if (!labelEls[id]) { const el = document.createElement("div"); el.className = "f-label"; labelRoot.appendChild(el); labelEls[id] = el; }
    return labelEls[id];
  };


  // control room: where the agent and the shift team sit. The responder starts here and walks to the equipment.
  const CR = { x: -10, z: -31, door: -24, aisle: -20 };
  {
    const wall = tone(std(0x334155, { roughness: 0.8 }), "wall");
    box(scene, 10, 4.2, 0.4, wall, CR.x, 2.1, CR.z - 3.5); box(scene, 0.4, 4.2, 7, wall, CR.x - 5, 2.1, CR.z); box(scene, 0.4, 4.2, 7, wall, CR.x + 5, 2.1, CR.z);
    box(scene, 10, 0.3, 7, tone(glass(0x94a3b8, 0.14), "roof"), CR.x, 4.2, CR.z).castShadow = false;
    box(scene, 4, 0.4, 0.4, std(0x38bdf8, { emissive: 0x0ea5e9, emissiveIntensity: 0.8 }), CR.x, 3.2, CR.z + 3.4);
    const l = makeLabel("Control room"); l.position.set(CR.x, 7, CR.z); scene.add(l);
  }
  const resp = new THREE.Group(); resp.visible = false;
  const limbs = {};
  {
    const suit = std(0x2563eb, { emissive: 0x1d4ed8, emissiveIntensity: 0.45, roughness: 0.55, metalness: 0.05 });
    const dark = std(0x1e293b, { roughness: 0.7, metalness: 0.05 });
    const skin = std(0xf1c9a5, { roughness: 0.7, metalness: 0 });
    const vest = std(0xf97316, { emissive: 0xc2410c, emissiveIntensity: 0.35, roughness: 0.6, metalness: 0 });
    const limb = (name, x, y, w, h, mat) => { const g = new THREE.Group(); g.position.set(x, y, 0); cyl(g, w, w * 0.9, h, mat, 0, -h / 2, 0); resp.add(g); limbs[name] = g; };
    limb("legL", -0.22, 1.0, 0.2, 1.0, dark); limb("legR", 0.22, 1.0, 0.2, 1.0, dark);
    box(resp, 0.9, 1.1, 0.5, suit, 0, 1.55, 0);                                  // torso
    box(resp, 0.95, 0.75, 0.55, vest, 0, 1.6, 0);                                // high-visibility vest
    limb("armL", -0.62, 2.0, 0.14, 0.95, suit); limb("armR", 0.62, 2.0, 0.14, 0.95, suit);
    sph(resp, 0.3, skin, 0, 2.42, 0);                                            // head
    sph(resp, 0.36, std(0xfacc15, { emissive: 0xa16207, emissiveIntensity: 0.4, roughness: 0.5, metalness: 0 }), 0, 2.5, 0, 1, 0.8, 1, true);   // hard hat
    const halo = new THREE.Mesh(new THREE.RingGeometry(0.95, 1.2, 32), new THREE.MeshBasicMaterial({ color: 0x60a5fa, transparent: true, opacity: 0.8, side: THREE.DoubleSide, depthWrite: false }));
    halo.rotation.x = -Math.PI / 2; halo.position.y = 0.1; resp.add(halo); limbs.halo = halo;
    resp.scale.setScalar(1.05);
    scene.add(resp);
  }
  const respLabel = document.createElement("div"); respLabel.className = "f-resp"; respLabel.style.display = "none"; labelRoot.appendChild(respLabel);
  const flat = (geo, color, op = 0.9) => { const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: op, side: THREE.DoubleSide, depthWrite: false })); m.rotation.x = -Math.PI / 2; m.visible = false; scene.add(m); return m; };
  const fx = {
    pulse: flat(new THREE.RingGeometry(0.92, 1, 48), 0xef4444),
    work: flat(new THREE.RingGeometry(1.2, 1.38, 40, 1, 0, Math.PI * 1.5), 0x60a5fa),
    scan: flat(new THREE.RingGeometry(0.94, 1, 48), 0x22c55e),
    dot: new THREE.Mesh(new THREE.SphereGeometry(0.55, 14, 10), new THREE.MeshBasicMaterial({ color: 0xfbbf24 })),
    line: new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0, 1, 0)]), new THREE.LineDashedMaterial({ color: 0xfbbf24, dashSize: 1.2, gapSize: 0.8 })),
  };
  fx.dot.visible = false; fx.line.visible = false; scene.add(fx.dot); scene.add(fx.line);
  let response = null;
  const WALK_MS = 8000;
  function walkPath(it) {
    const route = walkRoute(it.e.id);
    if (route) return route;
    const q = it.group.position;                                   // equipment without a mapped walkway: aisle, then straight in
    return [[CR.x, CR.door], [CR.x, CR.aisle], [q.x - 2.8, CR.aisle], [q.x - 2.8, q.z + 3.2]];
  }
  function along(path, u) {
    const seg = path.slice(1).map((p, i) => Math.hypot(p[0] - path[i][0], p[1] - path[i][1])), total = seg.reduce((a, b) => a + b, 0);
    let d = clamp(u, 0, 1) * total;
    for (let i = 0; i < seg.length; i += 1) {
      if (d <= seg[i] || i === seg.length - 1) { const k = seg[i] ? Math.min(1, d / seg[i]) : 1; return [path[i][0] + (path[i + 1][0] - path[i][0]) * k, path[i][1] + (path[i + 1][1] - path[i][1]) * k, Math.atan2(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])]; }
      d -= seg[i];
    }
    return [path[path.length - 1][0], path[path.length - 1][1], 0];
  }
  function updateResponse(t, w, h) {
    const r = response, it = r && items[r.equipId];
    Object.values(fx).forEach((o) => { o.visible = false; });
    if (!r || !it || !r.phase) { resp.visible = false; respLabel.style.display = "none"; return; }
    const path = walkPath(it), now = performance.now(), q = it.group.position, rad = it.spec.r;
    let u = 0, moving = false;
    if (r.phase === "walking") { u = clamp((now - r.walkStart) / WALK_MS, 0, 1); moving = u < 1; }
    else if (r.phase === "working" || r.phase === "verifying") u = 1;
    else if (r.phase === "returning") { u = 1 - clamp((now - r.returnStart) / WALK_MS, 0, 1); moving = u > 0; }
    const [px, pz, heading] = along(path, u);
    const hasPerson = !!r.name;
    resp.visible = hasPerson; resp.position.set(px, 0.25 + (moving ? Math.abs(Math.sin(t * 8)) * 0.07 : 0), pz);
    if (moving) resp.rotation.y = r.phase === "returning" ? heading + Math.PI : heading;
    limbs.halo.material.opacity = 0.55 + 0.35 * Math.sin(t * 4);
    const sw = moving ? Math.sin(t * 8) * 0.7 : 0;
    limbs.legL.rotation.x = sw; limbs.legR.rotation.x = -sw; limbs.armL.rotation.x = -sw * 0.8; limbs.armR.rotation.x = sw * 0.8;
    const at = (o, y = 0.32) => { o.position.set(q.x, y, q.z); return o; };
    if (["detected", "notified", "walking", "working"].includes(r.phase)) {
      const k = (t * 0.7) % 1, p = at(fx.pulse); p.visible = true; p.scale.setScalar(rad * (1 + k * 2.4)); p.material.opacity = 0.85 * (1 - k);
    }
    if (r.phase === "notified" && hasPerson) {
      const a = new THREE.Vector3(CR.x, 3, CR.door - 3), b = new THREE.Vector3(q.x, it.h + 1.5, q.z);
      const pos = fx.line.geometry.attributes.position; pos.setXYZ(0, a.x, a.y, a.z); pos.setXYZ(1, b.x, b.y, b.z); pos.needsUpdate = true; fx.line.computeLineDistances(); fx.line.visible = true;
      const k = (t * 0.45) % 1; fx.dot.position.lerpVectors(a, b, k); fx.dot.visible = true;
    }
    if (r.phase === "working" || (r.phase === "walking" && u >= 1)) { const wk = at(fx.work, 0.4); wk.visible = true; wk.scale.setScalar(rad); wk.rotation.z = t * 2.2; }
    if (r.phase === "verifying") { const k = (t * 0.5) % 1, sc = at(fx.scan, 0.3 + k * it.h); sc.visible = true; sc.scale.setScalar(rad * 1.3); sc.material.opacity = 0.9 * (1 - 0.6 * k); }
    if (hasPerson) {
      tmp.set(px, 3.6, pz).project(camera);
      if (tmp.z > 1) { respLabel.style.display = "none"; return; }
      respLabel.style.display = "block"; respLabel.textContent = r.name;
      respLabel.style.transform = `translate(-50%, -100%) translate(${((tmp.x + 1) / 2) * w}px, ${((1 - tmp.y) / 2) * h}px)`;
    } else respLabel.style.display = "none";
  }

  let grid2 = grid;
  const hemi = scene.children.find((o) => o.isHemisphereLight);
  function applyTheme() {
    const p = PALETTE[themeName()];
    scene.background.setHex(p.bg); scene.fog.color.setHex(p.bg); renderer.toneMappingExposure = p.exposure;
    hemi.color.setHex(p.sky); hemi.groundColor.setHex(p.under); hemi.intensity = p.hemi; sun.intensity = p.sun; fill.intensity = p.fill;
    themed.forEach(([m, key]) => m.color.setHex(p[key]));
    hallGlass.opacity = p.hallOp; hallRoof.opacity = p.roofOp;
    scene.remove(grid2); grid2.geometry.dispose(); grid2.material.dispose();
    grid2 = new THREE.GridHelper(190, 38, p.grid1, p.grid2); grid2.position.y = 0.03; scene.add(grid2);
    scene.traverse((o) => { const sign = o.userData?.sign; if (sign) { drawSign(sign.canvas, sign.text, p); o.material.map.needsUpdate = true; } });
    pipes.forEach((q) => q.puff?.material.color.setHex(p.puff));
  }
  const themeWatch = new MutationObserver(applyTheme);
  themeWatch.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  applyTheme();

  // name pop-ups: switched off altogether, or closed one at a time
  let showLabels = true;
  const closed = new Set();
  const onLabelClose = (ev) => {
    const id = ev.target.closest?.("[data-close]")?.dataset.close;
    if (!id) return;
    ev.preventDefault(); ev.stopPropagation();
    closed.add(id); onLabelsClosed?.(closed.size);
  };
  labelRoot.addEventListener("pointerdown", onLabelClose);

  // state
  let selectedId = null, hoverId = null, filter = null, showFlows = true, alerts = [];
  let leakSet = new Set(), consumerLevel = {}, issueLevel = {};
  // what the equipment shows: the worse of its live reading level and its open issue (so a machine with an open issue is never green)
  const levelOf = (id) => { const tl = view.levels[id] ?? 0, il = issueLevel[id] || 0; return il ? Math.max(tl === 4 ? 0 : tl, il) : tl; };
  const view = { snapTs: null, values: {}, levels: {} };
  let tween = null;
  const clock = new THREE.Clock();
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();

  function flyTo(pos, target, dur = 1.15) {
    tween = { t: clock.elapsedTime, dur, p0: camera.position.clone(), g0: controls.target.clone(), p1: new THREE.Vector3(...pos), g1: new THREE.Vector3(...target) };
  }
  controls.addEventListener("start", () => { tween = null; });

  function applyFilter() {
    Object.values(items).forEach((it) => {
      const dim = !!filter && it.utility !== filter;
      it.mats.forEach((m) => { m.transparent = dim || m.userData.baseTransparent; m.opacity = dim ? 0.1 : m.userData.baseOpacity; m.depthWrite = dim ? false : m.userData.baseDepth; });
      it.dim = dim;
    });
    pipes.forEach((p) => { const dim = !!filter && p.utility !== filter; p.mat.transparent = dim; p.mat.opacity = dim ? 0.1 : 1; p.inst.visible = !dim && showFlows; p.dim = dim; });
  }
  function recomputeAlerts() {
    leakSet = new Set(); consumerLevel = {}; issueLevel = {};
    alerts.filter((a) => a.status !== "VERIFIED").forEach((a) => {
      issueLevel[a.equipment_id] = Math.max(issueLevel[a.equipment_id] || 0, { INFO: 0, WARNING: 1, MAJOR: 2, CRITICAL: 3 }[a.severity] ?? 1);
      if ((a.anomaly_type || "").includes("leak") || (a.anomaly_type === "gas_abnormal_consumption" && /safety/i.test(a.title))) leakSet.add(a.equipment_id);
      const lv = { INFO: 0, WARNING: 1, MAJOR: 2, CRITICAL: 3 }[a.severity] ?? 1;
      (a.consumers || []).forEach((c) => { consumerLevel[c] = Math.max(consumerLevel[c] || 0, lv); });
    });
  }

  // picking
  function pick(ev) {
    const r = renderer.domElement.getBoundingClientRect();
    mouse.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(mouse, camera);
    const hit = ray.intersectObjects(pickables, true)[0];
    if (!hit) return null;
    let o = hit.object;
    while (o && !o.userData.equipId) o = o.parent;
    return o ? o.userData.equipId : null;
  }
  let moveQueued = false, lastMove = null, downAt = null;
  const onMove = (ev) => {
    lastMove = ev;
    if (moveQueued) return;
    moveQueued = true;
    requestAnimationFrame(() => {
      moveQueued = false;
      const id = pick(lastMove);
      renderer.domElement.style.cursor = id ? "pointer" : "grab";
      if (id !== hoverId) { hoverId = id; onHover?.(id, lastMove); }
    });
  };
  const onDown = (ev) => { downAt = [ev.clientX, ev.clientY]; };
  const onUp = (ev) => {
    if (!downAt || Math.hypot(ev.clientX - downAt[0], ev.clientY - downAt[1]) > 5) return;
    onSelect?.(pick(ev));
  };
  const onDbl = (ev) => { const id = pick(ev); if (id) api.focus(id); };
  const onLeave = () => { if (hoverId) { hoverId = null; onHover?.(null); } };
  const dom = renderer.domElement;
  dom.addEventListener("pointermove", onMove); dom.addEventListener("pointerdown", onDown);
  dom.addEventListener("pointerup", onUp); dom.addEventListener("dblclick", onDbl); dom.addEventListener("pointerleave", onLeave);

  // when the tickets drawer covers the right side, move the picture left so the plant stays centred in what is visible
  let inset = 0;
  const applyInset = () => {
    const on = inset && W() > 900;
    camera.zoom = on ? clamp(1 - inset / W() + 0.07, 0.72, 1) : 1;           // and step back so all of it fits
    if (on) camera.setViewOffset(W(), H(), inset / 2, 0, W(), H()); else camera.clearViewOffset();
    camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(() => { renderer.setSize(W(), H()); camera.aspect = W() / H(); camera.updateProjectionMatrix(); applyInset(); });
  ro.observe(container);

  // animation
  let raf = 0, running = true;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function frame() {
    if (!running) return;
    raf = requestAnimationFrame(frame);
    const dt = Math.min(clock.getDelta(), 0.1), t = clock.elapsedTime;
    const st = getState();
    if (st.snap && st.snap.ts !== view.snapTs) { view.snapTs = st.snap.ts; view.values = st.snap.values; view.levels = st.snap.levels; }

    if (tween) {
      const k = Math.min(1, (t - tween.t) / tween.dur), e = k < 0.5 ? 2 * k * k : 1 - ((-2 * k + 2) ** 2) / 2;
      camera.position.lerpVectors(tween.p0, tween.p1, e); controls.target.lerpVectors(tween.g0, tween.g1, e);
      if (k >= 1) tween = null;
    }
    controls.update();

    const anim = reduce ? 0 : dt;
    Object.values(items).forEach((it) => {
      const lvl = levelOf(it.e.id);
      const v = (key) => view.values[`${it.e.id}.${key}`] ?? it.nomMap[key] ?? 0;
      it.spec.update({ v, nom: (k) => it.nomMap[k], t, dt: anim });
      it.beacon.material.color.setHex(LV[lvl]);
      it.beacon.scale.setScalar(lvl >= 2 && !reduce ? 1 + 0.3 * Math.sin(t * 6) : 1);
      it.ring.material.color.setHex(LV[lvl]);
      it.ring.material.opacity = lvl >= 1 ? (lvl >= 2 && !reduce ? 0.55 + 0.35 * Math.sin(t * 5) : 0.6) : 0;
      it.sel.material.opacity = it.e.id === selectedId ? 0.95 : it.e.id === hoverId ? 0.5 : 0;
      const alarm = lvl >= 2 && lvl <= 3;
      it.spec.tint.forEach((m) => {
        if (!m.emissive) return;
        if (it.e.id === selectedId) { m.emissive.setHex(0x2563eb); m.emissiveIntensity = 0.55; }
        else if (alarm) { m.emissive.setHex(LV[lvl]); m.emissiveIntensity = reduce ? 0.4 : 0.25 + 0.25 * Math.sin(t * 5); }
        else if (lvl === 1) { m.emissive.setHex(LV[1]); m.emissiveIntensity = 0.12; }
        else { m.emissive.setHex(0x000000); m.emissiveIntensity = 0; }
      });
    });

    pipes.forEach((p) => {
      const lvl = Math.max(0, ...p.equip.map((id) => levelOf(id)).map((l) => (l === 4 ? 0 : l)));
      p.level = lvl;
      const target = lvl >= 1 ? new THREE.Color(LV[lvl]) : p.base;
      p.mat.color.lerp(target, 0.12);
      p.mat.emissive.copy(p.mat.color).multiplyScalar(lvl >= 2 && !reduce ? 0.55 + 0.4 * Math.sin(t * 6) : 0.25);
      if (p.inst.visible) {
        const nom = p.flow ? catalogNominal(p.flow) : 1;
        const ratio = p.flow ? clamp((view.values[p.flow] ?? nom) / (nom || 1), 0.05, 2.5) : 1;
        const speed = 0.07 * ratio / Math.max(1, p.curve.getLength() / 40);
        for (let i = 0; i < p.n; i += 1) { p.curve.getPointAt((i / p.n + t * speed) % 1, tmp); m4.makeTranslation(tmp.x, tmp.y, tmp.z); p.inst.setMatrixAt(i, m4); }
        p.inst.instanceMatrix.needsUpdate = true;
        p.pm.color.copy(p.mat.color).lerp(new THREE.Color(0xffffff), 0.5);
      }
      if (p.puff) {
        const on = !p.dim && (p.leakFor || []).some((id) => leakSet.has(id));
        p.puff.visible = on;
        if (on) {
          const { seeds, N } = p.puff.userData, pos = p.puff.geometry.attributes.position.array;
          for (let i = 0; i < N; i += 1) { const k = (t * 0.8 + seeds[i][0]) % 1; pos[i * 3] = p.leak[0] + Math.cos(seeds[i][1]) * k * 2.2; pos[i * 3 + 1] = p.leak[1] + k * 3.2; pos[i * 3 + 2] = p.leak[2] + Math.sin(seeds[i][1]) * k * 2.2; }
          p.puff.geometry.attributes.position.needsUpdate = true;
        }
      }
    });

    Object.entries(consumers).forEach(([name, c]) => {
      const lv = consumerLevel[name] || 0;
      c.mats.forEach((m) => { if (lv >= 1) { m.emissive.setHex(LV[lv]); m.emissiveIntensity = 0.3 + (reduce ? 0 : 0.2 * Math.sin(t * 4)); } else { m.emissive.setHex(0); m.emissiveIntensity = 0; } });
    });

    // labels: hovered, selected and every equipment in alarm
    const w = W(), h = H();
    Object.values(items).forEach((it) => {
      const id = it.e.id, lvl = levelOf(id);
      const show = showLabels && (id === hoverId || (!closed.has(id) && (id === selectedId || (lvl >= 2 && lvl <= 3 && !it.dim))));
      const el = show ? labelFor(id) : labelEls[id];
      if (!el) return;
      if (!show) { el.style.display = "none"; return; }
      tmp.setFromMatrixPosition(it.group.matrixWorld); tmp.y += it.h + 1.2;
      tmp.project(camera);
      if (tmp.z > 1) { el.style.display = "none"; return; }
      const tag = catalog.equipment && it.labelTag, s = view.values[tag];
      const spec = it.e.sensors.find((x) => x.tag === tag);
      el.style.display = "block";
      el.style.transform = `translate(-50%, -100%) translate(${((tmp.x + 1) / 2) * w}px, ${((1 - tmp.y) / 2) * h}px)`;
      el.className = `f-label lv${lvl}${id === selectedId ? " sel" : ""}`;
      const html = `<button type="button" class="f-x" data-close="${id}" aria-label="Close label for ${it.e.name}">×</button><b>${it.e.name}</b><span>${spec ? `${spec.label}: ${s == null ? "-" : Number(s).toFixed(spec.decimals)} ${spec.unit}` : ""}</span><em>${LEVELS[lvl]} · ${it.e.zone}${issueLevel[id] ? " · open issue" : ""}</em>`;
      if (el.dataset.html !== html) { el.dataset.html = html; el.innerHTML = html; }          // rewrite only on change, so the close button stays clickable
    });

    updateResponse(t, w, h);
    renderer.render(scene, camera);
  }
  const nominals = {};
  catalog.equipment.forEach((e) => e.sensors.forEach((s) => { nominals[s.tag] = s.nominal; }));
  function catalogNominal(tag) { return nominals[tag]; }
  frame();

  const api = {
    setSelected(id) { selectedId = id; },
    setFilter(u) { filter = u || null; applyFilter(); },
    setFlows(on) { showFlows = on; applyFilter(); },
    setResponse(r) { response = r || null; },
    setLabels(on) { showLabels = !!on; },
    setInset(px) { inset = px || 0; applyInset(); },
    restoreLabels() { closed.clear(); onLabelsClosed?.(0); },
    setAlerts(list) { alerts = list || []; recomputeAlerts(); },
    screenPos(id) {
      const it = items[id]; if (!it) return null;
      tmp.setFromMatrixPosition(it.group.matrixWorld); tmp.y += 2; tmp.project(camera);
      const r = dom.getBoundingClientRect();
      return { x: r.left + ((tmp.x + 1) / 2) * r.width, y: r.top + ((1 - tmp.y) / 2) * r.height };
    },
    resetCamera() { const h = homeFor(W() / H()); flyTo(h.pos, h.target, 1.3); },
    focus(id) {
      const it = items[id]; if (!it) return;
      const p = it.group.position;
      flyTo([p.x + 15, 13, p.z + 20], [p.x, 2.2, p.z], 1.1);
    },
    dispose() {
      running = false; cancelAnimationFrame(raf); ro.disconnect(); themeWatch.disconnect();
      ["pointermove", "pointerdown", "pointerup", "dblclick", "pointerleave"].forEach((n) => dom.removeEventListener(n, { pointermove: onMove, pointerdown: onDown, pointerup: onUp, dblclick: onDbl, pointerleave: onLeave }[n]));
      controls.dispose();
      scene.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => { m.map?.dispose(); m.dispose(); }); });
      disposables.forEach((d) => d.dispose?.());
      renderer.dispose(); dom.remove(); labelRoot.remove();
    },
  };
  return api;
}
