import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { utilityLabel } from "../lib/format.js";

// A simple 3D model of an iPhone assembly line. Every station is fed by one utility (pipes from the
// utility yard at the back). The beacon on each station follows the live utility status from the data.
// The model illustrates the use case; only the status colours come from the uploaded files.

const COLORS = {
  COMPRESSED_AIR: 0x3b82f6,
  CHILLED_WATER: 0x06b6d4,
  HVAC: 0xf59e0b,
  PROCESS_WATER: 0x8b5cf6,
  NITROGEN: 0x94a3b8,
};
const STATUS_COLOR = { NORMAL: 0x16a085, WATCH: 0x3b82f6, WARNING: 0xf59e0b, ALARM: 0xe45c72 };
// x = position along the conveyor; end = [z, y] where the feed pipe enters the station.
const LAYOUT = {
  CHILLED_WATER: { x: -12, station: "Display lamination", end: [-1.2, 4.0] },
  PROCESS_WATER: { x: -6, station: "Cleaning", end: [-1.2, 3.5] },
  COMPRESSED_AIR: { x: 0, station: "Robot assembly", end: [-3.7, 2.0] },
  NITROGEN: { x: 6, station: "Inert-gas sealing", end: [-1.2, 3.4] },
  HVAC: { x: 12, station: "Clean-room test & pack", end: [-1.2, 4.6] },
};
const TYPES = Object.keys(LAYOUT);
const SRC_Z = -8.5;
const PIPE_H = 5.4;
const X0 = -17, X1 = 16;

const std = (color, o = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.55, metalness: 0.15, ...o });
const cssVar = (n, f) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || f;

function add(parent, geo, mat, x, y, z) {
  const m = new THREE.Mesh(geo, mat);
  m.position.set(x, y, z);
  m.castShadow = m.receiveShadow = true;
  parent.add(m);
  return m;
}
const box = (p, w, h, d, mat, x, y, z) => add(p, new THREE.BoxGeometry(w, h, d), mat, x, y, z);
const cyl = (p, r, h, mat, x, y, z, seg = 28) => add(p, new THREE.CylinderGeometry(r, r, h, seg), mat, x, y, z);

function roundedRect(w, h, r) {
  const s = new THREE.Shape();
  const x = -w / 2, y = -h / 2;
  s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
  return s;
}
function slab(w, len, r, depth) {
  const g = new THREE.ExtrudeGeometry(roundedRect(w, len, r), { depth, bevelEnabled: false, curveSegments: 8 });
  g.rotateX(-Math.PI / 2); // extrusion becomes thickness (+y), length runs along z
  return g;
}
const GEO = { body: slab(0.9, 1.9, 0.17, 0.1), screen: slab(0.8, 1.8, 0.13, 0.012), cam: slab(0.42, 0.42, 0.1, 0.02) };

// A phone lying on its back (origin at its bottom face). `detail` adds the camera module under the back.
function makePhone(detail) {
  const g = new THREE.Group();
  const body = new THREE.Mesh(GEO.body, std(0x1f9d55, { metalness: 0.2 }));
  const screen = new THREE.Mesh(GEO.screen, new THREE.MeshStandardMaterial({ color: 0x090c14, roughness: 0.15, metalness: 0.4, emissive: 0x000000 }));
  screen.position.y = 0.1;
  screen.visible = false;
  body.castShadow = screen.castShadow = true;
  g.add(body, screen);
  if (detail) {
    const cam = new THREE.Mesh(GEO.cam, std(0x2a2f3a, { metalness: 0.5 }));
    cam.position.set(-0.17, -0.02, -0.62);
    g.add(cam);
    for (const [dx, dz] of [[-0.29, -0.74], [-0.05, -0.74], [-0.17, -0.5]]) {
      const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.075, 0.075, 0.04, 20), new THREE.MeshStandardMaterial({ color: 0x0a0d14, roughness: 0.1, metalness: 0.8 }));
      lens.position.set(dx, -0.04, dz);
      g.add(lens);
    }
  }
  return { group: g, body, screen };
}
function setPhoneStage(p, x) {
  const board = x < -9.5, titanium = x > 2.5, powered = x > 8.5;
  p.screen.visible = !board;
  p.body.material.color.setHex(titanium ? 0xc9ccd3 : board ? 0x1f9d55 : 0x2b2f3a);
  p.body.material.metalness = titanium ? 0.6 : 0.2;
  p.screen.material.emissive.setHex(powered ? 0x2f6fe0 : 0x000000);
  p.screen.material.emissiveIntensity = powered ? 0.8 : 0;
}

function buildLine(scene, themeMats) {
  const g = new THREE.Group();
  scene.add(g);
  const steel = std(0xcdd5e2, { metalness: 0.4 });
  const dark = std(0x2e3648);
  const white = std(0xf4f6fa);
  const glass = std(0xbcd6f5, { transparent: true, opacity: 0.28, roughness: 0.15 });

  const shadowGround = new THREE.Mesh(new THREE.PlaneGeometry(140, 140), new THREE.ShadowMaterial({ opacity: 0.16 }));
  shadowGround.rotation.x = -Math.PI / 2;
  shadowGround.position.y = -0.07;
  shadowGround.receiveShadow = true;
  g.add(shadowGround);
  box(g, 44, 0.14, 24, themeMats.slab, 1.5, 0, -2); // floor

  // conveyor and safety lines
  box(g, X1 - X0 + 2, 0.9, 2.4, dark, (X0 + X1) / 2, 0.55, 0);
  for (const z of [-1.25, 1.25]) box(g, X1 - X0 + 2, 0.12, 0.12, steel, (X0 + X1) / 2, 1.03, z);
  for (const z of [-2.5, 2.5]) box(g, X1 - X0 + 6, 0.02, 0.12, std(0xf5c542, { roughness: 0.9 }), (X0 + X1) / 2 + 1, 0.08, z);
  for (let x = X0; x <= X1; x += 4) for (const z of [-1, 1]) box(g, 0.2, 0.2, 0.2, steel, x, 0.1, z);

  const beacons = {};
  const flows = {};
  const L = LAYOUT;
  // 1. display lamination (chilled water): cooled press above the belt
  {
    const x = L.CHILLED_WATER.x;
    for (const z of [-1.9, 1.9]) box(g, 0.4, 3.4, 0.4, steel, x, 1.7, z);
    box(g, 3, 1.0, 4.4, white, x, 3.5, 0);
    box(g, 2.4, 0.3, 3.6, std(COLORS.CHILLED_WATER, { metalness: 0.3 }), x, 2.85, 0);
    cyl(g, 0.12, 1.0, steel, x - 0.9, 2.3, 0.7, 12);
    cyl(g, 0.12, 1.0, steel, x + 0.9, 2.3, -0.7, 12);
  }
  // 2. cleaning (process water): glass tunnel with spray nozzles
  {
    const x = L.PROCESS_WATER.x;
    box(g, 3.4, 2.3, 4.2, glass, x, 2.15, 0);
    box(g, 3.5, 0.3, 4.3, white, x, 3.45, 0);
    for (const dx of [-1, 0, 1]) for (const dz of [-1.2, 1.2]) cyl(g, 0.07, 0.5, std(COLORS.PROCESS_WATER), x + dx, 2.85, dz, 10);
  }
  // 3. robot arm (compressed air)
  const robot = new THREE.Group();
  {
    const x = L.COMPRESSED_AIR.x;
    box(g, 1.8, 0.4, 1.8, dark, x, 0.2, -3.7);
    cyl(g, 0.35, 1.9, steel, x, 1.3, -3.7, 20);
    robot.position.set(x, 2.3, -3.7);
    box(robot, 0.5, 0.45, 3.3, std(0xf59e0b, { metalness: 0.3 }), 0, 0, 1.55);
    box(robot, 0.8, 0.25, 0.5, dark, 0, -0.1, 3.3);
    cyl(robot, 0.07, 0.6, steel, 0, -0.55, 3.3, 10);
    g.add(robot);
    box(g, 1.2, 0.8, 1.2, std(COLORS.COMPRESSED_AIR), x, 0.6, -5.8); // pneumatic unit
  }
  // 4. inert-gas sealing (nitrogen)
  {
    const x = L.NITROGEN.x;
    box(g, 3.2, 2.2, 4.2, white, x, 2.2, 0);
    box(g, 2.8, 1.2, 0.05, glass, x, 2.4, 2.13);
    box(g, 3.3, 0.18, 4.3, std(COLORS.NITROGEN), x, 3.4, 0);
  }
  // 5. clean room test & pack (HVAC)
  {
    const x = L.HVAC.x;
    box(g, 4.4, 3.2, 4.8, glass, x, 1.8, 0);
    box(g, 4.5, 0.25, 4.9, white, x, 3.5, 0);
    for (const dx of [-1.2, 1.2]) box(g, 1.5, 0.4, 3.6, std(0xe3e8f1), x + dx, 3.8, 0);
    box(g, 1.2, 1.0, 1.2, white, x + 1.1, 1.4, 1.6); // packing table
  }

  // utility yard behind the line
  box(g, 38, 0.1, 5, themeMats.yard, 0, 0.02, SRC_Z);
  {
    const x = L.CHILLED_WATER.x;
    box(g, 3.6, 2.2, 3, std(0xdce6f4), x, 1.2, SRC_Z);
    for (const dx of [-0.9, 0.9]) cyl(g, 0.8, 0.2, dark, x + dx, 2.4, SRC_Z, 24);
  }
  {
    const x = L.PROCESS_WATER.x;
    cyl(g, 1.5, 3.8, std(0xe2e6f2, { metalness: 0.4 }), x, 2.0, SRC_Z, 32);
    add(g, new THREE.CylinderGeometry(0.01, 1.5, 0.6, 32), std(COLORS.PROCESS_WATER), x, 4.2, SRC_Z);
  }
  {
    const x = L.COMPRESSED_AIR.x;
    const tank = cyl(g, 0.95, 4.6, std(COLORS.COMPRESSED_AIR, { metalness: 0.3 }), x, 1.4, SRC_Z);
    tank.rotation.z = Math.PI / 2;
    for (const dx of [-1.5, 1.5]) box(g, 0.4, 0.7, 1.5, dark, x + dx, 0.4, SRC_Z);
  }
  {
    const x = L.NITROGEN.x;
    for (const dx of [-1, 1]) {
      cyl(g, 0.9, 3.2, std(0xf2f4f8, { metalness: 0.5, roughness: 0.35 }), x + dx, 1.7, SRC_Z);
      const cap = add(g, new THREE.SphereGeometry(0.9, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2), std(0xf2f4f8, { metalness: 0.5, roughness: 0.35 }), x + dx, 3.3, SRC_Z);
      cap.castShadow = true;
    }
  }
  {
    const x = L.HVAC.x;
    box(g, 3.6, 2.4, 2.8, std(0xe9eef6), x, 1.3, SRC_Z);
    box(g, 3.7, 0.3, 2.9, std(COLORS.HVAC), x, 2.65, SRC_Z);
    cyl(g, 0.55, 0.25, dark, x, 2.95, SRC_Z, 20);
  }

  // feed pipes, beacons, flow dots
  for (const type of TYPES) {
    const { x, end } = L[type];
    const [ez, ey] = end;
    const pts = [[x, 1.6, SRC_Z], [x, PIPE_H, SRC_Z], [x, PIPE_H, ez], [x, ey, ez]].map((p) => new THREE.Vector3(...p));
    const path = new THREE.CurvePath();
    for (let i = 0; i < pts.length - 1; i++) path.add(new THREE.LineCurve3(pts[i], pts[i + 1]));
    const tube = new THREE.Mesh(new THREE.TubeGeometry(path, 80, 0.12, 10), std(COLORS[type], { metalness: 0.3, roughness: 0.4 }));
    tube.castShadow = true;
    g.add(tube);
    const inst = new THREE.InstancedMesh(new THREE.SphereGeometry(0.1, 10, 8), new THREE.MeshBasicMaterial({ color: 0xffffff }), 14);
    g.add(inst);
    flows[type] = { path, inst };

    const mat = new THREE.MeshStandardMaterial({ color: STATUS_COLOR.NORMAL, emissive: STATUS_COLOR.NORMAL, emissiveIntensity: 0.9, roughness: 0.3 });
    const sphere = new THREE.Mesh(new THREE.SphereGeometry(0.34, 20, 16), mat);
    sphere.position.set(x, PIPE_H + 0.9, ez);
    g.add(sphere);
    const ringMat = new THREE.MeshBasicMaterial({ color: STATUS_COLOR.NORMAL, transparent: true, opacity: 0, side: THREE.DoubleSide });
    const ring = new THREE.Mesh(new THREE.RingGeometry(1.5, 1.7, 48), ringMat);
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(x, 0.16, 0);
    g.add(ring);
    beacons[type] = { mat, ringMat, ring };
  }

  // phones on the belt: green circuit board -> display fitted -> titanium body -> powered on
  const phones = [];
  for (let i = 0; i < 9; i++) {
    const p = makePhone(false);
    p.group.position.y = 1.1;
    g.add(p.group);
    phones.push(p);
  }
  // finished iPhone showcase at the end of the line
  const show = new THREE.Group();
  show.position.set(20.5, 0, 0);
  cyl(show, 1.6, 0.5, std(0x2e3648), 0, 0.25, 0, 40);
  cyl(show, 1.35, 0.12, std(0xe8ecf4), 0, 0.56, 0, 40);
  const big = makePhone(true);
  big.body.material.color.setHex(0xc9ccd3);
  big.body.material.metalness = 0.6;
  big.screen.visible = true;
  big.screen.material.emissive.setHex(0x2f6fe0);
  big.screen.material.emissiveIntensity = 0.8;
  const stand = new THREE.Group();
  stand.rotation.x = Math.PI / 2;
  stand.scale.setScalar(2.2);
  stand.position.y = 3.15;
  stand.add(big.group);
  show.add(stand);
  g.add(show);
  return { beacons, flows, phones, show, robot };
}

export default function PlantScene({ utilities, onSelect }) {
  const hostRef = useRef(null);
  const labelRefs = useRef({});
  const statusRef = useRef({});
  const [failed, setFailed] = useState(false);

  statusRef.current = Object.fromEntries((utilities || []).map((u) => [u.utility_type, u.status]));

  useEffect(() => {
    const host = hostRef.current;
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setFailed(true);
      return undefined;
    }
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.domElement.style.touchAction = "pan-y";
    renderer.domElement.setAttribute("aria-hidden", "true");
    host.prepend(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 0.5, 300);
    camera.position.set(6, 11, 25);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(3.5, 2.2, -1.5);
    controls.enableZoom = false;
    controls.enablePan = false;
    controls.enableDamping = true;
    controls.minPolarAngle = 0.6;
    controls.maxPolarAngle = 1.38;
    controls.minAzimuthAngle = -0.9;
    controls.maxAzimuthAngle = 0.9;
    controls.update();

    scene.add(new THREE.HemisphereLight(0xffffff, 0x8794b0, 1.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.7);
    sun.position.set(-14, 30, 24);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -34, right: 34, top: 26, bottom: -26, near: 1, far: 100 });
    sun.shadow.bias = -0.0004;
    scene.add(sun);

    const themeMats = { slab: std(0xdfe5ef), yard: std(0xcfd8e6) };
    const applyTheme = () => {
      themeMats.slab.color.set(cssVar("--muted-fill", "#eef1f6"));
      themeMats.yard.color.set(cssVar("--kg-bg-2", "#f8fafd"));
      sun.intensity = document.documentElement.dataset.theme === "dark" ? 1.0 : 1.7;
    };
    applyTheme();
    const themeObs = new MutationObserver(applyTheme);
    themeObs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

    const { beacons, flows, phones, show, robot } = buildLine(scene, themeMats);
    const dummy = new THREE.Object3D();
    const tmp = new THREE.Vector3();

    let width = 1, height = 1;
    const resize = () => {
      width = host.clientWidth || 1;
      height = host.clientHeight || 1;
      renderer.setSize(width, height, false);
      renderer.domElement.style.width = "100%";
      renderer.domElement.style.height = "100%";
      camera.aspect = width / height;
      camera.fov = width < 560 ? 62 : 36;
      camera.updateProjectionMatrix();
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(host);
    let visible = true;
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; });
    io.observe(host);

    const clock = new THREE.Clock();
    renderer.setAnimationLoop(() => {
      if (!visible || document.hidden) return;
      const t = reduce ? 1.2 : clock.getElapsedTime();
      controls.update();

      for (const [idx, type] of TYPES.entries()) {
        const status = statusRef.current[type] || "NORMAL";
        const color = STATUS_COLOR[status] ?? STATUS_COLOR.NORMAL;
        const b = beacons[type];
        b.mat.color.setHex(color);
        b.mat.emissive.setHex(color);
        b.ringMat.color.setHex(color);
        const pulse = status === "NORMAL" ? 0 : (Math.sin(t * 4) + 1) / 2;
        b.mat.emissiveIntensity = 0.7 + 0.5 * pulse;
        b.ringMat.opacity = status === "NORMAL" ? 0 : 0.85 - 0.5 * pulse;
        b.ring.scale.setScalar(1 + 0.35 * pulse);

        const { path, inst } = flows[type];
        for (let i = 0; i < 14; i++) {
          path.getPointAt((i / 14 + t * 0.05) % 1, tmp);
          dummy.position.copy(tmp);
          dummy.updateMatrix();
          inst.setMatrixAt(i, dummy.matrix);
        }
        inst.instanceMatrix.needsUpdate = true;

        const el = labelRefs.current[type];
        if (el) {
          tmp.set(LAYOUT[type].x, PIPE_H + (idx % 2 ? 2.9 : 1.3), LAYOUT[type].end[0]).project(camera);
          el.style.transform = `translate(${((tmp.x * 0.5 + 0.5) * width).toFixed(1)}px, ${((-tmp.y * 0.5 + 0.5) * height).toFixed(1)}px) translate(-50%, -100%)`;
          el.style.visibility = tmp.z > 1 ? "hidden" : "visible";
        }
      }
      phones.forEach((p, i) => {
        const x = X0 + ((i / phones.length + t * 0.035) % 1) * (X1 - X0 + 1);
        p.group.position.x = x;
        setPhoneStage(p, x);
      });
      robot.rotation.y = Math.sin(t * 1.1) * 0.55;
      show.rotation.y = t * 0.6;
      renderer.render(scene, camera);
    });

    return () => {
      renderer.setAnimationLoop(null);
      ro.disconnect();
      io.disconnect();
      themeObs.disconnect();
      controls.dispose();
      scene.traverse((o) => {
        if (o.geometry && !Object.values(GEO).includes(o.geometry)) o.geometry.dispose?.();
        const m = o.material;
        if (m) (Array.isArray(m) ? m : [m]).forEach((x) => x.dispose());
      });
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return (
    <div className="plant" ref={hostRef}>
      {failed && <div className="plant-fallback muted">The 3D view needs WebGL, which this browser does not provide. The cards below show the same status.</div>}
      {!failed && (
        <>
          <div className="plant-labels">
            {TYPES.map((type) => {
              const status = statusRef.current[type] || "NORMAL";
              return (
                <button key={type} ref={(el) => { labelRefs.current[type] = el; }}
                        className={`plant-label tone-${status.toLowerCase()}`} onClick={() => onSelect?.(type)}
                        aria-label={`${utilityLabel(type)} for ${LAYOUT[type].station}: ${status}. Show details`}>
                  <span className="dot" />
                  <span className="plant-label-text">
                    <span className="plant-label-name">{utilityLabel(type)}</span>
                    <span className="plant-label-station">{LAYOUT[type].station}</span>
                  </span>
                </button>
              );
            })}
          </div>
          <div className="plant-legend" aria-hidden="true">
            <span><i style={{ background: "#16a085" }} />Normal</span>
            <span><i style={{ background: "#3b82f6" }} />Watch</span>
            <span><i style={{ background: "#e45c72" }} />Alarm</span>
            <span className="muted">Drag to rotate</span>
          </div>
        </>
      )}
    </div>
  );
}
