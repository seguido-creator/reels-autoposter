/* 16:9 long-form documentary renderer (props built by longform.py).
   Every scene is drawn here: painted illustrations with camera moves, animated maps, step diagrams,
   real artifact photos or stock clips, plus brand intro, chapter cards with a timeline, labels and end panel.
   Narration (one recording per scene, already joined) is voice.wav; scene start times match it exactly. */
import React, { useMemo } from "react";
import {
  AbsoluteFill, Audio, Img, OffthreadVideo, Sequence, staticFile, useCurrentFrame, useVideoConfig,
  interpolate, spring, Easing,
} from "remotion";
import { geoMercator, geoPath, geoGraticule10 } from "d3-geo";
import { feature } from "topojson-client";
import land50 from "world-atlas/land-50m.json";

export type DocTheme = {
  accent: string; onAccent: string; bg: string; ink: string; text: string; muted: string; land: string; sea: string;
  titleFont: string; bodyFont: string;
};
export type MapSpec = { place: string; lat: number; lon: number; fromPlace?: string; fromLat?: number; fromLon?: number };
export type DocScene = {
  start: number; dur: number; kind: "illustration" | "artifact" | "clip" | "map" | "steps" | "card";
  img?: string; clip?: string; motion?: number; label?: string; map?: MapSpec;
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

/* ---------- atmosphere: vignette, warm grade, drifting dust ---------- */
const Grade: React.FC = () => (
  <AbsoluteFill style={{ pointerEvents: "none",
    background: "radial-gradient(ellipse at center, rgba(0,0,0,0) 55%, rgba(0,0,0,.55) 100%)" }} />
);

const Dust: React.FC<{ seed: number }> = ({ seed }) => {
  const f = useCurrentFrame();
  const dots = useMemo(() => Array.from({ length: 26 }, (_, i) => {
    const r = (k: number) => { const x = Math.sin(seed * 97.1 + i * 13.7 + k * 7.3) * 43758.5453; return x - Math.floor(x); };
    return { x: r(1) * 1920, y: r(2) * 1080, s: 1.5 + r(3) * 3, v: 0.15 + r(4) * 0.35, o: 0.15 + r(5) * 0.35 };
  }), [seed]);
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {dots.map((d, i) => (
        <div key={i} style={{ position: "absolute", left: (d.x + f * d.v) % 1920, top: (d.y - f * d.v * 0.6 + 1080) % 1080,
          width: d.s, height: d.s, borderRadius: "50%", background: "rgba(255,240,210,1)", opacity: d.o,
          filter: "blur(0.6px)" }} />
      ))}
    </AbsoluteFill>
  );
};

/* ---------- painted illustration / artifact with camera move ---------- */
const MOVES = [
  { s0: 1.0, s1: 1.14, x0: 0, x1: 0, y0: 0, y1: 0 },
  { s0: 1.16, s1: 1.02, x0: 0, x1: 0, y0: 0, y1: 0 },
  { s0: 1.12, s1: 1.12, x0: -4, x1: 4, y0: 0, y1: 0 },
  { s0: 1.12, s1: 1.12, x0: 4, x1: -4, y0: 0, y1: 0 },
  { s0: 1.04, s1: 1.18, x0: 2, x1: -3, y0: 2, y1: -2 },
  { s0: 1.18, s1: 1.06, x0: -3, x1: 2, y0: -2, y1: 2 },
];

const Painting: React.FC<{ sc: DocScene; frames: number; artifact?: boolean }> = ({ sc, frames, artifact }) => {
  const f = useCurrentFrame();
  const m = MOVES[(sc.motion ?? 0) % MOVES.length];
  const t = interpolate(f, [0, frames], [0, 1], { ...clamp, easing: Easing.inOut(Easing.sin) });
  const s = m.s0 + (m.s1 - m.s0) * t;
  const x = m.x0 + (m.x1 - m.x0) * t;
  const y = m.y0 + (m.y1 - m.y0) * t;
  const fade = interpolate(f, [0, 10], [0, 1], clamp);
  if (artifact) {
    // real photo: whole object visible over a blurred copy of itself
    return (
      <AbsoluteFill style={{ opacity: fade }}>
        <Img src={staticFile(sc.img!)} style={{ position: "absolute", inset: 0, width: "100%", height: "100%",
          objectFit: "cover", filter: "blur(28px) brightness(.45)", transform: "scale(1.15)" }} />
        <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
          <Img src={staticFile(sc.img!)} style={{ maxWidth: "78%", maxHeight: "82%", objectFit: "contain",
            transform: `scale(${0.96 + 0.06 * t})`, boxShadow: "0 30px 80px rgba(0,0,0,.6)" }} />
        </AbsoluteFill>
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill style={{ overflow: "hidden", opacity: fade }}>
      <Img src={staticFile(sc.img!)} style={{ width: "100%", height: "100%", objectFit: "cover",
        transform: `scale(${s}) translate(${x}%, ${y}%)` }} />
    </AbsoluteFill>
  );
};

/* ---------- animated map ---------- */
const LAND = feature(land50 as any, (land50 as any).objects.land) as any;
const GRAT = geoGraticule10();

const MapScene: React.FC<{ sc: DocScene; t: DocTheme; frames: number }> = ({ sc, t, frames }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const mp = sc.map!;
  const k = spring({ frame: f, fps, config: { damping: 200, stiffness: 30 }, durationInFrames: Math.min(70, frames) });
  const scale = interpolate(k, [0, 1], [260, 1500]);
  const cLon = interpolate(k, [0, 1], [mp.fromLon ?? 30, mp.lon]);
  const cLat = interpolate(k, [0, 1], [mp.fromLat ?? 25, mp.lat]);
  const proj = geoMercator().scale(scale).center([cLon, cLat]).translate([960, 560]);
  const path = geoPath(proj);
  const pin = proj([mp.lon, mp.lat]) || [960, 540];
  const from = mp.fromLon != null && mp.fromLat != null ? proj([mp.fromLon, mp.fromLat]) : null;
  const pulse = (f % 45) / 45;
  const labelIn = interpolate(f, [40, 60], [0, 1], clamp);
  return (
    <AbsoluteFill style={{ background: t.sea }}>
      <svg width={1920} height={1080}>
        <path d={path(GRAT) || ""} fill="none" stroke={t.muted} strokeOpacity={0.12} strokeWidth={1} />
        <path d={path(LAND) || ""} fill={t.land} stroke={t.ink} strokeOpacity={0.35} strokeWidth={1.2} />
        {from && (
          <path d={`M${from[0]},${from[1]} Q${(from[0] + pin[0]) / 2},${Math.min(from[1], pin[1]) - 160} ${pin[0]},${pin[1]}`}
            fill="none" stroke={t.accent} strokeWidth={4} strokeDasharray="14 10"
            strokeDashoffset={-f * 2} opacity={0.9} />
        )}
        {from && <circle cx={from[0]} cy={from[1]} r={10} fill={t.text} opacity={0.85} />}
        <circle cx={pin[0]} cy={pin[1]} r={14 + pulse * 46} fill="none" stroke={t.accent} strokeWidth={4} opacity={1 - pulse} />
        <circle cx={pin[0]} cy={pin[1]} r={14} fill={t.accent} stroke={t.ink} strokeWidth={3} />
      </svg>
      <div style={{ position: "absolute", left: pin[0] + 34, top: pin[1] - 40, opacity: labelIn,
        transform: `translateX(${(1 - labelIn) * -20}px)`, fontFamily: "Title", fontSize: 54, color: t.ink,
        background: t.text, padding: "8px 22px", borderLeft: `8px solid ${t.accent}` }}>{mp.place}</div>
      {from && mp.fromPlace && (
        <div style={{ position: "absolute", left: from[0] + 20, top: from[1] + 14, fontFamily: "Body", fontSize: 30,
          color: t.text, textShadow: "0 2px 10px rgba(0,0,0,.8)" }}>{mp.fromPlace}</div>
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
        lineHeight: 1.12 }}>{sc.title}</div>
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
  if (sc.kind === "map" && sc.map) body = <MapScene sc={sc} t={t} frames={frames} />;
  else if (sc.kind === "steps") body = <StepsScene sc={sc} t={t} frames={frames} />;
  else if (sc.kind === "clip" && sc.clip) body = (
    <OffthreadVideo src={staticFile(sc.clip)} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />);
  else if ((sc.kind === "illustration" || sc.kind === "artifact") && sc.img)
    body = <Painting sc={sc} frames={frames} artifact={sc.kind === "artifact"} />;
  else body = <CardScene sc={sc} t={t} />;
  return (
    <AbsoluteFill>
      {body}
      {sc.kind !== "map" && sc.kind !== "steps" && <><Grade /><Dust seed={i + 1} /></>}
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
      <div style={{ textAlign: "center", opacity: s, transform: `translateY(${(1 - s) * 30}px)` }}>
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
