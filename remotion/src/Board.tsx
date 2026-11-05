/* "Board" look for money / how-it-works explainers (Retirement, Credit, Medical Bills, Small Business Decoded).
   No stock footage: every scene is an animated explainer card drawn from the script itself (title, one big
   number or term, an icon and up to 3 short points), on a slowly moving branded background, with sentence
   captions (2 lines max, numbers and $ / % in the accent colour), soft whoosh at each cut and a quiet music bed.
   The hook is readable from frame 0. */
import React from "react";
import {
  AbsoluteFill, Audio, Sequence, staticFile, useCurrentFrame, useVideoConfig, interpolate, spring, Easing,
} from "remotion";
import type { ReelProps } from "./Reel";

export type BoardCard = { title: string; stat?: string; icon?: string; points?: string[] };

const clamp = { extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };

/* ---------- simple line icons (24x24, stroked) ---------- */
const ICONS: Record<string, string[]> = {
  dollar: ["M12 2v20", "M17 6.5c0-1.9-2.2-3-5-3s-5 1.2-5 3.3c0 4.9 10 2.6 10 7.6 0 2.1-2.2 3.4-5 3.4s-5-1.2-5-3.3"],
  card: ["M2 6h20v12H2z", "M2 10h20", "M6 15h4"],
  calendar: ["M3 5h18v16H3z", "M3 10h18", "M8 3v4", "M16 3v4", "M7 14h3", "M14 14h3", "M7 18h3"],
  clock: ["M12 3a9 9 0 1 0 0.01 0", "M12 7v5l3.5 2"],
  doc: ["M6 2h9l5 5v15H6z", "M15 2v5h5", "M9 12h8", "M9 16h8", "M9 8h3"],
  shield: ["M12 2l8 3v6c0 5-3.4 9.3-8 11-4.6-1.7-8-6-8-11V5z", "M8.5 12l2.5 2.5 4.5-5"],
  chart: ["M3 21h18", "M6 17v-5", "M11 17V8", "M16 17v-8", "M20 4l-6 5-4-3-6 5"],
  check: ["M12 3a9 9 0 1 0 0.01 0", "M7.5 12.5l3 3 6-6.5"],
  warn: ["M12 3l10 18H2z", "M12 10v5", "M12 18v.5"],
  home: ["M3 11l9-8 9 8", "M5 9.5V21h14V9.5", "M10 21v-6h4v6"],
  hospital: ["M4 3h16v18H4z", "M12 7v8", "M8 11h8"],
  briefcase: ["M3 7h18v13H3z", "M8 7V4h8v3", "M3 12h18"],
  piggy: ["M5 11a7 6 0 0 1 13-2h2v4h-2a7 6 0 0 1-3 4v3h-3v-2H9v2H6v-3a6 6 0 0 1-1-6z", "M10 7h4"],
  percent: ["M19 5L5 19", "M7 5a2 2 0 1 0 0.01 0", "M17 15a2 2 0 1 0 0.01 0"],
  phone: ["M7 2h10v20H7z", "M11 18h2"],
  mail: ["M2 5h20v14H2z", "M2 6l10 7 10-7"],
  id: ["M2 5h20v14H2z", "M8 10a2 2 0 1 0 0.01 0", "M5 16c.6-2 5.4-2 6 0", "M14 10h5", "M14 14h4"],
  scale: ["M12 3v18", "M5 21h14", "M4 7h16", "M4 7l-3 6h6z", "M20 7l-3 6h6z"],
  user: ["M12 3a4 4 0 1 0 0.01 0", "M4 21c1-4.5 5-6 8-6s7 1.5 8 6"],
  store: ["M3 9l2-5h14l2 5", "M3 9h18v2a3 3 0 0 1-6 0 3 3 0 0 1-6 0 3 3 0 0 1-6 0z", "M5 13v8h14v-8", "M10 21v-5h4v5"],
  bank: ["M3 9l9-6 9 6", "M4 9h16", "M6 9v9", "M10 9v9", "M14 9v9", "M18 9v9", "M3 20h18"],
  search: ["M10 3a7 7 0 1 0 0.01 0", "M15 15l6 6"],
};
const Icon: React.FC<{ name?: string; size: number; color: string; draw: number }> = ({ name, size, color, draw }) => {
  const paths = ICONS[(name || "").toLowerCase()] || ICONS.doc;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={1.7}
      strokeLinecap="round" strokeLinejoin="round">
      {paths.map((d, i) => (
        <path key={i} d={d} pathLength={1} strokeDasharray={1} strokeDashoffset={1 - Math.min(1, Math.max(0, draw * 1.3 - i * 0.15))} />
      ))}
    </svg>
  );
};

/* ---------- moving branded background ---------- */
const Backdrop: React.FC<{ p: ReelProps }> = ({ p }) => {
  const f = useCurrentFrame();
  const a = p.theme.accent;
  const x1 = 200 + Math.sin(f / 90) * 160, y1 = 520 + Math.cos(f / 110) * 140;
  const x2 = 860 + Math.cos(f / 100) * 140, y2 = 1460 + Math.sin(f / 80) * 160;
  return (
    <AbsoluteFill style={{ background: `linear-gradient(170deg, ${p.theme.bgTop} 0%, ${p.theme.bgBottom} 100%)` }}>
      <AbsoluteFill style={{ background: `radial-gradient(circle at ${x1}px ${y1}px, ${a}2e 0, ${a}00 420px),
        radial-gradient(circle at ${x2}px ${y2}px, ${a}24 0, ${a}00 480px)` }} />
      <AbsoluteFill style={{ opacity: 0.16, transform: `translateY(${-(f * 0.6) % 60}px)`,
        backgroundImage: "radial-gradient(rgba(255,255,255,.55) 1.6px, transparent 1.6px)", backgroundSize: "60px 60px" }} />
    </AbsoluteFill>
  );
};

/* ---------- top bar: brand + scene progress ---------- */
const TopBar: React.FC<{ p: ReelProps; t: number }> = ({ p, t }) => {
  const n = p.scenes.length;
  return (
    <div style={{ position: "absolute", top: 120, left: 70, right: 70 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
        <div style={{ width: 70, height: 70, borderRadius: 35, background: p.theme.accent, color: p.theme.onAccent,
          fontFamily: "Title", fontSize: 32, display: "flex", alignItems: "center", justifyContent: "center" }}>{p.monogram}</div>
        <div style={{ fontFamily: "Body", fontSize: 38, color: p.theme.text, letterSpacing: 1 }}>{p.brand}</div>
      </div>
      <div style={{ display: "flex", gap: 10, marginTop: 26 }}>
        {p.scenes.map((sc, i) => {
          const k = Math.min(1, Math.max(0, (t - sc.start) / Math.max(0.3, sc.end - sc.start)));
          return (
            <div key={i} style={{ flex: 1, height: 10, borderRadius: 5, background: "rgba(255,255,255,.22)", overflow: "hidden" }}>
              <div style={{ width: `${k * 100}%`, height: "100%", background: p.theme.accent }} />
            </div>
          );
        })}
        {n === 0 ? null : null}
      </div>
    </div>
  );
};

/* ---------- intro: the hook, readable from frame 0 ---------- */
const BoardHook: React.FC<{ p: ReelProps; len: number }> = ({ p, len }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const words = (p.theme.upper ? p.hook.toUpperCase() : p.hook).split(" ");
  const out = interpolate(f, [len - 9, len], [1, 0], clamp);
  const wipe = interpolate(f, [6, 30], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  const size = p.hook.length > 34 ? 104 : p.hook.length > 22 ? 122 : 140;
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "flex-start", padding: "0 80px", paddingBottom: 260, opacity: out }}>
      <div style={{ fontFamily: "Title", fontSize: size, lineHeight: 1.04, color: p.theme.text, display: "flex", flexWrap: "wrap",
        gap: `0 ${size * 0.25}px` }}>
        {words.map((w, i) => {
          const s = spring({ frame: f - i * 2, fps, config: { damping: 14, stiffness: 200 } });
          return <span key={i} style={{ display: "inline-block", opacity: 0.8 + 0.2 * s,
            transform: `translateY(${(1 - s) * 30}px)` }}>{w}</span>;
        })}
      </div>
      <div style={{ marginTop: 34, height: 16, width: 560 * wipe, borderRadius: 8, background: p.theme.accent }} />
    </AbsoluteFill>
  );
};

/* ---------- one explainer card per scene ---------- */
const SceneCard: React.FC<{ c: BoardCard; p: ReelProps; len: number; idx: number }> = ({ c, p, len, idx }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inS = spring({ frame: f, fps, config: { damping: 15, stiffness: 150 } });
  const outK = interpolate(f, [len - 8, len], [0, 1], clamp);
  const draw = interpolate(f, [4, 28], [0, 1], clamp);
  const stat = String(c.stat || "").trim();
  const pts = (c.points || []).filter(Boolean).slice(0, 3);
  const title = p.theme.upper ? c.title.toUpperCase() : c.title;
  const statS = spring({ frame: f - 8, fps, config: { damping: 10, stiffness: 170 } });
  const step = Math.max(8, Math.floor((len * 0.55) / Math.max(1, pts.length)));
  return (
    <AbsoluteFill style={{ justifyContent: "flex-start", alignItems: "center", paddingTop: 380,
      opacity: inS * (1 - outK), transform: `translateX(${(1 - inS) * 160 - outK * 160}px)` }}>
      <div style={{ width: 920, display: "flex", flexDirection: "column", gap: 30 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 30 }}>
          <div style={{ width: 170, height: 170, borderRadius: 40, background: "rgba(255,255,255,.08)",
            border: `4px solid ${p.theme.accent}`, display: "flex", alignItems: "center", justifyContent: "center",
            transform: `rotate(${(1 - inS) * -12}deg)` }}>
            <Icon name={c.icon} size={112} color={p.theme.accent} draw={draw} />
          </div>
          <div style={{ fontFamily: "Body", fontSize: 34, letterSpacing: 4, color: p.theme.accent }}>
            {String(idx + 1).padStart(2, "0")}</div>
        </div>
        <div style={{ fontFamily: "Title", fontSize: title.length > 26 ? 84 : 100, lineHeight: 1.06, color: p.theme.text }}>{title}</div>
        {stat ? (
          <div style={{ alignSelf: "flex-start", fontFamily: "Title", fontSize: stat.length > 10 ? 96 : 150, lineHeight: 1,
            color: p.theme.onAccent, background: p.theme.accent, borderRadius: 26, padding: "10px 34px",
            transform: `scale(${0.7 + 0.3 * statS})`, transformOrigin: "left center", boxShadow: "0 18px 50px rgba(0,0,0,.35)" }}>{stat}</div>
        ) : null}
        <div style={{ display: "flex", flexDirection: "column", gap: 16, marginTop: 6 }}>
          {pts.map((pt, i) => {
            const s = spring({ frame: f - 12 - i * step, fps, config: { damping: 14, stiffness: 180 } });
            return (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 18, opacity: s, transform: `translateX(${(1 - s) * 60}px)` }}>
                <div style={{ width: 22, height: 22, borderRadius: 11, background: p.theme.accent, flex: "0 0 auto" }} />
                <div style={{ fontFamily: "Body", fontSize: 50, color: p.theme.text, lineHeight: 1.15 }}>{pt}</div>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

/* ---------- sentence captions (not karaoke): 2 lines max, numbers in the accent colour ---------- */
const chunk = (words: { w: string; t: number }[], maxChars = 44) => {
  const out: { w: string; t: number }[][] = [];
  let cur: { w: string; t: number }[] = [];
  let len = 0;
  words.forEach((w) => {
    if (cur.length && len + w.w.length + 1 > maxChars) { out.push(cur); cur = []; len = 0; }
    cur.push(w); len += w.w.length + 1;
    if ((/[.?!]$/.test(w.w) && len > 14) || (/[,;:]$/.test(w.w) && len > 24)) { out.push(cur); cur = []; len = 0; }
  });
  if (cur.length) out.push(cur);
  return out;
};
const BoardCaptions: React.FC<{ p: ReelProps; hideFrom: number }> = ({ p, hideFrom }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = f / fps;
  const chunks = React.useMemo(() => chunk(p.words), [p.words]);
  if (t > hideFrom) return null;
  const ci = chunks.findIndex((c, i) => t >= c[0].t - 0.05 && (i === chunks.length - 1 || t < chunks[i + 1][0].t - 0.05));
  if (ci < 0) return null;
  const c = chunks[ci];
  const hot = (w: string) => /\d|\$|%/.test(w);
  return (
    <div style={{ position: "absolute", bottom: 380, left: 70, width: 940, display: "flex", justifyContent: "center" }}>
      <div style={{ background: "rgba(0,0,0,.42)", borderRadius: 20, padding: "14px 28px 16px", textAlign: "center",
        fontFamily: "Body", fontSize: 52, lineHeight: 1.22, color: "#FFFFFF" }}>
        {c.map((w, i) => <span key={i} style={{ color: hot(w.w) ? p.theme.accent : "#FFFFFF" }}>{w.w}{i < c.length - 1 ? " " : ""}</span>)}
      </div>
    </div>
  );
};

const BoardOutro: React.FC<{ p: ReelProps }> = ({ p }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: f, fps, config: { damping: 12 } });
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", gap: 30, opacity: Math.min(1, s * 1.4),
      background: `linear-gradient(180deg, ${p.theme.bgTop}f2, ${p.theme.bgBottom}f7)` }}>
      <div style={{ width: 210, height: 210, borderRadius: 105, background: p.theme.accent, color: p.theme.onAccent,
        fontFamily: "Title", fontSize: 96, display: "flex", alignItems: "center", justifyContent: "center",
        transform: `scale(${s})` }}>{p.monogram}</div>
      <div style={{ fontFamily: "Title", fontSize: 86, color: p.theme.text, textAlign: "center", padding: "0 60px", lineHeight: 1.05 }}>
        {p.theme.upper ? p.brand.toUpperCase() : p.brand}</div>
      <div style={{ fontFamily: "Body", fontSize: 50, color: p.theme.text, textAlign: "center", padding: "0 80px",
        whiteSpace: "normal" }}>{p.outro}</div>
    </AbsoluteFill>
  );
};

export const BoardReel: React.FC<{ p: ReelProps }> = ({ p }) => {
  const { fps } = useVideoConfig();
  const fr = (s: number) => Math.max(0, Math.round(s * fps));
  const frame = useCurrentFrame();
  const t = frame / fps;
  const introLen = 3.0, outroLen = 1.8;
  const cards = (p.cards || []) as BoardCard[];
  const fontFaces = `
@font-face{font-family:Title;src:url(${staticFile(p.theme.titleFont)});}
@font-face{font-family:Body;src:url(${staticFile(p.theme.bodyFont)});}`;
  const cuts = p.scenes.map((sc) => Math.max(sc.start, introLen)).filter((s, i) => i > 0 && s < p.total - outroLen);
  return (
    <AbsoluteFill style={{ backgroundColor: p.theme.bgBottom }}>
      <style>{fontFaces}</style>
      <Backdrop p={p} />
      <TopBar p={p} t={t} />
      <Sequence from={fr(p.lead)}><Audio src={staticFile(p.audio)} /></Sequence>
      {p.music ? <Audio src={staticFile(p.music)} volume={0.5} /> : null}
      {p.sfx ? [introLen, ...cuts].map((c, i) => (
        <Sequence key={`w${i}`} from={Math.max(0, fr(c) - 4)} durationInFrames={fr(0.8)}><Audio src={staticFile("whoosh.wav")} volume={0.45} /></Sequence>
      )) : null}
      <Sequence durationInFrames={fr(introLen)}><BoardHook p={p} len={fr(introLen)} /></Sequence>
      {p.scenes.map((sc, i) => {
        const c = cards[i];
        const start = Math.max(sc.start, introLen);
        const end = Math.min(sc.end, p.total - outroLen);
        if (!c || !c.title || end - start < 0.5) return null;
        return (
          <Sequence key={`s${i}`} from={fr(start)} durationInFrames={Math.max(1, fr(end) - fr(start))}>
            <SceneCard c={c} p={p} len={Math.max(1, fr(end) - fr(start))} idx={i} />
          </Sequence>
        );
      })}
      <BoardCaptions p={p} hideFrom={p.total - outroLen} />
      <Sequence from={fr(p.total - outroLen)}><BoardOutro p={p} /></Sequence>
    </AbsoluteFill>
  );
};
