"""Turns a source clip into a new, enhanced Reel:

  1. HOOK INTRO   - still frame of the key moment (blurred) + big hook text + spoken question
  2. THE CLIP     - the original clip, framed on a blurred background, original sound
  3. EXPLAINER    - replay of the key moment + AI voiceover that adds real insight, with captions

Gemini watches the clip and writes the script; Gemini TTS voices it; ffmpeg builds the video.
"""
import base64
import json
import os
import re
import subprocess
import textwrap
import time
import wave
from pathlib import Path

from common import load_config, log

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
W, H, FPS = 1080, 1920, 30
VCODEC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
          "-profile:v", "high", "-r", str(FPS), "-g", "60", "-keyint_min", "60",
          "-sc_threshold", "0"]
ACODEC = ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]


class Unsuitable(Exception):
    """Clip should not be posted (unsafe/sensitive or nothing to add)."""


# ---------------------------------------------------------------- probing
def probe(path):
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
         "-of", "json", str(path)], capture_output=True, text=True, check=True)
    info = json.loads(res.stdout)
    duration = float(info.get("format", {}).get("duration", 0) or 0)
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    return duration, has_audio


def wav_seconds(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / float(w.getframerate())


# ---------------------------------------------------------------- AI script
SCRIPT_PROMPT = """You are the writer-narrator of a Facebook Reels page. Your job is to turn this clip
into a NEW short video that adds genuine value: an explanation, context, a useful insight,
or a sharp, fair take that viewers could not get from the clip alone.

Page niche and angle: {angle}
Audience: {audience}
Language and tone for ALL text and voiceover: {language}
Clip length: {duration:.1f} seconds.

How the algorithm decides (follow this):
Facebook first shows each reel to a small test group picked from what the reel is "about", then
pushes it wider only if that group watches to the end, comments and shares.
- Make the topic obvious: name it plainly in the hook, in the first spoken sentence and in the
  first caption line (e.g. "turbo flutter", "infinity pool", "why cats knead"), so the right
  test group sees it.
- Lead with your strongest TRUE claim or most surprising angle, not a vague teaser. A non-obvious
  take on a familiar thing beats a plain description.
- Frame it broadly so anyone scrolling gets it instantly; where it is true and relevant, compare
  with something everyone knows (a famous car, a well-known landmark, an everyday object).
- Stay inside the page niche; never drift to unrelated topics.
- End the caption with a fair two-sided question people will have opinions on
  (e.g. "Manual or automatic - which would you pick?"). Debate is good; insults, politics,
  religion, negativity about real people and bait are not.

Return JSON with exactly these keys:
"skip_reason": "" normally. Fill it if the clip does not fit the page niche, or must not be posted: graphic violence or
    injury, sexual content, dangerous acts people could copy, a child as the main subject in a
    private or embarrassing moment, humiliation of a private person, hate, or political content.
"value_score": integer 1-5. How much REAL insight you can add (5 = clear, interesting
    explanation or context; 1 = nothing to add beyond describing the clip).
"hook": on-screen title for the intro, max 7 words, no emojis, no quotes. Names the topic and
    makes a bold, surprising but true point or promise about THIS clip.
"intro_vo": spoken intro, ONE sentence, max 14 words, a question or teaser that sets up the clip.
"insight_vo": spoken explainer, 40-65 words. Explain WHY or HOW, give context, a practical tip,
    a fun but TRUE fact connected to what we see, or an honest opinion clearly framed as opinion.
    Do NOT just describe what happens on screen. Only state facts that are well established;
    never invent names, places, numbers, dates or claims about the people in the clip.
    If unsure, use wording like "probably" or "it looks like".
"section_title": 2-4 word label shown during the explainer (e.g. "Here's why", "Ito pala ang dahilan").
"key_start": second where the most important moment begins (number).
"key_end": second where it ends (number, > key_start).
"caption": Facebook caption, 1-2 short lines that add your angle, ending with a genuine question.
    Max 2 emojis. No engagement bait ("like if", "share if", "tag someone", "comment YES").
"hashtags": 3-5 relevant hashtags.
Never mention AI. Never claim you filmed it."""


def _gemini_client():
    from google import genai
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY secret is missing")
    return genai.Client(api_key=key)


TRANSIENT = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "500", "INTERNAL",
             "overloaded", "high demand", "timed out", "Timeout")


def is_quota(msg):
    """Daily/plan quota used up - retrying today is pointless."""
    return "exceeded your current quota" in msg or "PerDay" in msg


def with_retry(fn, tries=6, base=10):
    """Retry temporary Gemini errors (busy/overloaded/rate limit) with backoff: 10,20,40,80,120s."""
    for attempt in range(tries):
        try:
            return fn()
        except Exception as exc:
            msg = str(exc)
            if attempt == tries - 1 or not any(t in msg for t in TRANSIENT) or is_quota(msg):
                raise
            wait = min(base * 2 ** attempt, 120)
            log(f"Gemini busy ({msg[:80]}), retrying in {wait}s")
            time.sleep(wait)


def script_models():
    """Main model first, then backups (used when the main one is overloaded or retired)."""
    cfg = load_config()
    first = os.environ.get("GEMINI_MODEL", "").strip() or cfg["gemini_model_default"]
    out = [first]
    for m in cfg.get("gemini_fallback_models", []):
        if m not in out:
            out.append(m)
    return out


class GeminiBusy(Exception):
    """Every Gemini model is overloaded/unavailable right now - try again in a later run."""


RETIRED = ("404", "NOT_FOUND", "not found", "no longer available")


def generate(client, contents, config=None, rounds=3):
    """generate_content with retries, falling back through the model list.
    Retired models (404) are skipped for the rest of the run. If all are busy, wait and go
    round again; after `rounds` raises GeminiBusy (callers then leave the clip for later).
    Returns (resp, model).
    Plain-text jobs (no video/images, no Google Search tool) go to Claude first when ANTHROPIC_API_KEY is set
    (paid by the Max plan's monthly API credits); any Claude error falls back to Gemini."""
    if isinstance(contents, str) and os.environ.get("ANTHROPIC_API_KEY", "").strip() \
            and not getattr(config, "tools", None):
        try:
            return _claude(contents, config)
        except Exception as exc:
            log(f"Claude unavailable ({str(exc)[:160]}), using Gemini")
    models = script_models()
    quota_hit = set()
    for rnd in range(rounds):
        for model in list(models):
            try:
                resp = with_retry(lambda: client.models.generate_content(
                    model=model, contents=contents, config=config), tries=3)
                return resp, model
            except Exception as exc:
                msg = str(exc)
                if is_quota(msg):
                    log(f"Model {model}: daily quota used up, skipping it for this run")
                    models.remove(model)
                    quota_hit.add(model)
                elif any(t in msg for t in RETIRED):
                    log(f"Model {model} is not available to this key, skipping it")
                    models.remove(model)
                elif any(t in msg for t in TRANSIENT):
                    log(f"Model {model} busy ({msg[:60]}), trying the next one")
                else:
                    raise
        if not models:
            if quota_hit:
                raise GeminiBusy("Gemini daily quota used up - will continue after it resets")
            raise RuntimeError("No Gemini model in the list is available to this API key")
        if rnd < rounds - 1:
            log(f"All Gemini models busy, waiting {90 * (rnd + 1)}s before another round")
            time.sleep(90 * (rnd + 1))
    raise GeminiBusy("All Gemini models were busy (high demand)")


CLAUDE_WRITER = "claude-sonnet-5-5"   # scripts, posts, outlines (creative work)
CLAUDE_LIGHT = "claude-haiku-5-5"     # judges, replies, short checks


def _claude(prompt, config=None):
    """One Claude Messages API call. Returns (resp-like object with .text, model)."""
    import requests
    from types import SimpleNamespace
    temp = getattr(config, "temperature", None)
    model = (os.environ.get("CLAUDE_WRITER_MODEL", "").strip() or CLAUDE_WRITER) if temp is None or temp >= 0.5 \
        else (os.environ.get("CLAUDE_LIGHT_MODEL", "").strip() or CLAUDE_LIGHT)
    wants_json = getattr(config, "response_mime_type", "") == "application/json"
    body = {"model": model, "max_tokens": 8000, "messages": [{"role": "user", "content": prompt}]}
    if wants_json:
        body["system"] = "Reply with valid JSON only: no markdown code fences, no text before or after the JSON."
    last = None
    for attempt in range(3):
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=300, json=body, headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"].strip(), "anthropic-version": "2023-06-01",
            "content-type": "application/json"})
        if r.status_code in (429, 500, 502, 503, 529):
            last = f"{r.status_code} {r.text[:120]}"
            time.sleep(8 * (attempt + 1))
            continue
        if not r.ok:
            raise RuntimeError(f"{r.status_code} {r.text[:200]}")
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        if wants_json:
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
        if not text:
            raise RuntimeError("empty Claude reply")
        return SimpleNamespace(text=text), model
    raise RuntimeError(f"Claude busy: {last}")


def write_script(video_path, page, duration):
    from google.genai import types
    client = _gemini_client()
    model = os.environ.get("GEMINI_MODEL", "").strip() or load_config()["gemini_model_default"]

    import mimetypes
    mime = mimetypes.guess_type(str(video_path))[0] or "video/mp4"
    if not mime.startswith("video/"):
        mime = "video/mp4"
    uploaded = client.files.upload(file=str(video_path),
                                   config=types.UploadFileConfig(mime_type=mime))
    try:
        for _ in range(100):
            state = getattr(uploaded.state, "name", str(uploaded.state))
            if "PROCESSING" not in state:
                break
            time.sleep(3)
            uploaded = client.files.get(name=uploaded.name)
        if "FAILED" in getattr(uploaded.state, "name", str(uploaded.state)):
            raise RuntimeError("Gemini could not process the video")

        prompt = SCRIPT_PROMPT.format(angle=page.get("content_angle", "general entertainment"),
                                      audience=page["audience"], language=page["language"],
                                      duration=duration)
        trends = [t for t in (page.get("_trends") or []) if t.get("angle")][:6]
        if trends:
            prompt += ("\n\nWhat is trending in this niche right now (from this week's research). If one "
                       "of these genuinely fits THIS clip, build on its angle in your own words with a "
                       "stronger hook; otherwise ignore them. Never copy anyone's wording:\n"
                       + "\n".join(f"- {t['angle']}" + (f" (hook idea: {t['hook']})" if t.get("hook") else "")
                                   for t in trends))
        resp, used = generate(client, [uploaded, prompt],
                              types.GenerateContentConfig(response_mime_type="application/json",
                                                          temperature=0.8))
        if used != model:
            log(f"Script written with backup model {used}")
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass

    data = json.loads(resp.text)
    if isinstance(data, list):
        data = data[0]
    if str(data.get("skip_reason", "")).strip():
        raise Unsuitable(str(data["skip_reason"])[:200])
    for key in ("hook", "intro_vo", "insight_vo", "caption"):
        if not str(data.get(key, "")).strip():
            raise RuntimeError(f"AI script missing '{key}'")

    tags = data.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.split()
    ks = _num(data.get("key_start"), 0.0)
    ke = _num(data.get("key_end"), ks + 4)
    ks = max(0.0, min(ks, max(duration - 1, 0)))
    ke = min(max(ke, ks + 1.5), duration)
    return {
        "value_score": int(_num(data.get("value_score"), 1)),
        "hook": _clean(data["hook"])[:70],
        "intro_vo": _clean(data["intro_vo"]),
        "insight_vo": _clean(data["insight_vo"]),
        "section_title": _clean(data.get("section_title") or "Here's why")[:30],
        "key_start": ks, "key_end": ke,
        "caption": str(data["caption"]).strip(),
        "hashtags": [t if t.startswith("#") else f"#{t}" for t in tags][:5],
    }


def _num(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean(text):
    return re.sub(r"\s+", " ", str(text)).strip().strip('"')


# ---------------------------------------------------------------- voice
def speak(text, page, out_wav):
    """Gemini TTS -> 24 kHz mono WAV file."""
    client = _gemini_client()
    model = os.environ.get("TTS_MODEL", "").strip() or load_config()["tts_model_default"]
    last = None
    for attempt in range(3):
        try:
            it = client.interactions.create(
                model=model,
                input=[{"type": "user_input", "content": [{
                    "type": "text", "text": text,
                    "annotations": [{"type": "speech_metadata", "style": page["voice_style"]}],
                }]}],
                response_format={"type": "audio", "mime_type": "audio/wav"},
                generation_config={"speech_config": [{"voice": page["voice"]}]},
            )
            data = it.output_audio.data
            raw = base64.b64decode(data) if isinstance(data, str) else bytes(data)
            if raw[:4] != b"RIFF":  # raw PCM -> wrap as WAV
                with wave.open(str(out_wav), "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
                    w.writeframes(raw)
            else:
                Path(out_wav).write_bytes(raw)
            if wav_seconds(out_wav) < 0.5:
                raise RuntimeError("TTS returned empty audio")
            return wav_seconds(out_wav)
        except Exception as exc:
            last = exc
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Voiceover failed: {last}")


# ---------------------------------------------------------------- captions
def _ass_time(t):
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def write_captions(text, start, length, path):
    """Karaoke-style chunks (3-4 words) timed proportionally to their length."""
    words = text.split()
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= 4 or w.endswith((".", "?", "!", ",")) and len(cur) >= 2:
            chunks.append(" ".join(cur)); cur = []
    if cur:
        chunks.append(" ".join(cur))
    total = sum(len(c) + 2 for c in chunks) or 1
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "",
             "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
             "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
             "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
             "Style: Cap,DejaVu Sans,74,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,"
             "100,100,0,0,1,6,2,2,80,80,430,1", "",
             "[Events]",
             "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    t = start
    for i, c in enumerate(chunks):
        d = length * (len(c) + 2) / total
        safe = c.replace("{", "(").replace("}", ")").replace("\\", "/")
        if i % 2 == 0:  # alternate highlight colour for rhythm
            safe = "{\\c&H00F7FF&}" + safe
        lines.append(f"Dialogue: 0,{_ass_time(t)},{_ass_time(t + d)},Cap,,0,0,0,,{safe}")
        t += d
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- rendering
def _text_file(work, name, text, width):
    p = Path(work) / name
    p.write_text("\n".join(textwrap.wrap(text, width=width)[:4]), encoding="utf-8")
    return p


def _brand(page):
    b = page.get("brand", "").strip()
    if not b:
        return ""
    return (f",drawtext=fontfile={FONT}:text='{_esc(b)}':expansion=none:fontsize=40:"
            "fontcolor=white@0.85:x=(w-text_w)/2:y=h-150:shadowcolor=black@0.6:shadowx=2:shadowy=2")


def _follow(page, work, end_t, secs=2.6):
    """'Follow <Page>' card over the last seconds of a reel (text from follow_cta in config.json)."""
    text = str(page.get("follow_cta") or f"Follow {page.get('brand', '').strip()} for more").strip()
    if not text or end_t < 5:
        return ""
    f = _text_file(work, "follow.txt", _esc(text), 20)
    return (f",drawtext=fontfile={FONT}:textfile={f}:expansion=none:fontsize=64:fontcolor=white:"
            "line_spacing=14:box=1:boxcolor=0x1877F2@0.95:boxborderw=30:"
            f"x=(w-text_w)/2:y=(h-text_h)/2-260:enable='gte(t,{max(0.0, end_t - secs):.2f})'")


def _esc(s):
    return s.replace("\\", "").replace("'", "").replace(":", " ").replace("%", "")


def _run(cmd, timeout=900):
    """Every ffmpeg call has a time limit, so one bad input can never freeze the whole runner."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffmpeg timed out after {timeout}s")
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {res.stderr[-800:]}")


FILL = (f"split=2[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"boxblur=24:2,eq=brightness=-0.18[bg];"
        f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS}")


def render(src, script, page, work, out_path):
    work = Path(work)
    duration, has_audio = probe(src)
    cfg = load_config()

    intro_wav, insight_wav = work / "intro.wav", work / "insight.wav"
    intro_len = speak(script["intro_vo"], page, intro_wav) + 0.35
    insight_len = speak(script["insight_vo"], page, insight_wav) + 0.6

    # --- how much of the clip fits
    room = cfg["max_reel_seconds"] - intro_len - insight_len
    if room < 3:
        raise RuntimeError("voiceover too long for a 90s reel")
    ks, ke = script["key_start"], script["key_end"]
    clip_len = min(duration, room)
    clip_start = 0.0
    if duration > room and ke > room:  # make sure the key moment stays in
        clip_start = min(duration - room, max(0.0, ke + 1 - room))

    # --- segment 1: hook over the MOVING key moment (a still frame lost most viewers in the first 3-5 s)
    hook = _text_file(work, "hook.txt", script["hook"].upper(), 16)
    seg1 = work / "s1.mp4"
    vf1 = (f"[0:v]{FILL},eq=brightness=-0.12,"
           f"drawtext=fontfile={FONT}:textfile={hook}:expansion=none:fontsize=84:"
           "fontcolor=white:line_spacing=18:box=1:boxcolor=0xE63946@0.92:boxborderw=34:"
           "x=(w-text_w)/2:y=(h-text_h)/2-120" + _brand(page) + "[v1];"
           "[1:a]aresample=48000,pan=stereo|c0=c0|c1=c0,apad[a1]")
    _run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-ss", f"{ks:.2f}", "-i", str(src),
          "-i", str(intro_wav), "-t", f"{intro_len:.2f}", "-filter_complex", vf1,
          "-map", "[v1]", "-map", "[a1]", *VCODEC, *ACODEC, str(seg1)])

    # --- segment 2: the clip, framed
    seg2 = work / "s2.mp4"
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{clip_start:.2f}", "-i", str(src)]
    if not has_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    cmd += ["-t", f"{clip_len:.2f}", "-filter_complex", f"[0:v]{FILL}{_brand(page)}[v]",
            "-map", "[v]", "-map", "0:a:0" if has_audio else "1:a:0",
            "-af", "aresample=48000", *VCODEC, *ACODEC, str(seg2)]
    _run(cmd)

    # --- segment 3: key-moment replay + insight voiceover + captions
    seg3 = work / "s3.mp4"
    caps = work / "caps.ass"
    write_captions(script["insight_vo"], 0.25, insight_len - 0.6, caps)
    title = _text_file(work, "title.txt", script["section_title"].upper(), 22)
    key = work / "key.mkv"  # cut the key moment once, then loop it under the voiceover
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{ks:.2f}", "-i", str(src),
           "-t", f"{max(ke - ks, 1.5):.2f}", "-c:v", "libx264", "-preset", "ultrafast",
           "-crf", "18"]
    cmd += ["-c:a", "pcm_s16le"] if has_audio else ["-an"]
    _run(cmd + [str(key)])
    cmd = ["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(key),
           "-i", str(insight_wav)]
    vf3 = (f"[0:v]{FILL},eq=brightness=-0.08,"
           f"drawtext=fontfile={FONT}:textfile={title}:expansion=none:fontsize=60:"
           "fontcolor=black:box=1:boxcolor=0xFFD60A@0.95:boxborderw=22:x=(w-text_w)/2:y=200,"
           f"subtitles={caps}{_brand(page)}{_follow(page, work, insight_len)}[v]")
    if has_audio:
        af3 = ("[0:a]aresample=48000,volume=0.12[bg];"
               "[1:a]aresample=48000,pan=stereo|c0=c0|c1=c0,volume=1.15[vo];"
               "[bg][vo]amix=inputs=2:duration=longest:normalize=0[a]")
    else:
        af3 = "[1:a]aresample=48000,pan=stereo|c0=c0|c1=c0,apad[a]"
    cmd += ["-t", f"{insight_len:.2f}", "-filter_complex", vf3 + ";" + af3,
            "-map", "[v]", "-map", "[a]", *VCODEC, *ACODEC, str(seg3)]
    _run(cmd)

    # --- join
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{s}'\n" for s in (seg1, seg2, seg3)))
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
          "-c", "copy", "-movflags", "+faststart", str(out_path)])
    total, _ = probe(out_path)
    log(f"Rendered {total:.1f}s reel (intro {intro_len:.1f}s, clip {clip_len:.1f}s, "
        f"explainer {insight_len:.1f}s)")
    return total
