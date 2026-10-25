// environment.js — a quiet Japanese countryside street around the origin, fully procedural.
//
// Everything lives inside a 50 m × 50 m box (x, z ∈ [-25, 25]); the edges are hidden by fog,
// a tree line and mountain silhouettes, with a sky dome inside the same box. Sakura stands at
// the origin on the road facing +Z (the camera side). Rendering goes through an EffectComposer
// with a Bokeh depth-of-field focused on her; if postprocessing fails for any reason the
// Environment falls back to a plain renderer.render() so the page never breaks.
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { BokehPass } from 'three/addons/postprocessing/BokehPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

const HALF = 25;                       // world half-extent (50 m box)
const FOCUS_POINT = new THREE.Vector3(0, 1.1, 0);

// deterministic PRNG so the street looks the same on every load
function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rnd = mulberry32(20261024);
const rr = (a, b) => a + (b - a) * rnd();

const _matCache = new Map();
function lambert(hex, extra = {}) {
  const key = hex + JSON.stringify(extra);
  if (!_matCache.has(key)) _matCache.set(key, new THREE.MeshLambertMaterial({ color: hex, ...extra }));
  return _matCache.get(key);
}
function addVertexColors(geo, hex, jitter = 0) {
  const base = new THREE.Color(hex);
  const n = geo.getAttribute('position').count;
  const arr = new Float32Array(n * 3);
  const c = new THREE.Color();
  for (let i = 0; i < n; i++) {
    c.copy(base);
    if (jitter) c.offsetHSL(0, 0, (rnd() - 0.5) * jitter);
    arr[i * 3] = c.r; arr[i * 3 + 1] = c.g; arr[i * 3 + 2] = c.b;
  }
  geo.setAttribute('color', new THREE.BufferAttribute(arr, 3));
  return geo;
}
function box(w, h, d, hex, x = 0, y = 0, z = 0, opts = {}) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), lambert(hex, opts.mat));
  m.position.set(x, y, z);
  m.castShadow = opts.cast ?? true;
  m.receiveShadow = opts.receive ?? false;
  return m;
}

/** BokehPass that hides additive/transparent helpers while it renders its depth map. */
class SoftBokehPass extends BokehPass {
  constructor(scene, camera, params, hideDuringDepth) {
    super(scene, camera, params);
    this._hide = hideDuringDepth;
  }
  render(renderer, writeBuffer, readBuffer, deltaTime, maskActive) {
    const prev = this._hide.map((o) => o.visible);
    this._hide.forEach((o) => { o.visible = false; });
    try { super.render(renderer, writeBuffer, readBuffer, deltaTime, maskActive); }
    finally { this._hide.forEach((o, i) => { o.visible = prev[i]; }); }
  }
}

export class Environment {
  constructor(scene, renderer, camera, opts = {}) {
    this.scene = scene; this.renderer = renderer; this.camera = camera;
    this.opts = { dof: true, shadows: true, ...opts };
    this.t = 0;
    this.sway = [];       // tree canopies to sway
    this.petals = null;
    this.water = null;
    this.flicker = [];
    this.hideForDepth = [];
    this.composer = null;
    this.bokeh = null;

    this._lighting();
    this._sky();
    this._ground();
    this._road();
    this._river();
    this._houses();
    this._shrine();
    this._trees();
    this._props();
    this._petals();
    this._collectHelpers();
    if (this.opts.dof) this._postprocessing();
  }

  // ------------------------------------------------------------ lighting / atmosphere
  _lighting() {
    const s = this.scene;
    s.traverse((o) => {
      if (o.isHemisphereLight) { o.color.set(0xe9f0ff); o.groundColor.set(0x7c8a62); o.intensity = 1.15; }
      if (o.isDirectionalLight) {
        o.color.set(0xfff1dc); o.intensity = 1.9; o.position.set(6, 10, 5);
        if (this.opts.shadows) {
          this.renderer.shadowMap.enabled = true;
          this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
          o.castShadow = true;
          o.shadow.mapSize.set(1024, 1024);
          const c = o.shadow.camera; c.left = -16; c.right = 16; c.top = 16; c.bottom = -16; c.near = 0.5; c.far = 40;
          o.shadow.bias = -0.0006;
        }
      }
    });
    s.fog = new THREE.Fog(0xead9df, 10, 30);
    s.background = new THREE.Color(0xdcc5cf);
  }

  _sky() {
    const geo = new THREE.SphereGeometry(HALF - 0.2, 48, 24);
    const pos = geo.getAttribute('position');
    const col = new Float32Array(pos.count * 3);
    const zenith = new THREE.Color(0x8fb8ea), mid = new THREE.Color(0xd8d2e8), horizon = new THREE.Color(0xf4ddd9), low = new THREE.Color(0xead9df);
    const c = new THREE.Color();
    for (let i = 0; i < pos.count; i++) {
      const y = pos.getY(i) / (HALF - 0.2);          // -1..1
      if (y >= 0.35) c.copy(mid).lerp(zenith, Math.min(1, (y - 0.35) / 0.65));
      else if (y >= 0.0) c.copy(horizon).lerp(mid, y / 0.35);
      else c.copy(low);
      col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b;
    }
    geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
    const sky = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide, fog: false, depthWrite: false }));
    sky.renderOrder = -10; sky.frustumCulled = false;
    this.scene.add(sky);

    // mountain silhouettes: two jagged rings just inside the box, faded by fog
    const ridge = (radius, hMin, hMax, hex, seed) => {
      const N = 112, verts = [], cols = [];
      const top = new THREE.Color(hex), base = new THREE.Color(0xead9df);
      const r = mulberry32(seed);
      const heights = [];
      for (let i = 0; i < N; i++) heights.push(hMin + (hMax - hMin) * (0.5 + 0.5 * Math.sin(i * 0.9 + r() * 2) * Math.sin(i * 0.37 + r())));
      for (let i = 0; i < N; i++) {
        const a0 = (i / N) * Math.PI * 2, a1 = ((i + 1) / N) * Math.PI * 2;
        const p0 = [Math.cos(a0) * radius, -0.5, Math.sin(a0) * radius], p1 = [Math.cos(a1) * radius, -0.5, Math.sin(a1) * radius];
        const t0 = [Math.cos(a0) * radius, heights[i], Math.sin(a0) * radius], t1 = [Math.cos(a1) * radius, heights[(i + 1) % N], Math.sin(a1) * radius];
        verts.push(...p0, ...p1, ...t1, ...p0, ...t1, ...t0);
        cols.push(...base.toArray(), ...base.toArray(), ...top.toArray(), ...base.toArray(), ...top.toArray(), ...top.toArray());
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
      g.setAttribute('color', new THREE.Float32BufferAttribute(cols, 3));
      const m = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide }));
      m.frustumCulled = false;
      return m;
    };
    this.scene.add(ridge(HALF - 0.6, 5, 11, 0xb7bdd0, 7), ridge(HALF - 1.6, 3, 7, 0x9ea7bd, 11));
  }

  // ------------------------------------------------------------ ground, fields, river
  _ground() {
    // ground is split around the river channel (z -11 … -7)
    const mk = (zc, depth) => {
      const geo = new THREE.PlaneGeometry(2 * HALF, depth, 50, Math.max(4, Math.round(depth)));
      addVertexColors(geo, 0x6e8e47, 0.16);
      const m = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ vertexColors: true }));
      m.rotation.x = -Math.PI / 2; m.position.set(0, 0, zc); m.receiveShadow = true;
      return m;
    };
    this.scene.add(mk(-18, 14), mk(9, 32));

    // rice paddies on both sides (flat, lighter green with row stripes)
    const paddy = (x, z, w, d) => {
      const g = new THREE.Group();
      g.add(box(w, 0.04, d, 0x7aa24e, 0, 0.02, 0, { cast: false, receive: true }));
      for (let i = -d / 2 + 0.6; i < d / 2; i += 1.2) g.add(box(w - 0.6, 0.06, 0.18, 0x5d8a3a, 0, 0.04, i, { cast: false }));
      g.add(box(w + 0.4, 0.12, 0.3, 0x8d8366, 0, 0.06, d / 2 + 0.15, { cast: false }));   // dirt path edge
      g.position.set(x, 0, z);
      return g;
    };
    for (const [x, z, w, d] of [[10.5, -19, 9, 9], [10.5, 3, 9, 10], [10.5, 17, 9, 10], [-10.5, 5, 9, 9], [-10.5, 18, 9, 8]]) this.scene.add(paddy(x, z, w, d));

    // irrigation ditches between road and fields (interrupted at the river)
    for (const x of [-5.4, 5.4]) {
      for (const [zc, len] of [[-18.25, 13.5], [9.25, 31.5]]) {
        this.scene.add(box(0.7, 0.4, len, 0xa6a39c, x, -0.18, zc, { cast: false, receive: true }));
        this.scene.add(box(0.44, 0.3, len, 0x4e7a93, x, -0.2, zc, { cast: false }));
      }
    }
  }

  _road() {
    const roadGeo = new THREE.PlaneGeometry(6.2, 2 * HALF, 8, 60);
    addVertexColors(roadGeo, 0x3e3e46, 0.1);
    const road = new THREE.Mesh(roadGeo, new THREE.MeshLambertMaterial({ vertexColors: true }));
    road.rotation.x = -Math.PI / 2; road.position.y = 0.012; road.receiveShadow = true;
    this.scene.add(road);
    const line = (w, len, hex, x, z) => {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(w, len), lambert(hex));
      m.rotation.x = -Math.PI / 2; m.position.set(x, 0.02, z); m.receiveShadow = true;
      return m;
    };
    this.scene.add(line(0.12, 2 * HALF, 0xe9e9e4, -2.85, 0), line(0.12, 2 * HALF, 0xe9e9e4, 2.85, 0));
    for (let z = -24; z <= 24; z += 4) if (Math.abs(z) > 2.2) this.scene.add(line(0.12, 2, 0xe9d28c, 0, z));

    // concrete roadside gutters (側溝) with grating slabs; interrupted at the river
    const grateGeo = new THREE.BoxGeometry(0.5, 0.05, 0.6);
    const grate = new THREE.InstancedMesh(grateGeo, lambert(0x6c6e72), 60);
    let gi = 0; const mtx = new THREE.Matrix4();
    for (const x of [-3.45, 3.45]) {
      for (const [zc, len] of [[-18.25, 13.5], [9.25, 31.5]]) {
        this.scene.add(box(0.5, 0.36, len, 0xaaa8a1, x, -0.16, zc, { cast: false, receive: true }));
        this.scene.add(box(0.3, 0.22, len, 0x33373b, x, -0.1, zc, { cast: false }));
        for (let z = zc - len / 2 + 1; z < zc + len / 2; z += 4) { mtx.makeTranslation(x, 0.035, z); grate.setMatrixAt(gi++, mtx); }
      }
    }
    grate.count = gi; grate.castShadow = false; grate.receiveShadow = true;
    this.scene.add(grate);
  }

  _river() {
    // channel: banks sloping down from z=-11 / z=-7 to the water at y=-0.42
    const bank = (zEdge, dir) => {
      const dz = 0.7 * dir, dy = -0.45;
      const len = Math.hypot(dz, dy);
      const m = new THREE.Mesh(new THREE.PlaneGeometry(2 * HALF, len, 40, 1), new THREE.MeshLambertMaterial({ color: 0x7f8f5a, side: THREE.DoubleSide }));
      m.rotation.x = Math.atan2(dz, dy);
      m.position.set(0, dy / 2, zEdge + dz / 2);
      m.receiveShadow = true;
      return m;
    };
    this.scene.add(bank(-11, 1), bank(-7, -1));

    // water: scrolling canvas texture
    const cv = document.createElement('canvas'); cv.width = 256; cv.height = 128;
    const ctx = cv.getContext('2d');
    ctx.fillStyle = '#5f98bf'; ctx.fillRect(0, 0, 256, 128);
    for (let i = 0; i < 40; i++) {
      ctx.strokeStyle = `rgba(255,255,255,${0.05 + rnd() * 0.12})`; ctx.lineWidth = 1 + rnd() * 2;
      ctx.beginPath(); const y = rnd() * 128; ctx.moveTo(0, y);
      for (let x = 0; x <= 256; x += 16) ctx.lineTo(x, y + Math.sin(x * 0.08 + i) * 4);
      ctx.stroke();
    }
    const tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace;
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping; tex.repeat.set(10, 1);
    const water = new THREE.Mesh(new THREE.PlaneGeometry(2 * HALF, 2.6), new THREE.MeshStandardMaterial({ map: tex, color: 0xa9d2e6, roughness: 0.3, metalness: 0.05, transparent: true, opacity: 0.92 }));
    water.rotation.x = -Math.PI / 2; water.position.set(0, -0.42, -9); water.receiveShadow = true;
    this.scene.add(water);
    this.water = tex;
    this.scene.add(box(2 * HALF, 0.3, 2.6, 0x2f3a3a, 0, -0.6, -9, { cast: false }));   // riverbed

    // bridge: deck sides + parapets
    this.scene.add(box(6.6, 0.5, 4.8, 0x8f8d86, 0, -0.26, -9, { cast: true }));
    for (const x of [-3.2, 3.2]) {
      this.scene.add(box(0.26, 0.4, 4.8, 0xbcb9b1, x, 0.2, -9));
      for (let z = -11; z <= -7; z += 1) this.scene.add(box(0.1, 0.9, 0.1, 0x9a9890, x, 0.45, z));
      this.scene.add(box(0.12, 0.08, 4.8, 0xd0cdc4, x, 0.9, -9));
    }

    // reeds along both banks
    const reedGeo = new THREE.ConeGeometry(0.05, 0.9, 5);
    const reeds = new THREE.InstancedMesh(reedGeo, lambert(0x4f7a3a), 160);
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3();
    let n = 0;
    for (let i = 0; i < 160; i++) {
      const side = i % 2 ? -1 : 1;
      const x = rr(-24, 24); if (Math.abs(x) < 3.9) continue;
      const z = -9 + side * rr(1.6, 2.1);
      p.set(x, -0.1 + rnd() * 0.2, z); q.setFromEuler(new THREE.Euler(rr(-0.15, 0.15), rr(0, 6.28), rr(-0.15, 0.15)));
      s.set(1, rr(0.7, 1.4), 1);
      m4.compose(p, q, s); reeds.setMatrixAt(n++, m4);
    }
    reeds.count = n; reeds.castShadow = true;
    this.scene.add(reeds);
  }

  // ------------------------------------------------------------ buildings
  _house(w, d, h, wallHex, roofHex, facing) {
    const g = new THREE.Group();
    g.add(box(w, h, d, wallHex, 0, h / 2, 0, { receive: true }));
    g.add(box(w + 0.3, 0.25, d + 0.3, 0x5a5048, 0, 0.12, 0));                              // foundation
    // hipped roof (pyramid) + ridge cap, with overhang
    const ov = 0.55, roofH = Math.max(1.4, w * 0.3);
    const roof = new THREE.Mesh(new THREE.ConeGeometry((w / 2 + ov) * Math.SQRT2, roofH, 4, 1), lambert(roofHex));
    roof.rotation.y = Math.PI / 4; roof.scale.z = (d / 2 + ov) / (w / 2 + ov);
    roof.position.y = h + roofH / 2; roof.castShadow = true;
    g.add(roof);
    g.add(box(w * 0.45, 0.16, 0.5, 0x2a2e36, 0, h + roofH - 0.02, 0));                    // ridge cap
    g.add(box(w + 2 * ov + 0.05, 0.14, d + 2 * ov + 0.05, 0xf1e8d8, 0, h - 0.02, 0));      // eave board
    // door + windows on the facing side (+Z of the group)
    g.add(box(1.1, 2.0, 0.08, 0x4a3b2f, -w * 0.22, 1.0, d / 2 + 0.03));
    g.add(box(0.5, 1.95, 0.03, 0xe9e2cf, -w * 0.22 - 0.28, 1.0, d / 2 + 0.08));             // sliding door frame
    for (const wx of [w * 0.2, w * 0.2 + 1.3]) {
      if (wx + 0.6 > w / 2) continue;
      g.add(box(1.1, 0.9, 0.06, 0xa9c8dd, wx, 1.6, d / 2 + 0.03));
      g.add(box(1.2, 0.08, 0.1, 0x4a3b2f, wx, 2.1, d / 2 + 0.05));
    }
    // low block wall + hedge in front
    g.add(box(w + 1.2, 0.8, 0.25, 0xb3aea4, 0, 0.4, d / 2 + 1.6, { receive: true }));
    g.add(box(w * 0.5, 0.6, 0.5, 0x4f7c3c, -w * 0.25, 1.05, d / 2 + 1.6));
    g.rotation.y = facing;
    return g;
  }

  _houses() {
    const walls = [0xf2e8d5, 0xe8dcc3, 0xd9cdb5, 0xf5efe3, 0xcbb9a0], roofs = [0x3b4557, 0x47505f, 0x2f3a49, 0x55525c];
    const placements = [
      [-10.5, -21, 0], [-11, -3, 0.08], [-10.8, 8, -0.05], [-11.5, 21, 0.1],
      [10.6, -22, Math.PI], [11, -13, Math.PI + 0.06], [10.5, 11, Math.PI - 0.08], [11.2, 22, Math.PI],
    ];
    placements.forEach(([x, z, rot], i) => {
      const w = rr(5.2, 7.2), d = rr(4.6, 6.4), h = rr(3.0, 3.8);
      const house = this._house(w, d, h, walls[i % walls.length], roofs[i % roofs.length], rot + Math.PI / 2);
      // make the facing side (+Z of the group) look toward the road
      house.rotation.y = x < 0 ? -Math.PI / 2 + rot * 0.3 : Math.PI / 2 + rot * 0.3;
      house.position.set(x, 0, z);
      this.scene.add(house);
    });
  }

  _shrine() {
    const g = new THREE.Group();
    // stone path from the road
    for (let i = 0; i < 6; i++) g.add(box(1.6, 0.06, 0.8, 0xb9b6ae, 0, 0.03, 3.2 - i * 1.0, { cast: false, receive: true }));
    // torii
    const red = 0xc8392b;
    for (const x of [-1.3, 1.3]) {
      const post = new THREE.Mesh(new THREE.CylinderGeometry(0.13, 0.15, 3.4, 10), lambert(red));
      post.position.set(x, 1.7, 2.4); post.castShadow = true; g.add(post);
    }
    g.add(box(3.9, 0.22, 0.3, red, 0, 3.45, 2.4));
    g.add(box(4.1, 0.14, 0.36, 0x1d1d22, 0, 3.63, 2.4));
    g.add(box(3.3, 0.16, 0.2, red, 0, 2.85, 2.4));
    g.add(box(0.26, 0.4, 0.2, red, 0, 3.15, 2.4));
    // honden (small hall) with a steep roof
    g.add(box(2.6, 0.5, 2.6, 0x8d8780, 0, 0.25, -1.4, { receive: true }));
    g.add(box(2.1, 1.9, 2.1, 0x6f4e36, 0, 1.45, -1.4));
    const roof = new THREE.Mesh(new THREE.ConeGeometry(2.2, 1.6, 4, 1), lambert(0x2f3a49));
    roof.rotation.y = Math.PI / 4; roof.position.set(0, 3.2, -1.4); roof.castShadow = true; g.add(roof);
    g.add(box(0.9, 1.2, 0.06, 0x3a2a20, 0, 1.1, -0.32));                       // door
    g.add(box(1.2, 0.5, 0.1, 0xd9c8a0, 0, 2.1, -0.3));                         // shimenawa-ish plaque
    // stone lanterns
    for (const x of [-1.5, 1.5]) {
      const l = new THREE.Group();
      l.add(box(0.5, 0.25, 0.5, 0x9b9892, 0, 0.12, 0));
      const post = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.12, 0.9, 8), lambert(0x9b9892)); post.position.y = 0.7; l.add(post);
      l.add(box(0.42, 0.42, 0.42, 0xa8a59e, 0, 1.35, 0));
      const cap = new THREE.Mesh(new THREE.ConeGeometry(0.42, 0.3, 4), lambert(0x8a8781)); cap.rotation.y = Math.PI / 4; cap.position.y = 1.7; l.add(cap);
      l.position.set(x, 0, 0.6); l.traverse((o) => { o.castShadow = true; });
      g.add(l);
    }
    // low fence
    for (const x of [-2.4, 2.4]) g.add(box(0.12, 0.9, 5.2, 0x7b6a5a, x, 0.45, -0.2));
    g.position.set(-9.6, 0, -13.5); g.rotation.y = Math.PI / 2;   // sits on the left, faces the road
    this.scene.add(g);
  }

  // ------------------------------------------------------------ trees, props, petals
  _tree(x, z, { pink = false, scale = 1, simple = false } = {}) {
    const trunkH = 1.9 * scale;
    const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.11 * scale, 0.2 * scale, trunkH, 7), lambert(pink ? 0x5a4034 : 0x5b4a3a));
    trunk.position.set(x, trunkH / 2, z); trunk.castShadow = true;
    this.scene.add(trunk);
    const palette = pink ? [0xffc4da, 0xf9b1cd, 0xffd3e3, 0xf7a6c4] : [0x4f8a3a, 0x5f9a44, 0x447a33, 0x6aa64b];
    const geos = [];
    const blobs = simple ? 3 : 6;
    for (let i = 0; i < blobs; i++) {
      const r = (0.75 + rnd() * 0.55) * scale;
      const g = new THREE.IcosahedronGeometry(r, 1);
      g.translate(rr(-0.7, 0.7) * scale, trunkH + 0.55 * scale + rr(-0.3, 0.9) * scale, rr(-0.7, 0.7) * scale);
      addVertexColors(g, palette[i % palette.length], 0.12);
      geos.push(g);
    }
    const canopy = new THREE.Mesh(mergeGeometries(geos, false), new THREE.MeshLambertMaterial({ vertexColors: true }));
    canopy.position.set(x, 0, z); canopy.castShadow = true; canopy.receiveShadow = false;
    this.scene.add(canopy);
    this.sway.push({ mesh: canopy, phase: rnd() * 6.28, amp: pink ? 0.025 : 0.015 });
    return canopy;
  }

  _trees() {
    // sakura framing her, then greens, then a perimeter tree line to hide the box edge
    for (const [x, z, s] of [[-4.6, 3.2, 1.15], [4.9, 2.4, 1.05], [-5.2, -5.5, 1.2], [5.6, -4.2, 1.1], [-4.8, 12, 1.0], [5.0, 14, 1.1], [7.5, -8.5, 0.9]]) this._tree(x, z, { pink: true, scale: s });
    for (const [x, z, s] of [[-15, -23, 1.3], [15.5, -19, 1.2], [16, 7, 1.1], [-16.5, 14, 1.25], [13, 18, 1.0], [-14.5, 1, 0.9], [-7, 24, 1.1], [7.5, 24, 1.0]]) this._tree(x, z, { scale: s });
    const N = 30;
    for (let i = 0; i < N; i++) {
      const a = (i / N) * Math.PI * 2 + rnd() * 0.12;
      const r = rr(20.5, 23.5);
      const x = Math.cos(a) * r, z = Math.sin(a) * r;
      if (Math.abs(x) < 4.5 && z < 0) continue;              // leave the road's far end open toward the mountains
      this._tree(x, z, { scale: rr(1.1, 1.7), simple: true, pink: rnd() < 0.2 });
    }
  }

  _vending(x, z, hex, rotY) {
    const g = new THREE.Group();
    g.add(box(1.0, 1.85, 0.75, hex, 0, 0.925, 0));
    const panel = new THREE.Mesh(new THREE.PlaneGeometry(0.72, 1.0), new THREE.MeshBasicMaterial({ color: 0xfff4cf }));
    panel.position.set(-0.08, 1.2, 0.376); g.add(panel);
    for (let r = 0; r < 3; r++) for (let c = 0; c < 4; c++) g.add(box(0.12, 0.2, 0.02, [0xd84a4a, 0x3d7bd6, 0xf3c13a, 0x58b86b][(r + c) % 4], -0.32 + c * 0.16, 1.55 - r * 0.3, 0.39, { cast: false }));
    g.add(box(0.26, 0.5, 0.02, 0x222228, 0.3, 0.9, 0.39, { cast: false }));         // coin / selection column
    g.add(box(0.6, 0.22, 0.04, 0x1a1a1e, -0.08, 0.35, 0.39, { cast: false }));       // dispense slot
    const light = new THREE.PointLight(0xfff0c2, 1.4, 4.0, 1.5); light.position.set(0, 1.2, 0.9); g.add(light);
    this.flicker.push(light);
    g.position.set(x, 0, z); g.rotation.y = rotY;
    this.scene.add(g);
  }

  _props() {
    this._vending(4.6, 6.8, 0xd3302f, -Math.PI / 2 - 0.1);
    this._vending(-4.7, -3.4, 0x2b73c9, Math.PI / 2 + 0.05);
    // sign post next to the red machine
    this.scene.add(box(0.08, 2.4, 0.08, 0x7d7f84, 4.6, 1.2, 8.0));
    this.scene.add(box(0.7, 0.7, 0.04, 0xf4f4f0, 4.6, 2.2, 8.0, { cast: false }));
    this.scene.add(box(0.56, 0.56, 0.05, 0x2d63c8, 4.6, 2.2, 8.0, { cast: false }));
    // utility poles + sagging wires
    const poleMat = lambert(0x6e6862);
    const wireMat = new THREE.LineBasicMaterial({ color: 0x24262b });
    const sides = [[-4.1, -23], [-4.1, -13], [-4.1, -3], [-4.1, 7], [-4.1, 17], [4.3, -18], [4.3, -8], [4.3, 2], [4.3, 12], [4.3, 22]];
    const tops = {};
    for (const [x, z] of sides) {
      const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.16, 7.6, 8), poleMat);
      pole.position.set(x, 3.8, z); pole.castShadow = true; this.scene.add(pole);
      this.scene.add(box(1.5, 0.1, 0.1, 0x5d5853, x, 7.0, z));
      this.scene.add(box(1.2, 0.08, 0.08, 0x5d5853, x, 6.5, z));
      (tops[x] = tops[x] || []).push(z);
    }
    for (const xs of Object.keys(tops)) {
      const x = Number(xs), zs = tops[xs].sort((a, b) => a - b);
      for (let i = 0; i + 1 < zs.length; i++) {
        for (const [dx, y] of [[-0.6, 7.06], [0.6, 7.06], [-0.45, 6.56], [0.45, 6.56]]) {
          const pts = [];
          for (let k = 0; k <= 14; k++) { const t = k / 14; pts.push(new THREE.Vector3(x + dx, y - 0.55 * 4 * t * (1 - t), zs[i] + (zs[i + 1] - zs[i]) * t)); }
          this.scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), wireMat));
        }
      }
    }
    // a bench and a mailbox near the right-hand houses
    this.scene.add(box(1.6, 0.08, 0.45, 0x8a6a4a, 7.6, 0.45, 9.2), box(0.08, 0.45, 0.4, 0x5a4a3a, 6.9, 0.22, 9.2), box(0.08, 0.45, 0.4, 0x5a4a3a, 8.3, 0.22, 9.2));
    this.scene.add(box(0.4, 1.1, 0.4, 0xd9382c, -7.6, 0.55, 10.5));
  }

  _petals() {
    const cv = document.createElement('canvas'); cv.width = 32; cv.height = 32;
    const ctx = cv.getContext('2d');
    ctx.fillStyle = '#ffd1e3'; ctx.beginPath(); ctx.ellipse(16, 16, 12, 7, 0.6, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#ffb0cf'; ctx.beginPath(); ctx.ellipse(13, 14, 5, 3, 0.6, 0, Math.PI * 2); ctx.fill();
    const tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace;
    const N = 650;
    const pos = new Float32Array(N * 3); this._petalVel = new Float32Array(N * 2);
    for (let i = 0; i < N; i++) {
      pos[i * 3] = rr(-11, 11); pos[i * 3 + 1] = rr(0, 8); pos[i * 3 + 2] = rr(-12, 9);
      this._petalVel[i * 2] = rr(0.35, 0.8); this._petalVel[i * 2 + 1] = rr(0, 6.28);
    }
    const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    const mat = new THREE.PointsMaterial({ map: tex, size: 0.085, transparent: true, depthWrite: false, alphaTest: 0.15, sizeAttenuation: true, color: 0xffffff });
    this.petals = new THREE.Points(geo, mat); this.petals.frustumCulled = false;
    this.scene.add(this.petals);
  }

  _collectHelpers() {
    // additive / transparent helpers (god-ray cones, floor glow, petals) must not write the DoF depth map
    this.scene.traverse((o) => {
      if (o.isPoints || (o.isMesh && o.material && (o.material.blending === THREE.AdditiveBlending))) this.hideForDepth.push(o);
    });
  }

  // ------------------------------------------------------------ post-processing
  _postprocessing() {
    try {
      const size = this.renderer.getSize(new THREE.Vector2());
      const composer = new EffectComposer(this.renderer);
      composer.setPixelRatio(this.renderer.getPixelRatio());
      composer.setSize(size.x, size.y);
      composer.addPass(new RenderPass(this.scene, this.camera));
      // subtle: ~1.5 m either side of her stays sharp, the far street only softens slightly
      this.bokeh = new SoftBokehPass(this.scene, this.camera, { focus: 2.6, aperture: 0.0009, maxblur: 0.0035 }, this.hideForDepth);
      composer.addPass(this.bokeh);
      composer.addPass(new OutputPass());
      this.composer = composer;
    } catch (e) {
      console.warn('[env] depth of field unavailable, rendering directly:', e);
      this.composer = null; this.bokeh = null;
    }
  }

  setSize(w, h) { this.composer?.setSize(w, h); }

  update(dt) {
    this.t += dt;
    const t = this.t;
    for (const s of this.sway) { s.mesh.rotation.z = Math.sin(t * 0.8 + s.phase) * s.amp; s.mesh.rotation.x = Math.cos(t * 0.6 + s.phase) * s.amp * 0.6; }
    if (this.water) this.water.offset.x -= dt * 0.035;
    this.flicker.forEach((l, i) => { l.intensity = 1.35 + Math.sin(t * 23 + i * 7) * 0.05 + (rnd() < 0.01 ? -0.3 : 0); });
    if (this.petals) {
      const p = this.petals.geometry.getAttribute('position'), v = this._petalVel;
      for (let i = 0; i < p.count; i++) {
        let y = p.getY(i) - v[i * 2] * dt;
        let x = p.getX(i) + Math.sin(t * 1.3 + v[i * 2 + 1]) * 0.35 * dt;
        let z = p.getZ(i) + Math.cos(t * 0.9 + v[i * 2 + 1]) * 0.25 * dt;
        if (y < 0.02) { y = rr(6, 8.5); x = rr(-11, 11); z = rr(-12, 9); }
        p.setXYZ(i, x, y, z);
      }
      p.needsUpdate = true;
    }
    if (this.bokeh) this.bokeh.uniforms.focus.value = this.camera.position.distanceTo(this.focusTarget || FOCUS_POINT);
  }

  render() {
    if (this.composer) {
      try { this.composer.render(); return; }
      catch (e) { console.warn('[env] composer failed, falling back:', e); this.composer = null; this.bokeh = null; }
    }
    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    this.composer?.dispose?.();
    this.composer = null;
  }
}
