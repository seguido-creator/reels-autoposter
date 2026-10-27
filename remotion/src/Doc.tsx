/* 16:9 overlay layer for long-form YouTube documentaries (rendered by longform.py).
   longform.py prepares joined.mp4 (the picture track) + voice.wav; this file adds the opening title,
   chapter cards, place/date labels, a quiet brand mark and the end-screen panel. */
import React from "react";
import {
  AbsoluteFill, Audio, OffthreadVideo, Sequence, staticFile, useCurrentFrame, useVideoConfig,
  interpolate, spring,
} from "remotion";

export type DocCard = { start: number; end: number; n: number; title: string };
export type DocLabel = { start: number; end: number; text: string };
export type DocTheme = {
  accent: string; onAccent: string; bg: string; text: string; muted: string; titleFont: string; bodyFont: string;
};
export type DocProps = {
  total: number; video: string; audio: string; brand: string; title: string;
  cards: DocCard[]; labels: DocLabel[]; endStart: number; endText: string; theme: DocTheme;
};

export const docDefaults: DocProps = {
  total: 10, video: "joined.mp4", audio: "voice.wav", brand: "Brand", title: "Title", cards: [], labels: [],
  endStart: 8, endText: "Subscribe", theme: {
    accent: "#D9822B", onAccent: "#1A140E", bg: "#120E0A", text: "#F4EAD5", muted: "#D6C7A8",
    titleFont: "title.ttf", bodyFont: "body.ttf" },
};

const ChapterCard: React.FC<{ c: DocCard; t: DocTheme; frames: number }> = ({ c, t, frames }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: f, fps, config: { damping: 16, stiffness: 120 } });
  const out = interpolate(f, [frames - 8, frames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const line = interpolate(f, [4, 24], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ background: t.bg, opacity: out, justifyContent: "center", alignItems: "center" }}>
      <div style={{ textAlign: "center", transform: `translateY(${(1 - s) * 30}px)`, opacity: s }}>
        {c.n > 0 && <div style={{ fontFamily: "Body", fontSize: 34, letterSpacing: 10, color: t.accent }}>
          CHAPTER {c.n}</div>}
        <div style={{ height: 4, width: 220 * line, background: t.accent, margin: "22px auto 26px" }} />
        <div style={{ fontFamily: "Title", fontSize: c.n > 0 ? 92 : 72, color: t.text, maxWidth: 1500, lineHeight: 1.1,
          padding: "0 120px" }}>{c.title}</div>
      </div>
    </AbsoluteFill>
  );
};

const Label: React.FC<{ l: DocLabel; t: DocTheme; frames: number }> = ({ l, t, frames }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: f, fps, config: { damping: 18, stiffness: 140 } });
  const out = interpolate(f, [frames - 10, frames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", left: 90, bottom: 110, display: "flex", alignItems: "stretch",
      opacity: Math.min(s, out), transform: `translateX(${(1 - s) * -40}px)` }}>
      <div style={{ width: 8, background: t.accent }} />
      <div style={{ background: "rgba(10,8,6,.72)", color: t.text, fontFamily: "Body", fontSize: 38,
        padding: "14px 26px", letterSpacing: 0.5 }}>{l.text}</div>
    </div>
  );
};

const Opening: React.FC<{ p: DocProps; frames: number }> = ({ p, frames }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: f - 10, fps, config: { damping: 16, stiffness: 110 } });
  const out = interpolate(f, [frames - 15, frames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", padding: "0 110px 130px", opacity: out }}>
      <div style={{ fontFamily: "Body", fontSize: 30, letterSpacing: 8, color: p.theme.accent, opacity: s }}>
        {p.brand.toUpperCase()}</div>
      <div style={{ fontFamily: "Title", fontSize: 76, color: p.theme.text, maxWidth: 1400, lineHeight: 1.08,
        marginTop: 12, opacity: s, transform: `translateY(${(1 - s) * 30}px)`,
        textShadow: "0 6px 30px rgba(0,0,0,.8)" }}>{p.title}</div>
    </AbsoluteFill>
  );
};

const EndPanel: React.FC<{ p: DocProps }> = ({ p }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: f, fps, config: { damping: 18, stiffness: 100 } });
  return (
    <AbsoluteFill style={{ background: p.theme.bg, opacity: s }}>
      {/* left half stays free for YouTube end-screen video tiles */}
      <div style={{ position: "absolute", right: 120, top: 0, bottom: 0, width: 700, display: "flex",
        flexDirection: "column", justifyContent: "center", gap: 26 }}>
        <div style={{ fontFamily: "Body", fontSize: 32, letterSpacing: 8, color: p.theme.accent }}>
          {p.brand.toUpperCase()}</div>
        <div style={{ fontFamily: "Title", fontSize: 70, color: p.theme.text, lineHeight: 1.1 }}>{p.endText}</div>
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
  const firstCard = p.cards.length ? p.cards[0].start : p.endStart;
  const openLen = Math.min(6, Math.max(2, firstCard - 0.5));
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <style>{css}</style>
      <OffthreadVideo src={staticFile(p.video)} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      <Sequence from={fr(0.3)} durationInFrames={fr(openLen)}><Opening p={p} frames={fr(openLen)} /></Sequence>
      {p.labels.map((l, i) => (
        <Sequence key={`l${i}`} from={fr(l.start)} durationInFrames={Math.max(1, fr(l.end - l.start))}>
          <Label l={l} t={p.theme} frames={Math.max(1, fr(l.end - l.start))} />
        </Sequence>
      ))}
      {p.cards.map((c, i) => (
        <Sequence key={`c${i}`} from={fr(c.start)} durationInFrames={Math.max(1, fr(c.end - c.start))}>
          <ChapterCard c={c} t={p.theme} frames={Math.max(1, fr(c.end - c.start))} />
        </Sequence>
      ))}
      <div style={{ position: "absolute", right: 60, top: 46, fontFamily: "Body", fontSize: 24, letterSpacing: 4,
        color: p.theme.text, opacity: 0.55 }}>{p.brand.toUpperCase()}</div>
      <Sequence from={fr(p.endStart)}><EndPanel p={p} /></Sequence>
      <Audio src={staticFile(p.audio)} />
    </AbsoluteFill>
  );
};
