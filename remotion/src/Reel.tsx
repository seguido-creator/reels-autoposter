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
  intro?: "pill" | "magazine"; rec?: boolean; timeline?: TimeItem[];
};
export type TimeItem = { year: string; label: string };

export const defaultProps: ReelProps = {
  total: 10, lead: 0.3, video: "joined.mp4", audio: "vo.wav", hook: "Hook", brand: "Brand",
  monogram: "B", outro: "Follow for more", totalN: 0, scenes: [], words: [], intro: "pill", rec: false,
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

// Magazine Cover intro: masthead + cover line, like a magazine front page
const MagazineIntro: React.FC<{ p: ReelProps }> = ({ p }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: f, fps, config: { damping: 16, stiffness: 120 } });
  const s2 = spring({ frame: f - 10, fps, config: { damping: 14 } });
  const out = interpolate(f, [80, 95], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const brand = p.brand.toUpperCase();
  const words = p.hook.split(" ");
  return (
    <AbsoluteFill style={{ opacity: out }}>
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(0,0,0,.55) 0%, rgba(0,0,0,0) 38%)" }} />
      <div style={{ position: "absolute", top: 150, width: "100%", textAlign: "center",
        transform: `translateY(${(1 - s) * -120}px)`, opacity: s }}>
        <div style={{ fontFamily: "Title", fontSize: brand.length > 14 ? 128 : 150, lineHeight: 1, color: p.theme.text,
          letterSpacing: 4, textShadow: "0 6px 30px rgba(0,0,0,.6)" }}>{brand}</div>
        <div style={{ margin: "18px auto 0", width: 860, borderTop: `4px solid ${p.theme.accent}`,
          borderBottom: `1px solid ${p.theme.accent}`, padding: "10px 0", fontFamily: "Body", fontSize: 30,
          letterSpacing: 6, color: p.theme.text }}>SPECIAL EDITION</div>
      </div>
      <div style={{ position: "absolute", left: 70, bottom: 640, width: 900, opacity: s2,
        transform: `translateX(${(1 - s2) * -200}px)` }}>
        <div style={{ display: "inline-block", background: p.theme.accent, color: p.theme.onAccent, fontFamily: "Body",
          fontSize: 34, padding: "4px 18px", borderRadius: 8, marginBottom: 14 }}>COVER STORY</div>
        <div style={{ fontFamily: "Title", fontSize: 96, lineHeight: 1.04, color: "#FFFFFF",
          textShadow: "0 6px 26px rgba(0,0,0,.75)" }}>
          {(p.theme.upper ? words.map((w) => w.toUpperCase()) : words).join(" ")}</div>
      </div>
    </AbsoluteFill>
  );
};

// Checklist Pop: list Reels get a running checklist; each point ticks in when it is spoken
const Checklist: React.FC<{ p: ReelProps }> = ({ p }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = f / fps;
  const items = p.scenes.filter((sc) => sc.num > 0).sort((a, b) => a.num - b.num);
  if (!items.length) return null;
  const first = items[0].start;
  const last = Math.max(...items.map((i) => i.end));
  if (t < first || t > last) return null;
  const fade = interpolate(t, [first, first + 0.3, last - 0.3, last], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", top: 420, left: 70, opacity: fade, display: "flex", flexDirection: "column", gap: 14 }}>
      {items.map((it, i) => {
        const on = t >= it.start;
        const pop = spring({ frame: f - Math.round(it.start * fps), fps, config: { damping: 10, stiffness: 200 } });
        const label = (it.key || `Point ${it.num}`);
        return (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 16, opacity: on ? 1 : 0.55 }}>
            <div style={{ width: 54, height: 54, borderRadius: 14, display: "flex", alignItems: "center", justifyContent: "center",
              background: on ? p.theme.accent : "rgba(0,0,0,.45)", border: `3px solid ${p.theme.accent}`,
              color: p.theme.onAccent, fontFamily: "Body", fontSize: 38, transform: `scale(${on ? 0.7 + 0.3 * pop : 1})` }}>
              {on ? "✓" : ""}</div>
            <div style={{ fontFamily: "Body", fontSize: 40, color: "#FFFFFF", textShadow: "0 3px 12px rgba(0,0,0,.8)",
              textDecoration: "none" }}>{p.theme.upper ? label.toUpperCase() : label}</div>
          </div>
        );
      })}
    </div>
  );
};

// REC viewfinder + punch-in on key moments (documentary / archive feel)
const RecFrame: React.FC<{ p: ReelProps }> = ({ p }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = f / fps;
  const active = p.scenes.some((sc) => sc.key && t >= sc.start && t < Math.min(sc.end, sc.start + 1.6));
  if (!active) return null;
  const c = "rgba(255,255,255,.9)";
  const L = 90, W = 6, M = 60;
  const corner = (st: React.CSSProperties) => <div style={{ position: "absolute", width: L, height: L, ...st }} />;
  return (
    <AbsoluteFill>
      {corner({ top: M + 120, left: M, borderTop: `${W}px solid ${c}`, borderLeft: `${W}px solid ${c}` })}
      {corner({ top: M + 120, right: M, borderTop: `${W}px solid ${c}`, borderRight: `${W}px solid ${c}` })}
      {corner({ bottom: M + 220, left: M, borderBottom: `${W}px solid ${c}`, borderLeft: `${W}px solid ${c}` })}
      {corner({ bottom: M + 220, right: M, borderBottom: `${W}px solid ${c}`, borderRight: `${W}px solid ${c}` })}
      <div style={{ position: "absolute", top: M + 150, right: M + 40, fontFamily: "Body", fontSize: 34, color: "#FFFFFF",
        display: "flex", alignItems: "center", gap: 10, textShadow: "0 2px 8px rgba(0,0,0,.7)" }}>
        <span style={{ width: 22, height: 22, borderRadius: 11, background: "#E53935",
          opacity: Math.floor(f / 15) % 2 === 0 ? 1 : 0.25, display: "inline-block" }} />REC</div>
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

// Animated timeline (History Decoded): dates drop in one by one on a growing vertical line,
// shown over the last scene so viewers SEE how events line up in time.
const Timeline: React.FC<{ p: ReelProps; len: number }> = ({ p, len }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const items = p.timeline || [];
  const n = items.length;
  const step = Math.max(10, Math.floor((len * 0.65) / Math.max(n, 1)));
  const inS = spring({ frame: f, fps, config: { damping: 18 } });
  const out = interpolate(f, [len - 8, len], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const rowH = n > 4 ? 170 : 200;
  const lineLen = interpolate(f, [6, 6 + step * n], [0, (n - 1) * rowH + 40], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: out, paddingBottom: 300 }}>
      <div style={{ position: "relative", width: 900, padding: "60px 50px 70px 50px", borderRadius: 34,
        background: `linear-gradient(180deg, ${p.theme.bgTop}eb, ${p.theme.bgBottom}f0)`,
        boxShadow: "0 30px 80px rgba(0,0,0,.55)", transform: `scale(${0.9 + 0.1 * inS})`, opacity: inS }}>
        <div style={{ fontFamily: "Body", fontSize: 34, letterSpacing: 6, color: p.theme.accent, marginBottom: 34,
          textAlign: "center" }}>{p.theme.upper ? "SIDE BY SIDE IN TIME" : "Side by side in time"}</div>
        <div style={{ position: "relative" }}>
          <div style={{ position: "absolute", left: 38, top: 20, width: 8, height: lineLen, borderRadius: 4,
            background: p.theme.accent }} />
          {items.map((it, i) => {
            const s = spring({ frame: f - 6 - i * step, fps, config: { damping: 13, stiffness: 160 } });
            return (
              <div key={i} style={{ position: "relative", height: rowH, display: "flex", alignItems: "flex-start",
                opacity: s, transform: `translateX(${(1 - s) * 80}px)` }}>
                <div style={{ width: 84, display: "flex", justifyContent: "center", paddingTop: 10 }}>
                  <div style={{ width: 42, height: 42, borderRadius: 21, background: p.theme.accent,
                    border: `6px solid ${p.theme.text}`, transform: `scale(${s})` }} />
                </div>
                <div style={{ paddingLeft: 26 }}>
                  <div style={{ fontFamily: "Title", fontSize: it.year.length > 8 ? 70 : 88, lineHeight: 1,
                    color: p.theme.accent }}>{it.year}</div>
                  <div style={{ fontFamily: "Body", fontSize: 48, lineHeight: 1.15, color: p.theme.text,
                    marginTop: 8 }}>{it.label}</div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
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
  const frame = useCurrentFrame();
  const tt = frame / fps;
  // gentle punch-in on each key moment (only with the REC look)
  const zoom = p.rec ? 1 + Math.max(0, ...p.scenes.filter((sc) => sc.key).map((sc) =>
    interpolate(tt, [sc.start, sc.start + 0.35, sc.start + 1.4, sc.start + 1.8], [0, 0.08, 0.08, 0],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" }))) : 1;
  const hasTimeline = (p.timeline || []).length >= 2 && p.scenes.length > 0;
  const last = p.scenes[p.scenes.length - 1];
  // over the last scene, but always on screen for at least ~4.5s before the outro
  const tlStart = hasTimeline ? Math.max(3.4, Math.min(last.start + 0.2, p.total - outroLen - 4.5)) : 0;
  const tlLen = hasTimeline ? Math.max(1, fr(p.total - outroLen) - fr(tlStart)) : 1;
  const fontFaces = `
@font-face{font-family:Title;src:url(${staticFile(p.theme.titleFont)});}
@font-face{font-family:Body;src:url(${staticFile(p.theme.bodyFont)});}`;
  return (
    <AbsoluteFill style={{ backgroundColor: p.theme.bgBottom }}>
      <style>{fontFaces}</style>
      <AbsoluteFill style={{ transform: `scale(${zoom})` }}>
        <OffthreadVideo src={staticFile(p.video)} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </AbsoluteFill>
      {/* top and bottom shade so text stays readable on any footage */}
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(0,0,0,.45) 0%, rgba(0,0,0,0) 28%, rgba(0,0,0,0) 55%, rgba(0,0,0,.6) 100%)" }} />
      <Sequence from={fr(p.lead)}><Audio src={staticFile(p.audio)} /></Sequence>
      <Sequence durationInFrames={fr(3.2)}>{p.intro === "magazine" ? <MagazineIntro p={p} /> : <Hook p={p} />}</Sequence>
      {p.rec ? <RecFrame p={p} /> : null}
      {p.scenes.map((sc, i) => sc.num > 0 && p.totalN > 0 && !(hasTimeline && sc.start >= tlStart) ? (
        <Sequence key={`c${i}`} from={fr(sc.start)} durationInFrames={Math.max(1, Math.min(fr(sc.end - sc.start),
          hasTimeline ? fr(tlStart) - fr(sc.start) : 1e9))}>
          <Counter sc={sc} p={p} />
        </Sequence>
      ) : null)}
      {p.scenes.map((sc, i) => sc.key && fr(sc.start) >= fr(3.2) && !(hasTimeline && sc.end > tlStart) ? (
        <Sequence key={`k${i}`} from={fr(sc.start)} durationInFrames={Math.min(fr(1.6), Math.max(1, fr(sc.end - sc.start)))}>
          <KeyFlash sc={sc} p={p} />
        </Sequence>
      ) : null)}
      {hasTimeline ? <Sequence durationInFrames={Math.max(1, fr(tlStart))}><Checklist p={p} /></Sequence> : <Checklist p={p} />}
      {hasTimeline ? <Sequence from={fr(tlStart)} durationInFrames={tlLen}><Timeline p={p} len={tlLen} /></Sequence> : null}
      <Captions p={p} />
      <Sequence from={fr(p.total - outroLen)}><Outro p={p} /></Sequence>
      <div style={{ position: "absolute", bottom: 150, width: "100%", textAlign: "center", fontFamily: "Body",
        fontSize: 38, color: "rgba(255,255,255,.85)", textShadow: "0 2px 8px rgba(0,0,0,.7)" }}>{p.brand}</div>
    </AbsoluteFill>
  );
};
