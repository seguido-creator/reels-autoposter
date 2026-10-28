/* 16:9 long-form documentary renderer (props built by longform.py).
   Every scene is drawn here: painted illustrations with camera moves, AI-animated shots, 3D globe maps,
   step diagrams, real artifact photos or stock clips, plus mood effects (fog, embers, light rays, sand...),
   brand intro, chapter cards with a timeline, labels and end panel.
   Narration (one recording per scene, already joined) is voice.wav; scene start times match it exactly. */
import React, { useMemo } from "react";
import {
  AbsoluteFill, Audio, Img, OffthreadVideo, Sequence, staticFile, useCurrentFrame, useVideoConfig,
  interpolate, spring, Easing,
} from "remotion";
import { geoOrthographic, geoPath, geoGraticule10, geoInterpolate, geoDistance } from "d3-geo";
import { feature } from "topojson-client";
import land50 from "world-atlas/land-50m.json";

export type DocTheme = {
  accent: string; onAccent: string; bg: string; ink: string; text: string; muted: string; land: string; sea: string;
  titleFont: string; bodyFont: string;
};
export type MapSpec = {
  place: string; lat: number; lon: number; era?: string;
  fromPlace?: string | null; fromLat?: number | null; fromLon?: number | null;
};
export type Fx = "dust" | "fog" | "smoke" | "embers" | "rays" | "sand" | "rain" | "water" | "none";
export type DocScene = {
  start: number; dur: number; kind: "illustration" | "artifact" | "clip" | "motion" | "map" | "steps" | "card";
  img?: string; clip?: string; motion?: number; label?: string; map?: MapSpec; fx?: Fx;
  stepsTitle?: string; steps?: string[]; title?: string;
};
export type DocChapter = { start: number; dur: number; n: number; title: string; era?: string; year?: number };
export type DocProps = {
  total: number; audio: string; brand: string; monogram: string; title: string; theme: DocTheme;
  scenes: DocScene[]; chapters: DocChapter[]; intro: { start: number; dur: number };
  yearMin: number; yearMax: number; endStart: number; endText: string;
};

export const docDefaults: DocProps = {
  total: 10, audio: "voice.wav", brand: "History Decoded", monogram: "HD", title: "Title",
  theme: { accent: "#C8923A", onAccent: "#14110D", bg: "#0F1418", ink: "#0B0F12", text: "#F3EADB", muted: "#C9BBA3",
    land: "#C9B48C", sea: "#16222B", titleFont: "title.ttf", bodyFont: "body.ttf" },
  scenes: [], chapters: [], intro: { start: 0, dur: 0 }, yearMin: -3000, yearMax: 2000, endStart: 8, endText: "Subscribe",
};

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const rnd = (seed: number, i: number, k: number) => {
  const x = Math.sin(seed * 97.1 + i * 13.7 + k * 7.3) * 43758.5453;
  return x - Math.floor(x);
};

/* ---------- atmosphere: vignette ---------- */
const Grade: React.FC = () => (
  <AbsoluteFill style={{ pointerEvents: "none",
    background: "radial-gradient(ellipse at center, rgba(0,0,0,0) 55%, rgba(0,0,0,.55) 100%)" }} />
);

/* ---------- mood effects: always something moving on screen ---------- */
const Particles: React.FC<{ seed: number; n: number; color: string; size: [number, number]; vx: [number, number];
  vy: [number, number]; op: [number, number]; blur?: number; flicker?: boolean; streak?: number }> =
  ({ seed, n, color, size, vx, vy, op, blur = 0.6, flicker, streak }) => {
    const f = useCurrentFrame();
    const pts = useMemo(() => Array.from({ length: n }, (_, i) => ({
      x: rnd(seed, i, 1) * 2100 - 90, y: rnd(seed, i, 2) * 1260 - 90,
      s: size[0] + rnd(seed, i, 3) * (size[1] - size[0]),
      vx: vx[0] + rnd(seed, i, 4) * (vx[1] - vx[0]), vy: vy[0] + rnd(seed, i, 5) * (vy[1] - vy[0]),
      o: op[0] + rnd(seed, i, 6) * (op[1] - op[0]), ph: rnd(seed, i, 7) * 6.28,
    })), [seed, n]);
    const wrap = (v: number, m: number) => ((v % m) + m) % m;
    return (
      <AbsoluteFill style={{ pointerEvents: "none" }}>
        {pts.map((d, i) => {
          const x = wrap(d.x + f * d.vx, 2100) - 90;
          const y = wrap(d.y + f * d.vy, 1260) - 90;
          const o = d.o * (flicker ? 0.55 + 0.45 * Math.sin(f * 0.25 + d.ph) : 1);
          return <div key={i} style={{ position: "absolute", left: x, top: y,
            width: streak ? d.s * streak : d.s, height: d.s, borderRadius: streak ? d.s : "50%", background: color,
            opacity: o, filter: `blur(${blur}px)`, boxShadow: flicker ? `0 0 ${d.s * 3}px ${color}` : undefined,
            transform: streak ? `rotate(${Math.atan2(d.vy, d.vx) * 57.3}deg)` : undefined }} />;
        })}
      </AbsoluteFill>
    );
  };

const Haze: React.FC<{ seed: number; color: string; op: number; speed: number; top?: number }> = ({ seed, color, op, speed, top = 0 }) => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{ pointerEvents: "none", mixBlendMode: "screen" }}>
      {[0, 1, 2, 3].map((i) => {
        const w = 900 + rnd(seed, i, 1) * 700;
        const x = ((rnd(seed, i, 2) * 2400 + f * speed * (0.6 + rnd(seed, i, 3))) % 2900) - 900;
        const y = top + rnd(seed, i, 4) * (1080 - top) - 250;
        return <div key={i} style={{ position: "absolute", left: x, top: y, width: w, height: w * 0.45,
          borderRadius: "50%", background: `radial-gradient(ellipse at center, ${color} 0%, rgba(0,0,0,0) 70%)`,
          opacity: op * (0.7 + 0.3 * Math.sin(f / 40 + i)), filter: "blur(30px)" }} />;
      })}
    </AbsoluteFill>
  );
};

const Rays: React.FC<{ seed: number }> = ({ seed }) => {
  const f = useCurrentFrame();
  const sway = Math.sin(f / 70 + seed) * 3;
  const pulse = 0.26 + 0.1 * Math.sin(f / 35 + seed);
  return (
    <AbsoluteFill style={{ pointerEvents: "none", mixBlendMode: "screen", opacity: pulse }}>
      <div style={{ position: "absolute", left: -400, top: -700, width: 2200, height: 2200,
        transform: `rotate(${18 + sway}deg)`, transformOrigin: "30% 30%",
        background: "repeating-conic-gradient(from 100deg at 20% 20%, rgba(255,226,170,.55) 0deg 3deg, rgba(0,0,0,0) 3deg 9deg)",
        maskImage: "radial-gradient(circle at 25% 25%, #000 0%, rgba(0,0,0,0) 60%)",
        WebkitMaskImage: "radial-gradient(circle at 25% 25%, #000 0%, rgba(0,0,0,0) 60%)", filter: "blur(10px)" }} />
    </AbsoluteFill>
  );
};

const Water: React.FC<{ seed: number }> = ({ seed }) => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{ pointerEvents: "none", mixBlendMode: "screen", opacity: 0.22 }}>
      {[0, 1, 2].map((i) => (
        <div key={i} style={{ position: "absolute", left: 0, right: 0, top: 560 + i * 120, height: 200,
          background: `repeating-linear-gradient(${172 + i * 4}deg, rgba(255,255,255,0) 0px, rgba(255,250,235,.5) ${3 + i}px, rgba(255,255,255,0) ${9 + i * 2}px, rgba(255,255,255,0) ${40 + i * 10}px)`,
          backgroundPosition: `${(f * (1.4 + i * 0.5) + seed * 30) % 400}px 0`, filter: "blur(2px)",
          maskImage: "linear-gradient(180deg, rgba(0,0,0,0), #000 40%, rgba(0,0,0,0))",
          WebkitMaskImage: "linear-gradient(180deg, rgba(0,0,0,0), #000 40%, rgba(0,0,0,0))" }} />
      ))}
    </AbsoluteFill>
  );
};

const MoodFx: React.FC<{ fx?: Fx; seed: number }> = ({ fx = "dust", seed }) => {
  switch (fx) {
    case "none": return null;
    case "fog": return <><Haze seed={seed} color="rgba(235,230,220,.9)" op={0.32} speed={0.9} top={300} />
      <Particles seed={seed} n={14} color="rgba(255,240,210,1)" size={[1.5, 3]} vx={[0.1, 0.4]} vy={[-0.2, 0]} op={[0.1, 0.3]} /></>;
    case "smoke": return <Haze seed={seed} color="rgba(150,140,130,.9)" op={0.38} speed={1.4} />;
    case "embers": return <><Particles seed={seed} n={44} color="rgba(255,150,50,1)" size={[3, 7]} vx={[-0.4, 0.6]}
      vy={[-2.4, -0.8]} op={[0.4, 0.95]} blur={0.8} flicker /><Haze seed={seed} color="rgba(255,120,40,.7)" op={0.12} speed={0.5} top={500} /></>;
    case "rays": return <><Rays seed={seed} /><Particles seed={seed} n={30} color="rgba(255,236,190,1)" size={[1.5, 3.5]}
      vx={[0.1, 0.5]} vy={[-0.4, 0.2]} op={[0.2, 0.6]} /></>;
    case "sand": return <><Particles seed={seed} n={70} color="rgba(232,200,150,1)" size={[1.5, 3]} vx={[6, 11]} vy={[0.4, 1.4]}
      op={[0.25, 0.6]} streak={5} blur={1} /><Haze seed={seed} color="rgba(220,180,120,.9)" op={0.2} speed={4} top={400} /></>;
    case "rain": return <Particles seed={seed} n={90} color="rgba(210,225,240,1)" size={[1.5, 2.5]} vx={[2, 3]} vy={[22, 30]}
      op={[0.2, 0.45]} streak={14} blur={0.5} />;
    case "water": return <><Water seed={seed} /><Particles seed={seed} n={18} color="rgba(255,240,210,1)" size={[1.5, 3]}
      vx={[0.1, 0.4]} vy={[-0.3, 0]} op={[0.15, 0.35]} /></>;
    default: return <Particles seed={seed} n={30} color="rgba(255,240,210,1)" size={[1.5, 4.5]} vx={[0.15, 0.5]}
      vy={[-0.3, 0.05]} op={[0.15, 0.5]} />;
  }
};

/* ---------- painted illustration / artifact with camera move ---------- */
const MOVES = [
  { s0: 1.0, s1: 1.22, x0: 0, x1: 0, y0: 0, y1: -1, r0: 0, r1: 0.6 },
  { s0: 1.24, s1: 1.04, x0: 0, x1: 0, y0: 1, y1: 0, r0: -0.5, r1: 0 },
  { s0: 1.16, s1: 1.2, x0: -6, x1: 5, y0: 0, y1: 0, r0: 0, r1: 0 },
  { s0: 1.16, s1: 1.2, x0: 6, x1: -5, y0: 0, y1: 0, r0: 0, r1: 0 },
  { s0: 1.06, s1: 1.26, x0: 3, x1: -4, y0: 3, y1: -3, r0: 0.4, r1: -0.4 },
  { s0: 1.24, s1: 1.08, x0: -4, x1: 3, y0: -3, y1: 3, r0: -0.4, r1: 0.4 },
];

const Painting: React.FC<{ sc: DocScene; frames: number; artifact?: boolean }> = ({ sc, frames, artifact }) => {
  const f = useCurrentFrame();
  const m = MOVES[(sc.motion ?? 0) % MOVES.length];
  const t = interpolate(f, [0, frames], [0, 1], { ...clamp, easing: Easing.inOut(Easing.sin) });
  const s = m.s0 + (m.s1 - m.s0) * t;
  const x = m.x0 + (m.x1 - m.x0) * t;
  const y = m.y0 + (m.y1 - m.y0) * t;
  const r = m.r0 + (m.r1 - m.r0) * t;
  const fade = interpolate(f, [0, 10], [0, 1], clamp);
  if (artifact) {
    // real photo: whole object visible over a blurred copy of itself
    return (
      <AbsoluteFill style={{ opacity: fade }}>
        <Img src={staticFile(sc.img!)} style={{ position: "absolute", inset: 0, width: "100%", height: "100%",
          objectFit: "cover", filter: "blur(28px) brightness(.45)", transform: `scale(${1.15 + 0.08 * t})` }} />
        <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
          <Img src={staticFile(sc.img!)} style={{ maxWidth: "78%", maxHeight: "82%", objectFit: "contain",
            transform: `scale(${0.94 + 0.1 * t}) rotate(${(t - 0.5) * 1.2}deg)`, boxShadow: "0 30px 80px rgba(0,0,0,.6)" }} />
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill style={{ overflow: "hidden", opacity: fade }}>
      <Img src={staticFile(sc.img!)} style={{ width: "100%", height: "100%", objectFit: "cover",
        transform: `scale(${s}) translate(${x}%, ${y}%) rotate(${r}deg)` }} />
    </AbsoluteFill>
  );
};

/* AI-animated shot (already cut to the scene length by longform.py) with a gentle push-in on top */
const MotionShot: React.FC<{ sc: DocScene; frames: number }> = ({ sc, frames }) => {
  const f = useCurrentFrame();
  const s = interpolate(f, [0, frames], [1.0, 1.07], clamp);
  const fade = interpolate(f, [0, 8], [0, 1], clamp);
  return (
    <AbsoluteFill style={{ overflow: "hidden", opacity: fade }}>
      <OffthreadVideo src={staticFile(sc.clip!)} muted style={{ width: "100%", height: "100%", objectFit: "cover",
        transform: `scale(${s})` }} />
    </AbsoluteFill>
  );
};

/* ---------- 3D map: the globe spins to the place, then tilts into a 3D landscape view ---------- */
const LAND = feature(land50 as any, (land50 as any).objects.land) as any;
const GRAT = geoGraticule10();
const SPHERE = { type: "Sphere" } as any;
const PW = 3400, PH = 2700;  // map plane, larger than the screen so the tilt never shows its edges
const PERSP = 1300, PO_Y = 200;
/* where a point of the tilted map plane lands on screen (same maths as the CSS 3D transform), plus its depth scale */
const toScreen = (px: number, py: number, tiltDeg: number, rzDeg: number, sc: number): [number, number, number] => {
  const ox = PW / 2, oy = PH * 0.5, L = (1920 - PW) / 2, T = (1080 - PH) / 2;
  let x = (px - ox) * sc, y = (py - oy) * sc;
  const r = (rzDeg * Math.PI) / 180, a = (tiltDeg * Math.PI) / 180;
  [x, y] = [x * Math.cos(r) - y * Math.sin(r), x * Math.sin(r) + y * Math.cos(r)];
  const z = y * Math.sin(a);
  y = y * Math.cos(a);
  const X = L + ox + x, Y = T + oy + y, k = PERSP / (PERSP - z);
  return [960 + (X - 960) * k, PO_Y + (Y - PO_Y) * k, k];
};

const Clouds: React.FC<{ seed: number; rush: number; settle: number }> = ({ seed, rush, settle }) => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {Array.from({ length: 7 }, (_, i) => {
        const bx = rnd(seed, i, 1) * 1920, by = rnd(seed, i, 2) * 1080;
        const dx = bx - 960, dy = by - 540;
        const grow = 1 + rush * 2.2;  // clouds fly past the camera while it dives in
        const x = 960 + dx * grow + f * (0.6 + rnd(seed, i, 3));
        const y = 540 + dy * grow;
        const w = (420 + rnd(seed, i, 4) * 520) * (1 + rush * 1.5);
        return <div key={i} style={{ position: "absolute", left: x - w / 2, top: y - w * 0.22, width: w, height: w * 0.44,
          borderRadius: "50%", background: "radial-gradient(ellipse at center, rgba(255,255,255,.95) 0%, rgba(255,255,255,0) 68%)",
          opacity: (0.42 * (1 - rush) * (1 - settle) + 0.16 * settle) * (rush > 0.95 ? 0 : 1), filter: "blur(18px)" }} />;
      })}
    </AbsoluteFill>
  );
};

const MapScene: React.FC<{ sc: DocScene; t: DocTheme; frames: number; i: number }> = ({ sc, t, frames, i }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const mp = sc.map!;
  const to: [number, number] = [mp.lon, mp.lat];
  const from: [number, number] | null = mp.fromLon != null && mp.fromLat != null ? [mp.fromLon, mp.fromLat] : null;
  const d = from ? geoDistance(from, to) : 0;
  const endCenter = from && d > 0.01 ? geoInterpolate(from, to)(0.62) : to;
  const startCenter: [number, number] = [endCenter[0] + 95, Math.max(-35, Math.min(35, endCenter[1] * 0.4))];
  const fly = Math.max(30, Math.min(95, Math.round(frames * 0.5)));
  const k = interpolate(f, [0, fly], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const center = geoInterpolate(startCenter, endCenter)(k);
  const endScale = from && d > 0.01 ? Math.max(1500, Math.min(5200, 900 / d)) : 3600;
  const scale = 420 * Math.pow(endScale / 420, k);
  const proj = geoOrthographic().scale(scale).rotate([-center[0], -center[1]]).translate([PW / 2, PH * 0.5 + 40]).clipAngle(90);
  const path = geoPath(proj);
  const pin = proj(to) || [PW / 2, PH / 2];
  const fromPt = from ? proj(from) : null;
  const tiltK = interpolate(f, [fly * 0.7, fly * 0.7 + 50], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const tilt = 56 * tiltK;
  const drift = interpolate(f, [0, frames], [0, 1], clamp);
  const rz = (drift - 0.5) * 5 * tiltK;
  const ps = 1 + 0.08 * drift;
  const route = from ? interpolate(f, [fly * 0.55, fly * 0.55 + 55], [0, 1], { ...clamp, easing: Easing.inOut(Easing.quad) }) : 0;
  const traveler = from && route > 0 && route < 1 ? proj(geoInterpolate(from, to)(route)) : null;
  const pulse = (f % 40) / 40;
  const standIn = interpolate(f, [fly * 0.8, fly * 0.8 + 22], [0, 1], clamp);
  const beam = 230 * Easing.out(Easing.cubic)(standIn);
  const era = mp.era || "";
  const routeLine = from ? { type: "LineString", coordinates: [from, to] } as any : null;
  const space = interpolate(tiltK, [0, 1], [1, 0]);
  return (
    <AbsoluteFill style={{ background: `radial-gradient(circle at 50% 40%, #1a2733 0%, #05080b 75%)`, overflow: "hidden" }}>
      {/* stars while we are in space */}
      <AbsoluteFill style={{ opacity: space * (1 - k * 0.8) }}>
        {Array.from({ length: 70 }, (_, s) => <div key={s} style={{ position: "absolute", left: rnd(i, s, 1) * 1920,
          top: rnd(i, s, 2) * 1080, width: 2, height: 2, borderRadius: 1, background: "#fff",
          opacity: 0.3 + 0.5 * Math.abs(Math.sin(f / 20 + s)) }} />)}
      </AbsoluteFill>
      {/* sky haze on the horizon once the map tilts */}
      <AbsoluteFill style={{ opacity: tiltK, background: `linear-gradient(180deg, ${t.muted}55 0%, ${t.sea} 38%, ${t.sea} 100%)` }} />
      <AbsoluteFill style={{ perspective: PERSP, perspectiveOrigin: `960px ${PO_Y}px` }}>
        <div style={{ position: "absolute", left: (1920 - PW) / 2, top: (1080 - PH) / 2, width: PW, height: PH,
          transformOrigin: `${PW / 2}px ${PH * 0.5}px`,
          transform: `rotateX(${tilt}deg) rotateZ(${rz}deg) scale(${ps})` }}>
          <svg width={PW} height={PH} style={{ position: "absolute", left: 0, top: 0 }}>
            <defs>
              <radialGradient id={`sea${i}`} cx="45%" cy="40%" r="70%">
                <stop offset="0%" stopColor={t.sea} stopOpacity={1} />
                <stop offset="100%" stopColor="#070b0e" stopOpacity={1} />
              </radialGradient>
              <linearGradient id={`land${i}`} x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor={t.land} />
                <stop offset="100%" stopColor="#8f7a52" />
              </linearGradient>
              <filter id={`glow${i}`} x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="9" /></filter>
            </defs>
            <path d={path(SPHERE) || ""} fill={`url(#sea${i})`} stroke="#9fd0ff" strokeOpacity={0.35 * space} strokeWidth={6} />
            <path d={path(GRAT) || ""} fill="none" stroke={t.muted} strokeOpacity={0.14} strokeWidth={1.2} />
            <path d={path(LAND) || ""} fill={t.accent} opacity={0.25} filter={`url(#glow${i})`} />
            <path d={path(LAND) || ""} fill="#4a3c26" transform={`translate(0, ${4 + 12 * tiltK})`} />
            <path d={path(LAND) || ""} fill={`url(#land${i})`} stroke={t.ink} strokeOpacity={0.4} strokeWidth={1.4} />
            {routeLine && route > 0 && <>
              <path d={path(routeLine) || ""} fill="none" stroke={t.accent} strokeWidth={14} opacity={0.35}
                filter={`url(#glow${i})`} pathLength={1} strokeDasharray={`${route} 1`} />
              <path d={path(routeLine) || ""} fill="none" stroke={t.accent} strokeWidth={6} pathLength={1}
                strokeDasharray={`${route} 1`} strokeLinecap="round" />
            </>}
            {traveler && <circle cx={traveler[0]} cy={traveler[1]} r={13} fill={t.text} stroke={t.accent} strokeWidth={5} />}
            {fromPt && <>
              <circle cx={fromPt[0]} cy={fromPt[1]} r={11} fill={t.text} opacity={0.9} />
              {mp.fromPlace && <text x={fromPt[0] + 22} y={fromPt[1] + 12} fontFamily="Body" fontSize={40} fill={t.text}
                stroke="#000" strokeWidth={6} paintOrder="stroke" opacity={route > 0 ? 1 : 0}>{mp.fromPlace}</text>}
            </>}
            <circle cx={pin[0]} cy={pin[1]} r={30} fill={t.accent} opacity={0.6} filter={`url(#glow${i})`} />
            <circle cx={pin[0]} cy={pin[1]} r={16 + pulse * 70} fill="none" stroke={t.accent} strokeWidth={5} opacity={(1 - pulse) * standIn} />
            <circle cx={pin[0]} cy={pin[1]} r={15} fill={t.accent} stroke={t.ink} strokeWidth={4} />
          </svg>
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={{ opacity: tiltK, background: `linear-gradient(180deg, ${t.sea} 0%, ${t.sea}cc 12%, ${t.sea}00 34%)` }} />
      <Clouds seed={i + 3} rush={Math.min(1, k * 1.15)} settle={tiltK} />
      {/* upright marker: a light beam standing on the map with the place and era on top */}
      {(() => {
        const sp = toScreen(pin[0], pin[1], tilt, rz, ps);
        const z = sp[2];
        return (
          <div style={{ position: "absolute", left: sp[0], top: sp[1], opacity: standIn }}>
            <div style={{ position: "absolute", left: -4 * z, top: -beam * z, width: 8 * z, height: beam * z,
              background: `linear-gradient(0deg, ${t.accent}, ${t.accent}00)`, boxShadow: `0 0 24px ${t.accent}` }} />
            <div style={{ position: "absolute", left: 0, top: -beam * z - 16, transform: `translate(-50%, -100%) scale(${0.9 + 0.1 * standIn})`,
              transformOrigin: "50% 100%", whiteSpace: "nowrap", textAlign: "center", background: "rgba(10,8,6,.84)",
              borderTop: `6px solid ${t.accent}`, padding: "16px 34px 18px", boxShadow: "0 20px 50px rgba(0,0,0,.5)" }}>
              <div style={{ fontFamily: "Title", fontSize: 62, color: t.text, lineHeight: 1.05 }}>{mp.place.toUpperCase()}</div>
              {era && <div style={{ fontFamily: "Body", fontSize: 38, color: t.accent, marginTop: 6, letterSpacing: 3 }}>{era}</div>}
            </div>
          </div>
        );
      })()}
      {/* era stamp from the first frame */}
      {era && (
        <div style={{ position: "absolute", left: 90, top: 70, display: "flex",
          opacity: interpolate(f, [4, 16, frames - 10, frames], [0, 1, 1, 0], clamp) }}>
          <div style={{ width: 8, background: t.accent }} />
          <div style={{ background: "rgba(10,8,6,.74)", padding: "12px 24px" }}>
            <div style={{ fontFamily: "Body", fontSize: 24, letterSpacing: 6, color: t.muted }}>THE WORLD IN</div>
            <div style={{ fontFamily: "Title", fontSize: 50, color: t.text }}>{era}</div>
          </div>
        </div>
      )}
      <Grade />
    </AbsoluteFill>
  );
};

/* ---------- step diagram over the painting ---------- */
const StepsScene: React.FC<{ sc: DocScene; t: DocTheme; frames: number }> = ({ sc, t, frames }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const steps = sc.steps || [];
  const per = Math.max(12, Math.floor((frames - 20) / Math.max(steps.length, 1)));
  return (
    <AbsoluteFill>
      {sc.img ? <Painting sc={{ ...sc, motion: 0 }} frames={frames} /> : <AbsoluteFill style={{ background: t.bg }} />}
      <AbsoluteFill style={{ background: "linear-gradient(90deg, rgba(10,8,6,.88) 0%, rgba(10,8,6,.72) 48%, rgba(10,8,6,0) 75%)" }} />
      <div style={{ position: "absolute", left: 110, top: 150, width: 980 }}>
        <div style={{ fontFamily: "Body", fontSize: 30, letterSpacing: 6, color: t.accent }}>HOW IT WORKED</div>
        <div style={{ fontFamily: "Title", fontSize: 66, color: t.text, lineHeight: 1.08, margin: "14px 0 46px" }}>{sc.stepsTitle}</div>
        {steps.map((s, i) => {
          const k = spring({ frame: f - 14 - i * per, fps, config: { damping: 15, stiffness: 120 } });
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 28, marginBottom: 30, opacity: k,
              transform: `translateX(${(1 - k) * -50}px)` }}>
              <div style={{ width: 76, height: 76, borderRadius: "50%", background: t.accent, color: t.onAccent,
                fontFamily: "Title", fontSize: 44, display: "flex", alignItems: "center", justifyContent: "center",
                flexShrink: 0 }}>{i + 1}</div>
              <div style={{ fontFamily: "Body", fontSize: 44, color: t.text, lineHeight: 1.15 }}>{s}</div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const CardScene: React.FC<{ sc: DocScene; t: DocTheme }> = ({ sc, t }) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [0, 15], [0, 1], clamp);
  return (
    <AbsoluteFill style={{ background: `radial-gradient(circle at 50% 45%, ${t.sea} 0%, ${t.bg} 70%)`,
      justifyContent: "center", alignItems: "center" }}>
      <div style={{ fontFamily: "Title", fontSize: 76, color: t.text, opacity: o, maxWidth: 1400, textAlign: "center",
        lineHeight: 1.12, transform: `scale(${1 + f * 0.0006})` }}>{sc.title}</div>
    </AbsoluteFill>
  );
};

const Label: React.FC<{ text: string; t: DocTheme; frames: number }> = ({ text, t, frames }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: f - 8, fps, config: { damping: 18, stiffness: 140 } });
  const out = interpolate(f, [frames - 10, frames], [1, 0], clamp);
  return (
    <div style={{ position: "absolute", left: 90, top: 70, display: "flex", opacity: Math.min(s, out),
      transform: `translateX(${(1 - s) * -40}px)` }}>
      <div style={{ width: 8, background: t.accent }} />
      <div style={{ background: "rgba(10,8,6,.74)", color: t.text, fontFamily: "Body", fontSize: 36,
        padding: "12px 24px" }}>{text}</div>
    </div>
  );
};

const SceneView: React.FC<{ sc: DocScene; t: DocTheme; frames: number; i: number }> = ({ sc, t, frames, i }) => {
  let body: React.ReactNode;
  if (sc.kind === "map" && sc.map) body = <MapScene sc={sc} t={t} frames={frames} i={i} />;
  else if (sc.kind === "steps") body = <StepsScene sc={sc} t={t} frames={frames} />;
  else if ((sc.kind === "clip" || sc.kind === "motion") && sc.clip) body = <MotionShot sc={sc} frames={frames} />;
  else if ((sc.kind === "illustration" || sc.kind === "artifact") && sc.img)
    body = <Painting sc={sc} frames={frames} artifact={sc.kind === "artifact"} />;
  else body = <CardScene sc={sc} t={t} />;
  const fx: Fx = sc.kind === "artifact" ? "dust" : (sc.fx || "dust");
  return (
    <AbsoluteFill>
      {body}
      {sc.kind !== "map" && <><MoodFx fx={sc.kind === "steps" ? "dust" : fx} seed={i + 1} /><Grade /></>}
      {sc.label && sc.kind !== "map" && <Label text={sc.label} t={t} frames={frames} />}
    </AbsoluteFill>
  );
};

/* ---------- brand pieces ---------- */
const Monogram: React.FC<{ t: DocTheme; text: string; size: number }> = ({ t, text, size }) => (
  <div style={{ width: size, height: size, borderRadius: "50%", border: `${size * 0.05}px solid ${t.accent}`,
    display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "Title", fontSize: size * 0.4,
    color: t.text, background: "rgba(0,0,0,.35)" }}>{text}</div>
);

const Intro: React.FC<{ p: DocProps; frames: number }> = ({ p, frames }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = p.theme;
  const s = spring({ frame: f, fps, config: { damping: 14, stiffness: 110 } });
  const line = interpolate(f, [6, 34], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  const out = interpolate(f, [frames - 10, frames], [1, 0], clamp);
  return (
    <AbsoluteFill style={{ background: t.bg, justifyContent: "center", alignItems: "center", opacity: out }}>
      <MoodFx fx="embers" seed={7} />
      <div style={{ transform: `scale(${0.85 + 0.15 * s})`, opacity: s }}><Monogram t={t} text={p.monogram} size={170} /></div>
      <div style={{ height: 3, width: 760 * line, background: t.accent, margin: "34px 0 26px" }} />
      <div style={{ fontFamily: "Title", fontSize: 64, letterSpacing: 6, color: t.text, opacity: line }}>{p.brand.toUpperCase()}</div>
    </AbsoluteFill>
  );
};

const ChapterCard: React.FC<{ c: DocChapter; p: DocProps; frames: number }> = ({ c, p, frames }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = p.theme;
  const s = spring({ frame: f, fps, config: { damping: 16, stiffness: 120 } });
  const out = interpolate(f, [frames - 8, frames], [1, 0], clamp);
  const span = Math.max(1, p.yearMax - p.yearMin);
  const pos = (y?: number) => (y == null ? null : (y - p.yearMin) / span);
  const here = pos(c.year);
  const moving = interpolate(f, [0, 30], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  return (
    <AbsoluteFill style={{ background: t.bg, opacity: out, justifyContent: "center", alignItems: "center" }}>
      <MoodFx fx="dust" seed={c.n + 20} />
      <div style={{ textAlign: "center", opacity: s, transform: `translateY(${(1 - s) * 30}px) scale(${1 + f * 0.0008})` }}>
        <div style={{ fontFamily: "Body", fontSize: 32, letterSpacing: 10, color: t.accent }}>
          CHAPTER {c.n}{c.era ? `  ·  ${c.era.toUpperCase()}` : ""}</div>
        <div style={{ fontFamily: "Title", fontSize: 96, color: t.text, maxWidth: 1500, lineHeight: 1.08, marginTop: 22,
          padding: "0 110px" }}>{c.title}</div>
      </div>
      {here != null && (
        <div style={{ position: "absolute", left: 260, right: 260, bottom: 170, height: 4, background: `${t.muted}44` }}>
          {p.chapters.filter((x) => x.year != null).map((x, i) => (
            <div key={i} style={{ position: "absolute", left: `${(pos(x.year) as number) * 100}%`, top: -7, width: 18, height: 18,
              marginLeft: -9, borderRadius: "50%", background: x.n === c.n ? t.accent : t.muted, opacity: x.n === c.n ? 1 : 0.45 }} />
          ))}
          <div style={{ position: "absolute", left: 0, width: `${here * 100 * moving}%`, height: 4, background: t.accent }} />
        </div>
      )}
    </AbsoluteFill>
  );
};

const Opening: React.FC<{ p: DocProps; frames: number }> = ({ p, frames }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: f - 8, fps, config: { damping: 16, stiffness: 110 } });
  const out = interpolate(f, [frames - 15, frames], [1, 0], clamp);
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", padding: "0 110px 120px", opacity: out,
      background: "linear-gradient(0deg, rgba(0,0,0,.65) 0%, rgba(0,0,0,0) 45%)" }}>
      <div style={{ fontFamily: "Title", fontSize: 74, color: p.theme.text, maxWidth: 1450, lineHeight: 1.08, opacity: s,
        transform: `translateY(${(1 - s) * 30}px)`, textShadow: "0 6px 30px rgba(0,0,0,.8)" }}>{p.title}</div>
    </AbsoluteFill>
  );
};

const EndPanel: React.FC<{ p: DocProps }> = ({ p }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: f, fps, config: { damping: 18, stiffness: 100 } });
  return (
    <AbsoluteFill style={{ background: p.theme.bg, opacity: s }}>
      <MoodFx fx="dust" seed={99} />
      <div style={{ position: "absolute", right: 120, top: 0, bottom: 0, width: 720, display: "flex",
        flexDirection: "column", justifyContent: "center", gap: 26 }}>
        <Monogram t={p.theme} text={p.monogram} size={120} />
        <div style={{ fontFamily: "Title", fontSize: 66, color: p.theme.text, lineHeight: 1.1 }}>{p.endText}</div>
        <div style={{ height: 4, width: 160, background: p.theme.accent }} />
      </div>
    </AbsoluteFill>
  );
};

export const Doc: React.FC<DocProps> = (p) => {
  const { fps } = useVideoConfig();
  const fr = (s: number) => Math.max(0, Math.round(s * fps));
  const css = `@font-face{font-family:Title;src:url(${staticFile(p.theme.titleFont)});}
@font-face{font-family:Body;src:url(${staticFile(p.theme.bodyFont)});}`;
  const firstLen = p.scenes.length ? p.scenes[0].dur : 4;
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <style>{css}</style>
      {p.scenes.map((sc, i) => (
        <Sequence key={`s${i}`} from={fr(sc.start)} durationInFrames={Math.max(1, fr(sc.dur) + 1)}>
          <SceneView sc={sc} t={p.theme} frames={Math.max(1, fr(sc.dur))} i={i} />
        </Sequence>
      ))}
      <Sequence from={fr(0.3)} durationInFrames={fr(Math.min(6, firstLen))}><Opening p={p} frames={fr(Math.min(6, firstLen))} /></Sequence>
      {p.intro.dur > 0 && (
        <Sequence from={fr(p.intro.start)} durationInFrames={fr(p.intro.dur)}><Intro p={p} frames={fr(p.intro.dur)} /></Sequence>
      )}
      {p.chapters.map((c, i) => (
        <Sequence key={`c${i}`} from={fr(c.start)} durationInFrames={Math.max(1, fr(c.dur))}>
          <ChapterCard c={c} p={p} frames={Math.max(1, fr(c.dur))} />
        </Sequence>
      ))}
      <div style={{ position: "absolute", right: 56, top: 42, opacity: 0.7, transform: "scale(.9)" }}>
        <Monogram t={p.theme} text={p.monogram} size={64} />
      </div>
      <Sequence from={fr(p.endStart)}><EndPanel p={p} /></Sequence>
      <Audio src={staticFile(p.audio)} />
    </AbsoluteFill>
  );
};
