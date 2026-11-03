/* "Case file" look for history Reels (History Decoded, Chika ng Kasaysayan).
   Someone leaning in to tell you something most people never learned:
   aged-paper case card with a red stamp and a typewriter hook (readable from frame 0), film grain + vignette,
   sentence captions (2 lines max, safe zone, dates/names in the accent colour), an animated map pin/route when a
   place matters, the timeline with a highlight line joining the two overlapping events, soft whoosh / paper /
   stamp sounds and a low ambient bed. Fonts: one serif (Title) + one clean sans (Caption). */
import React from "react";
import {
  AbsoluteFill, Audio, Sequence, staticFile, useCurrentFrame, useVideoConfig, interpolate, spring, Easing,
} from "remotion";
import { geoOrthographic, geoPath, geoGraticule10, geoInterpolate, geoDistance } from "d3-geo";
import { feature } from "topojson-client";
import land110 from "world-atlas/land-110m.json";

export type CFTheme = {
  accent: string; paper: string; paperDark: string; ink: string; stamp: string; text: string; shade: string;
};
export type CFWord = { w: string; t: number };
export type CFScene = { start: number; end: number; key?: string; map?: CFMap | null };
export type CFMap = { place: string; lat: number; lon: number; fromPlace?: string; fromLat?: number; fromLon?: number };
export type CFTime = { year: string; label: string; pair?: boolean };
export type CaseFileProps = {
  total: number; lead: number; hook: string; brand: string; words: CFWord[]; scenes: CFScene[];
  timeline: CFTime[]; highlights: string[]; theme: CFTheme; stamp: string; fileLabel: string;
  outro: string; monogram: string; sfx: boolean; music: string | null;
};

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
const norm = (s: string) => s.toLowerCase().normalize("NFKD").replace(/[^\p{L}\p{N}]/gu, "");

/* ---------- film grain + vignette + warm grade over the footage ---------- */
export const Atmosphere: React.FC<{ t: CFTheme }> = ({ t }) => {
  const f = useCurrentFrame();
  const sx = (f * 37) % 200, sy = (f * 53) % 200;
  return (
    <>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 45%, rgba(0,0,0,.62) 100%)" }} />
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(0,0,0,.42) 0%, rgba(0,0,0,0) 22%, rgba(0,0,0,0) 58%, rgba(0,0,0,.55) 100%)" }} />
      <AbsoluteFill style={{ opacity: 0.16, mixBlendMode: "overlay", pointerEvents: "none" }}>
        <svg width="1080" height="1920" style={{ transform: `translate(${-sx}px, ${-sy}px)` }}>
          <filter id="grain"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed={f % 7} /></filter>
          <rect width="1300" height="2200" filter="url(#grain)" />
        </svg>
      </AbsoluteFill>
      <AbsoluteFill style={{ background: t.shade, mixBlendMode: "soft-light", opacity: 0.35 }} />
    </>
  );
};

/* ---------- paper texture (used by cards) ---------- */
const Paper: React.FC<{ t: CFTheme; style?: React.CSSProperties; children?: React.ReactNode; seed?: number }> =
  ({ t, style, children, seed = 3 }) => (
    <div style={{ position: "relative", background: `linear-gradient(160deg, ${t.paper} 0%, ${t.paperDark} 100%)`,
      boxShadow: "0 30px 70px rgba(0,0,0,.55), inset 0 0 90px rgba(120,80,30,.35)", borderRadius: 10, overflow: "hidden",
      ...style }}>
      <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%", opacity: 0.28, mixBlendMode: "multiply" }}>
        <filter id={`pp${seed}`}><feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="4" seed={seed} />
          <feColorMatrix values="0 0 0 0 0.45  0 0 0 0 0.32  0 0 0 0 0.18  0 0 0 0.9 0" /></filter>
        <rect width="100%" height="100%" filter={`url(#pp${seed})`} />
      </svg>
      <div style={{ position: "relative" }}>{children}</div>
    </div>
  );

/* ---------- intro: case card, red stamp, typewriter hook (full text faintly visible from frame 0) ---------- */
export const CaseIntro: React.FC<{ p: CaseFileProps; len: number }> = ({ p, len }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = p.theme;
  const chars = p.hook.length;
  const typed = Math.min(chars, Math.floor(interpolate(f, [0, Math.min(len - 18, 44)], [Math.min(6, chars), chars], clamp)));
  const stampS = spring({ frame: f - 10, fps, config: { damping: 9, stiffness: 260 } });
  const out = interpolate(f, [len - 9, len], [1, 0], clamp);
  const slide = interpolate(f, [len - 9, len], [0, -60], clamp);
  const caret = Math.floor(f / 8) % 2 === 0 && typed < chars;
  const size = chars > 46 ? 70 : chars > 30 ? 80 : 92;
  return (
    <AbsoluteFill style={{ justifyContent: "flex-start", alignItems: "center", paddingTop: 330, opacity: out,
      transform: `translateY(${slide}px)` }}>
      <Paper t={t} seed={5} style={{ width: 900, padding: "46px 58px 128px", transform: "rotate(-1.2deg)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "Caption", fontSize: 30, letterSpacing: 5,
          color: t.ink, opacity: 0.75, borderBottom: `3px solid ${t.ink}33`, paddingBottom: 16, marginBottom: 30 }}>
          <span>{p.brand.toUpperCase()}</span><span>{p.fileLabel}</span>
        </div>
        <div style={{ position: "relative", fontFamily: "Title", fontSize: size, lineHeight: 1.12, color: t.ink }}>
          <span style={{ opacity: 0 }}>{p.hook}</span>
          <span style={{ position: "absolute", left: 0, top: 0, right: 0 }}>
            <span>{p.hook.slice(0, typed)}</span>
            <span style={{ opacity: caret ? 1 : 0, color: t.stamp }}>|</span>
            <span style={{ opacity: 0.22 }}>{p.hook.slice(typed)}</span>
          </span>
        </div>
        <div style={{ position: "absolute", right: 0, bottom: -96, transform: `rotate(-8deg) scale(${2.2 - 1.2 * stampS})`,
          opacity: Math.min(1, stampS * 1.3) * 0.9, border: `6px solid ${t.stamp}`, color: t.stamp, borderRadius: 10,
          padding: "6px 20px", fontFamily: "Caption", fontWeight: 800, fontSize: 40, letterSpacing: 4, mixBlendMode: "multiply" }}>
          {p.stamp}</div>
      </Paper>
    </AbsoluteFill>
  );
};

/* ---------- sentence captions: 2 lines max, readable bar, dates and names in the accent colour ---------- */
const chunkWords = (words: CFWord[], maxChars = 46) => {
  const out: CFWord[][] = [];
  let cur: CFWord[] = [];
  let len = 0;
  words.forEach((w) => {
    if (cur.length && len + w.w.length + 1 > maxChars) { out.push(cur); cur = []; len = 0; }
    cur.push(w); len += w.w.length + 1;
    // end a caption at a sentence end, or at a comma once it is long enough (never mid-phrase if avoidable)
    if ((/[.?!]$/.test(w.w) && len > 14) || (/[,;:]$/.test(w.w) && len > 24)) { out.push(cur); cur = []; len = 0; }
  });
  if (cur.length) out.push(cur);
  return out;
};

export const SentenceCaptions: React.FC<{ p: CaseFileProps; hideUntil: number; hideFrom: number }> =
  ({ p, hideUntil, hideFrom }) => {
    const f = useCurrentFrame();
    const { fps } = useVideoConfig();
    const t = f / fps;
    const chunks = React.useMemo(() => chunkWords(p.words), [p.words]);
    if (t < hideUntil || t > hideFrom) return null;
    const ci = chunks.findIndex((c, i) => t >= c[0].t - 0.05 && (i === chunks.length - 1 || t < chunks[i + 1][0].t - 0.05));
    if (ci < 0) return null;
    const c = chunks[ci];
    const hl = new Set(p.highlights.flatMap((h) => h.split(/\s+/)).map(norm).filter((x) => x.length > 1));
    const isHl = (w: string) => /\d{3,4}/.test(w) || /^(bc|ad|bce|ce)\W*$/i.test(w) || hl.has(norm(w));
    const appear = interpolate(f, [Math.round((c[0].t - 0.05) * fps), Math.round((c[0].t - 0.05) * fps) + 5], [0, 1], clamp);
    return (
      <div style={{ position: "absolute", bottom: 470, left: 70, width: 840, display: "flex", justifyContent: "center" }}>
        <div style={{ background: "rgba(14,10,6,.62)", borderRadius: 18, padding: "14px 26px 16px", maxWidth: 840,
          textAlign: "center", fontFamily: "Caption", fontWeight: 600, fontSize: 54, lineHeight: 1.22, color: "#FFFFFF",
          textShadow: "0 3px 12px rgba(0,0,0,.6)", opacity: appear, transform: `translateY(${(1 - appear) * 10}px)`,
          boxShadow: "0 10px 30px rgba(0,0,0,.35)" }}>
          {c.map((w, i) => <span key={i} style={{ color: isHl(w.w) ? p.theme.accent : "#FFFFFF" }}>{w.w}{i < c.length - 1 ? " " : ""}</span>)}
        </div>
      </div>
    );
  };

/* ---------- small evidence tag for the key word of a scene ---------- */
export const EvidenceTag: React.FC<{ text: string; t: CFTheme; len: number }> = ({ text, t, len }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: f, fps, config: { damping: 14, stiffness: 180 } });
  const out = interpolate(f, [len - 8, len], [1, 0], clamp);
  return (
    <div style={{ position: "absolute", top: 300, left: 70, opacity: out * s, transform: `translateX(${(1 - s) * -60}px) rotate(-2deg)` }}>
      <Paper t={t} seed={9} style={{ padding: "12px 26px 14px", borderLeft: `10px solid ${t.stamp}` }}>
        <div style={{ fontFamily: "Title", fontSize: 58, color: t.ink, lineHeight: 1 }}>{text}</div>
      </Paper>
    </div>
  );
};

/* ---------- animated map: pin drop (and a route when there is a "from" place) ---------- */
const LAND = feature(land110 as any, (land110 as any).objects.land) as any;
const GRAT = geoGraticule10();
export const MapCard: React.FC<{ m: CFMap; t: CFTheme; len: number }> = ({ m, t, len }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const W = 860, H = 720;
  const to: [number, number] = [m.lon, m.lat];
  const from: [number, number] | null = m.fromLon != null && m.fromLat != null ? [m.fromLon, m.fromLat] : null;
  const d = from ? geoDistance(from, to) : 0;
  const center = from && d > 0.01 ? geoInterpolate(from, to)(0.5) : to;
  const k = interpolate(f, [0, 26], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  const endScale = from && d > 0.01 ? Math.max(380, Math.min(2600, 520 / d)) : 1300;
  const scale = 330 * Math.pow(endScale / 330, k);
  const startC: [number, number] = [center[0] + 40, center[1] * 0.5];
  const c = geoInterpolate(startC, center)(k);
  const proj = geoOrthographic().scale(scale).rotate([-c[0], -c[1]]).translate([W / 2, H / 2]).clipAngle(90);
  const path = geoPath(proj);
  const pin = proj(to) || [W / 2, H / 2];
  const fromPt = from ? proj(from) : null;
  const drop = spring({ frame: f - 22, fps, config: { damping: 9, stiffness: 200 } });
  const route = from ? interpolate(f, [18, 48], [0, 1], { ...clamp, easing: Easing.inOut(Easing.quad) }) : 0;
  const routeLine = from ? { type: "LineString", coordinates: [from, geoInterpolate(from, to)(Math.max(0.001, route))] } as any : null;
  const s = spring({ frame: f, fps, config: { damping: 15 } });
  const out = interpolate(f, [len - 8, len], [1, 0], clamp);
  return (
    <AbsoluteFill style={{ alignItems: "center", paddingTop: 300, opacity: out * s }}>
      <Paper t={t} seed={11} style={{ width: W + 40, padding: 20, transform: `rotate(1deg) translateY(${(1 - s) * 40}px)` }}>
        <svg width={W} height={H} style={{ display: "block", borderRadius: 6, background: `${t.paperDark}` }}>
          <path d={path({ type: "Sphere" } as any) || ""} fill={`${t.ink}14`} />
          <path d={path(GRAT) || ""} fill="none" stroke={t.ink} strokeOpacity={0.12} strokeWidth={1} />
          <path d={path(LAND) || ""} fill={`${t.ink}38`} stroke={t.ink} strokeOpacity={0.55} strokeWidth={1.4} />
          {routeLine ? <path d={path(routeLine) || ""} fill="none" stroke={t.stamp} strokeWidth={6} strokeDasharray="14 10" strokeLinecap="round" /> : null}
          {fromPt ? <circle cx={fromPt[0]} cy={fromPt[1]} r={11} fill={t.ink} /> : null}
          <g transform={`translate(${pin[0]},${pin[1] - (1 - drop) * 60})`} opacity={Math.min(1, drop * 1.5)}>
            <circle r={26 + 18 * ((f % 36) / 36)} fill="none" stroke={t.stamp} strokeOpacity={1 - (f % 36) / 36} strokeWidth={4} />
            <path d="M0,0 C-16,-22 -22,-34 -22,-46 A22,22 0 1 1 22,-46 C22,-34 16,-22 0,0 Z" fill={t.stamp} />
            <circle cy={-46} r={8} fill={t.paper} />
          </g>
        </svg>
        <div style={{ fontFamily: "Title", fontSize: 54, color: t.ink, textAlign: "center", marginTop: 12 }}>
          {from && m.fromPlace ? `${m.fromPlace} → ${m.place}` : m.place}</div>
      </Paper>
    </AbsoluteFill>
  );
};

/* ---------- timeline on paper, with a highlight line joining the two overlapping events ---------- */
export const CaseTimeline: React.FC<{ p: CaseFileProps; len: number }> = ({ p, len }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = p.theme;
  const items = p.timeline;
  const n = items.length;
  const step = Math.max(10, Math.floor((len * 0.5) / Math.max(n, 1)));
  const rowH = n > 4 ? 150 : 175;
  const s0 = spring({ frame: f, fps, config: { damping: 16 } });
  const out = interpolate(f, [len - 8, len], [1, 0], clamp);
  const pairs = items.map((it, i) => (it.pair ? i : -1)).filter((i) => i >= 0);
  const [a, b] = pairs.length >= 2 ? [pairs[0], pairs[pairs.length - 1]] : [-1, -1];
  const linkAt = 8 + step * n + 6;
  const link = a >= 0 ? interpolate(f, [linkAt, linkAt + 20], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) }) : 0;
  const lineLen = interpolate(f, [6, 6 + step * n], [0, (n - 1) * rowH + 30], clamp);
  const dotY = (i: number) => 36 + i * rowH;
  const ya = dotY(a), yb = dotY(b);
  return (
    <AbsoluteFill style={{ alignItems: "center", paddingTop: 280, opacity: out }}>
      <Paper t={t} seed={13} style={{ width: 900, padding: "40px 46px 46px", opacity: s0, transform: `scale(${0.94 + 0.06 * s0}) rotate(-0.8deg)` }}>
        <div style={{ fontFamily: "Caption", fontWeight: 700, fontSize: 30, letterSpacing: 6, color: t.stamp, marginBottom: 26,
          textAlign: "center" }}>SIDE BY SIDE IN TIME</div>
        <div style={{ position: "relative" }}>
          <div style={{ position: "absolute", left: 38, top: 30, width: 6, height: lineLen, background: t.ink, opacity: 0.6 }} />
          {a >= 0 ? (
            <svg width={160} height={(n - 1) * rowH + 80} style={{ position: "absolute", left: -40, top: 0, overflow: "visible" }}>
              <path d={`M 78 ${ya} C ${-10} ${ya + 30}, ${-10} ${yb - 30}, 78 ${yb}`} fill="none" stroke={t.stamp} strokeWidth={8}
                strokeLinecap="round" strokeDasharray={1000} strokeDashoffset={1000 * (1 - link)} />
            </svg>
          ) : null}
          {items.map((it, i) => {
            const s = spring({ frame: f - 6 - i * step, fps, config: { damping: 13, stiffness: 160 } });
            const hot = link > 0.6 && (i === a || i === b);
            return (
              <div key={i} style={{ position: "relative", height: rowH, display: "flex", alignItems: "flex-start",
                opacity: s, transform: `translateX(${(1 - s) * 60}px)` }}>
                <div style={{ width: 84, display: "flex", justifyContent: "center", paddingTop: 14 }}>
                  <div style={{ width: 40, height: 40, borderRadius: 20, background: hot ? t.stamp : t.ink,
                    border: `6px solid ${t.paper}`, boxShadow: `0 0 0 3px ${hot ? t.stamp : t.ink}` }} />
                </div>
                <div style={{ paddingLeft: 24 }}>
                  <div style={{ fontFamily: "Title", fontSize: it.year.length > 8 ? 64 : 80, lineHeight: 1,
                    color: hot ? t.stamp : t.ink }}>{it.year}</div>
                  <div style={{ fontFamily: "Caption", fontWeight: 600, fontSize: 42, lineHeight: 1.15, color: t.ink,
                    marginTop: 6, opacity: 0.88 }}>{it.label}</div>
                </div>
              </div>
            );
          })}
        </div>
      </Paper>
    </AbsoluteFill>
  );
};

/* ---------- outro: case closed ---------- */
export const CaseOutro: React.FC<{ p: CaseFileProps }> = ({ p }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = p.theme;
  const s = spring({ frame: f, fps, config: { damping: 14 } });
  const st = spring({ frame: f - 8, fps, config: { damping: 9, stiffness: 260 } });
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", background: "rgba(10,7,4,.55)", opacity: Math.min(1, s * 1.4) }}>
      <Paper t={t} seed={17} style={{ width: 860, padding: "56px 50px", textAlign: "center", transform: `scale(${0.92 + 0.08 * s})` }}>
        <div style={{ fontFamily: "Title", fontSize: 84, color: t.ink, lineHeight: 1.05 }}>{p.brand}</div>
        <div style={{ fontFamily: "Caption", fontWeight: 600, fontSize: 40, color: t.ink, opacity: 0.85, marginTop: 22 }}>{p.outro}</div>
        <div style={{ display: "inline-block", marginTop: 30, transform: `rotate(-8deg) scale(${2 - st})`, opacity: Math.min(1, st * 1.3),
          border: `6px solid ${t.stamp}`, color: t.stamp, borderRadius: 10, padding: "4px 22px", fontFamily: "Caption",
          fontWeight: 800, fontSize: 38, letterSpacing: 4, mixBlendMode: "multiply" }}>{p.fileLabel}</div>
      </Paper>
    </AbsoluteFill>
  );
};

/* ---------- sound: ambient bed + whoosh / paper / stamp on transitions ---------- */
export const CaseSound: React.FC<{ p: CaseFileProps; cuts: number[]; papers: number[] }> = ({ p, cuts, papers }) => {
  const { fps } = useVideoConfig();
  const fr = (s: number) => Math.max(0, Math.round(s * fps));
  return (
    <>
      {p.music ? <Audio src={staticFile(p.music)} volume={0.55} /> : null}
      {p.sfx ? (
        <>
          <Sequence from={0}><Audio src={staticFile("paper.wav")} volume={0.5} /></Sequence>
          <Sequence from={fr(0.33)}><Audio src={staticFile("stamp.wav")} volume={0.55} /></Sequence>
          {cuts.map((c, i) => <Sequence key={`w${i}`} from={fr(Math.max(0, c - 0.25))}><Audio src={staticFile("whoosh.wav")} volume={0.32} /></Sequence>)}
          {papers.map((c, i) => <Sequence key={`p${i}`} from={fr(c)}><Audio src={staticFile("paper.wav")} volume={0.45} /></Sequence>)}
        </>
      ) : null}
    </>
  );
};
