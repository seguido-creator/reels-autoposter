/* Animated overlay layer for explainer Reels.
   explainer.py prepares joined.mp4 (the cut, cropped 9:16 stock clips) + vo.wav and passes
   timings as props; this file draws the hook, counters, keyword highlights, karaoke captions
   and the branded outro on top. */
import React from "react";
import {
  AbsoluteFill, Audio, OffthreadVideo, Sequence, staticFile, useCurrentFrame, useVideoConfig,
  interpolate, spring,
} from "remotion";

export type Scene = { start: number; end: number; num: number; key?: string };
export type Word = { w: string; t: number };
export type Theme = {
  accent: string; onAccent: string; bgTop: string; bgBottom: string; text: string;
  titleFont: string; bodyFont: string; upper: boolean;
};
export type ReelProps = {
  total: number; lead: number; video: string; audio: string;
  hook: string; brand: string; monogram: string; outro: string;
  totalN: number; scenes: Scene[]; words: Word[]; theme: Theme;
};

export const defaultProps: ReelProps = {
  total: 10, lead: 0.3, video: "joined.mp4", audio: "vo.wav", hook: "Hook", brand: "Brand",
  monogram: "B", outro: "Follow for more", totalN: 0, scenes: [], words: [],
  theme: { accent: "#E8B84A", onAccent: "#0F2742", bgTop: "#0F2742", bgBottom: "#081626", text: "#FFFFFF",
    titleFont: "title.ttf", bodyFont: "body.ttf", upper: true },
};

const clean = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}₱$%]/gu, "");

const PopWords: React.FC<{ text: string; size: number; delay?: number; font: string; theme: Theme; keyWord?: string }> =
  ({ text, size, delay = 0, font, theme, keyWord }) => {
    const f = useCurrentFrame();
    const { fps } = useVideoConfig();
    return (
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: `6px ${size * 0.28}px`, padding: "0 70px" }}>
        {text.split(" ").map((w, i) => {
          const s = spring({ frame: f - delay - i * 3, fps, config: { damping: 12, stiffness: 190 } });
          const hot = keyWord && clean(w) === clean(keyWord);
          return (
            <span key={i} style={{
              fontFamily: font, fontSize: size, lineHeight: 1.12, display: "inline-block",
              color: hot ? theme.onAccent : theme.text, background: hot ? theme.accent : "transparent",
              borderRadius: 16, padding: hot ? "0 14px" : 0, opacity: s,
              transform: `translateY(${(1 - s) * 40}px) scale(${0.6 + 0.4 * s})`,
              textShadow: hot ? "none" : "0 4px 22px rgba(0,0,0,.7)",
            }}>{w}</span>
          );
        })}
      </div>
    );
  };

const Hook: React.FC<{ p: ReelProps }> = ({ p }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: f, fps, config: { damping: 10, stiffness: 130 } });
  const out = interpolate(f, [80, 95], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const shake = f < 18 ? Math.sin(f * 2.3) * (18 - f) * 0.5 : 0;
  const text = p.theme.upper ? p.hook.toUpperCase() : p.hook;
  return (
    <AbsoluteFill style={{ justifyContent: "flex-start", alignItems: "center", paddingTop: 300, opacity: out }}>
      <div style={{
        transform: `scale(${s}) rotate(${shake}deg)`, background: p.theme.accent, color: p.theme.onAccent,
        fontFamily: "Title", fontSize: text.length > 22 ? 92 : 112, lineHeight: 1.08, textAlign: "center",
        padding: "18px 44px", borderRadius: 30, maxWidth: 940, boxShadow: "0 24px 70px rgba(0,0,0,.5)",
      }}>{text}</div>
    </AbsoluteFill>
  );
};

const Counter: React.FC<{ sc: Scene; p: ReelProps }> = ({ sc, p }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const len = Math.round((sc.end - sc.start) * fps);
  const inS = spring({ frame: f, fps, config: { damping: 14 } });
  const out = interpolate(f, [len - 8, len], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", top: 250, left: 70, display: "flex", alignItems: "center", gap: 22,
      opacity: out, transform: `translateX(${(1 - inS) * -320}px)` }}>
      <div style={{ fontFamily: "Title", fontSize: 108, color: p.theme.onAccent, background: p.theme.accent,
        borderRadius: 26, padding: "0 34px", boxShadow: "0 16px 40px rgba(0,0,0,.45)" }}>{sc.num}/{p.totalN}</div>
      <div style={{ display: "flex", gap: 12 }}>
        {Array.from({ length: p.totalN }).map((_, i) => (
          <div key={i} style={{ width: i < sc.num ? 64 : 24, height: 18, borderRadius: 9,
            background: i < sc.num ? p.theme.accent : "rgba(255,255,255,.4)" }} />
        ))}
      </div>
    </div>
  );
};

const KeyFlash: React.FC<{ sc: Scene; p: ReelProps }> = ({ sc, p }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const len = Math.round((sc.end - sc.start) * fps);
  const out = interpolate(f, [len - 8, len], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  if (!sc.key) return null;
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: out, paddingBottom: 120 }}>
      <PopWords text={p.theme.upper ? sc.key.toUpperCase() : sc.key} size={104} delay={6} font="Title" theme={p.theme} keyWord={sc.key} />
    </AbsoluteFill>
  );
};

// karaoke captions: groups of up to 4 words, the spoken word lights up in the accent colour
const Captions: React.FC<{ p: ReelProps }> = ({ p }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = f / fps;
  const groups: Word[][] = [];
  let cur: Word[] = [];
  p.words.forEach((w) => {
    cur.push(w);
    if (cur.length >= 4 || (/[.?!,]$/.test(w.w) && cur.length >= 2)) { groups.push(cur); cur = []; }
  });
  if (cur.length) groups.push(cur);
  const gi = groups.findIndex((g, i) => t >= g[0].t && (i === groups.length - 1 || t < groups[i + 1][0].t));
  if (gi < 0 || t > p.total - 1.2) return null;
  const g = groups[gi];
  const pop = spring({ frame: f - Math.round(g[0].t * fps), fps, config: { damping: 14, stiffness: 220 } });
  return (
    <div style={{ position: "absolute", bottom: 330, width: "100%", display: "flex", justifyContent: "center" }}>
      <div style={{ transform: `scale(${0.85 + 0.15 * pop})`, maxWidth: 940, textAlign: "center", padding: "0 40px",
        fontFamily: "Body", fontSize: 76, lineHeight: 1.15 }}>
        {g.map((w, i) => {
          const on = t >= w.t;
          return (
            <span key={i} style={{
              color: on ? p.theme.accent : "#FFFFFF", marginRight: 18, display: "inline-block",
              WebkitTextStroke: "3px rgba(0,0,0,.85)", paintOrder: "stroke fill",
              textShadow: "0 6px 18px rgba(0,0,0,.6)",
            }}>{w.w}</span>
          );
        })}
      </div>
    </div>
  );
};

const Outro: React.FC<{ p: ReelProps }> = ({ p }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: f, fps, config: { damping: 12 } });
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", gap: 26,
      background: `linear-gradient(180deg, ${p.theme.bgTop}e6, ${p.theme.bgBottom}f2)`, opacity: Math.min(1, s * 1.4) }}>
      <div style={{ width: 210, height: 210, borderRadius: 105, background: p.theme.accent, color: p.theme.onAccent,
        fontFamily: "Title", fontSize: 100, display: "flex", alignItems: "center", justifyContent: "center",
        transform: `scale(${s})` }}>{p.monogram}</div>
      <div style={{ fontFamily: "Title", fontSize: 92, color: p.theme.text, textAlign: "center", padding: "0 60px" }}>
        {p.theme.upper ? p.brand.toUpperCase() : p.brand}</div>
      <PopWords text={p.outro} size={48} delay={8} font="Body" theme={p.theme} />
    </AbsoluteFill>
  );
};

export const Reel: React.FC<ReelProps> = (p) => {
  const { fps } = useVideoConfig();
  const fr = (s: number) => Math.max(0, Math.round(s * fps));
  const outroLen = 1.6;
  const fontFaces = `
@font-face{font-family:Title;src:url(${staticFile(p.theme.titleFont)});}
@font-face{font-family:Body;src:url(${staticFile(p.theme.bodyFont)});}`;
  return (
    <AbsoluteFill style={{ backgroundColor: p.theme.bgBottom }}>
      <style>{fontFaces}</style>
      <OffthreadVideo src={staticFile(p.video)} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      {/* top and bottom shade so text stays readable on any footage */}
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(0,0,0,.45) 0%, rgba(0,0,0,0) 28%, rgba(0,0,0,0) 55%, rgba(0,0,0,.6) 100%)" }} />
      <Sequence from={fr(p.lead)}><Audio src={staticFile(p.audio)} /></Sequence>
      <Sequence durationInFrames={fr(3.2)}><Hook p={p} /></Sequence>
      {p.scenes.map((sc, i) => sc.num > 0 && p.totalN > 0 ? (
        <Sequence key={`c${i}`} from={fr(sc.start)} durationInFrames={Math.max(1, fr(sc.end - sc.start))}>
          <Counter sc={sc} p={p} />
        </Sequence>
      ) : null)}
      {p.scenes.map((sc, i) => sc.key && fr(sc.start) >= fr(3.2) ? (
        <Sequence key={`k${i}`} from={fr(sc.start)} durationInFrames={Math.min(fr(1.6), Math.max(1, fr(sc.end - sc.start)))}>
          <KeyFlash sc={sc} p={p} />
        </Sequence>
      ) : null)}
      <Captions p={p} />
      <Sequence from={fr(p.total - outroLen)}><Outro p={p} /></Sequence>
      <div style={{ position: "absolute", bottom: 150, width: "100%", textAlign: "center", fontFamily: "Body",
        fontSize: 38, color: "rgba(255,255,255,.85)", textShadow: "0 2px 8px rgba(0,0,0,.7)" }}>{p.brand}</div>
    </AbsoluteFill>
  );
};
