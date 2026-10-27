"""Long-form YouTube documentaries (8-12 min, 16:9) for the US channels.

Pipeline (one run = one video, saved to Drive for review; nothing is published here):
  1. Outline: title, thumbnail text, opening hook and 5-7 chapters (Gemini).
  2. Chapters: 4-6 scenes each, every scene with its own visual (Gemini), then a fact-check per chapter
     (Wikipedia + Google Search grounding, see factcheck.py). A chapter that fails twice stops the run.
  3. Voice: one narrator (Gemini TTS) per chapter.
  4. Visuals per scene: public-domain picture from Wikimedia Commons (history) or a stock clip from
     Pexels / Pixabay checked by Gemini; if nothing fits, an animated title card. Never other creators' videos.
  5. Edit: ffmpeg builds the picture track (slow push-ins on stills, clips trimmed/looped), Remotion adds
     chapter cards, place/date labels, brand mark and the end-screen space.
  6. Package: MP4 + thumbnail + title/description (with chapters, sources, credits, AI-voice note) to Drive.

  python longform.py --channel HIST --topic "What the world looked like when the Great Pyramid was built"
  python longform.py --channel HIST            # the writer proposes and picks a topic
"""
import argparse
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from common import load_config, log, utcnow

W, H, FPS = 1920, 1080, 30
GAP = 1.6          # silence before each chapter (the chapter card shows during it)
END_SCREEN = 20.0  # YouTube end screens need the last 20 seconds
ROOT = Path(__file__).resolve().parent

OUTLINE_PROMPT = """You plan an original long-form YouTube documentary for the channel "{brand}".
Audience: {audience}
Channel angle: {angle}
Voice and style: {language}
{style_block}
{extra_rules}

{topic_line}

Plan a {minutes}-minute video (about {words} spoken words in total). Rules:
- Title: max 70 characters, curiosity + clarity, honest (the video must deliver it), no clickbait words like
  "shocking". Give the best title and 2 alternatives.
- Thumbnail text: 2-4 words that add to the title (do not repeat it).
- Hook: the spoken opening, 45-70 words. Start with the most surprising TRUE fact of the whole video,
  promise what the viewer will understand by the end, no "in this video", no greetings.
- 5 to 7 chapters in a clear order that builds curiosity; the strongest reveal near the end.
- Each chapter: a short title (max 6 words) and 2-4 bullet "beats" (facts or story points to cover).
- Only well-documented facts that appear in standard encyclopedias. Ancient dates are estimates
  ("around", "about"). No invented quotes.
- "timeline": 3-6 key dates of the video in order, each {{"year": "max 14 chars", "label": "max 4 words"}}.
Return ONLY JSON: {{"title": "...", "alt_titles": ["...", "..."], "thumb_text": "...", "thumb_query": "Wikimedia
Commons search words for the single most striking public-domain picture for the thumbnail",
"hook": "...", "chapters": [{{"title": "...", "beats": ["..."]}}], "timeline": [...],
"description": "2-3 sentence YouTube description in plain language", "tags": ["up to 12 search tags"]}}"""

CHAPTER_PROMPT = """You write one chapter of the YouTube documentary "{title}" for the channel "{brand}".
Audience: {audience}. Voice and style: {language}
{style_block}
{extra_rules}

The whole video, for context (do not repeat other chapters):
{outline}

Write chapter {n} of {count}: "{chapter}". Cover these beats: {beats}
{issues}
Rules:
- {words} spoken words for this chapter (about {seconds} seconds), split into 4 to 6 scenes of 30-70 words.
- Spoken, warm, vivid storytelling for the ear: short sentences, concrete images, years anchored, a small
  "but..." or "meanwhile..." turn every few sentences. End the chapter on a line that pulls into the next one
  (the last chapter ends with a one-line takeaway and a genuine question for the comments).
- Only well-documented facts; hedge estimates; no invented quotes.
- For EACH scene give the visual:
  "commons": Wikimedia Commons search words for a real public-domain picture of exactly what is said
             (a famous artwork, artefact, historic photo, map or monument), "" if none fits;
  "search": 2-4 words of stock footage that can be filmed today and shows the scene's main subject
            (e.g. "Giza pyramids aerial", "ancient pottery museum", "desert sunrise");
  "label": an on-screen place/date label of max 5 words (e.g. "Giza, Egypt - c. 2560 BC"), or "".
Return ONLY JSON: {{"scenes": [{{"vo": "...", "commons": "...", "search": "...", "label": "..."}}]}}"""

TOPIC_PROMPT = """Suggest 6 topics for long-form YouTube documentaries on the channel "{brand}".
Audience: {audience}. Angle: {angle}
{signals}
Pick topics with proven, evergreen search demand in the US (people already search or watch this), a clear
curiosity gap, enough well-documented facts for 10 minutes, and plenty of public-domain pictures.
Then choose the single best one for a channel's first videos.
Return ONLY JSON: {{"ideas": ["..."], "best": "...", "why": "one sentence"}}"""


def _json(resp):
    text = (resp.text or "").strip()
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    data = json.loads(m.group(0) if m else text)
    return data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else data


def _gen(prompt, temperature=0.7):
    import transform
    from google.genai import types
    for _ in range(3):
        resp, _m = transform.generate(transform._gemini_client(), prompt, types.GenerateContentConfig(
            response_mime_type="application/json", temperature=temperature))
        try:
            return _json(resp)
        except Exception:
            log("longform: unreadable JSON from the writer, asking again")
    raise RuntimeError("writer returned no usable JSON")


def channel_page(cfg, key):
    """The channel profile: a youtube_channels entry, inheriting voice/theme/rules from its base Page."""
    ch = next((c for c in cfg.get("youtube_channels", []) if c["key"].upper() == key.upper()), None)
    if not ch:
        raise SystemExit(f"no youtube_channels entry '{key}' in config.json")
    base = next((p for p in cfg["pages"] + cfg.get("image_pages", []) if p["key"] == ch.get("base_page")), {})
    page = json.loads(json.dumps(base))
    page.update({k: v for k, v in ch.items() if k != "image"})
    page["image"] = dict(base.get("image") or {}, **(ch.get("image") or {}))
    page["key"] = ch["key"]
    return page


def pick_topic(page):
    sig = ""
    try:
        import signals
        from common import drive_service, google_creds
        vids = signals.load(drive_service(google_creds())).get(str(page.get("base_page", "")).upper(), [])
        sig = signals.hint(vids)
    except Exception:
        pass
    data = _gen(TOPIC_PROMPT.format(brand=page["name"], audience=page["audience"],
                                    angle=page["image"].get("angle", ""), signals=sig), 0.9)
    log(f"[{page['key']}] topic ideas: {data.get('ideas')} -> {data.get('best')} ({data.get('why')})")
    return str(data.get("best") or (data.get("ideas") or [""])[0])


def write_outline(page, topic, minutes):
    im = page["image"]
    data = _gen(OUTLINE_PROMPT.format(
        brand=page["name"], audience=page["audience"], angle=im.get("angle", ""), language=page["language"],
        style_block=im.get("style_block", ""), extra_rules=im.get("extra_rules", ""), minutes=minutes,
        words=int(minutes * 150), topic_line=f"Topic: {topic}" if topic else ""))
    chapters = [c for c in data.get("chapters") or [] if isinstance(c, dict) and str(c.get("title", "")).strip()]
    if not data.get("title") or not data.get("hook") or not 4 <= len(chapters) <= 8:
        raise RuntimeError("outline incomplete")
    data["chapters"] = chapters
    return data


def write_chapter(page, outline, i, minutes):
    import factcheck
    im = page["image"]
    ch = outline["chapters"][i]
    count = len(outline["chapters"])
    words = int((minutes * 150 - 60) / count)
    sketch = "\n".join(f"{k + 1}. {c['title']}: {'; '.join(map(str, c.get('beats') or []))}"
                       for k, c in enumerate(outline["chapters"]))
    issues = ""
    for attempt in range(4):
        data = _gen(CHAPTER_PROMPT.format(
            title=outline["title"], brand=page["name"], audience=page["audience"], language=page["language"],
            style_block=im.get("style_block", ""), extra_rules=im.get("extra_rules", ""), outline=sketch,
            n=i + 1, count=count, chapter=ch["title"], beats="; ".join(map(str, ch.get("beats") or [])),
            issues=issues, words=words, seconds=int(words / 2.5)))
        scenes = [s for s in data.get("scenes") or [] if isinstance(s, dict) and str(s.get("vo", "")).strip()]
        if not 3 <= len(scenes) <= 8:
            issues = "\nThe previous draft had the wrong number of scenes. Write 4 to 6."
            continue
        if not im.get("fact_check", True):
            return scenes, []
        text = f"Chapter: {ch['title']}\n" + " ".join(s["vo"] for s in scenes)
        res = factcheck.check(page, text, [outline["title"], ch["title"]])
        if res["verdict"] == "pass":
            return scenes, res.get("sources") or []
        issues = ("\nA fact-checker rejected the previous draft. Fix every point (use the verified values, "
                  "hedge or drop anything uncertain; fewer, simpler claims are better than risky details): "
                  + "; ".join(map(str, res.get("issues") or []))
                  + ("\nVerified facts you may rely on: " + str(res.get("verified_facts")) if res.get("verified_facts") else ""))
    log(f"[{page['key']}] chapter {i + 1} '{ch['title']}' did not pass the fact-check, leaving it out")
    return None, []


# ---------------------------------------------------------------- visuals
def _landscape_clip(page, query, taken):
    import explainer
    pkey = os.environ.get("PIXABAY_API_KEY", "").strip()
    xkey = os.environ.get("PEXELS_API_KEY", "").strip()
    looks = 0
    for q in explainer._queries(query, "")[:4]:
        if not q:
            continue
        want = [w.lower() for w in q.split() if len(w) > 2] or q.lower().split()
        cands = [h for h in (explainer._pixabay_videos(q, pkey) if pkey else []) + explainer._pexels_videos(q, xkey)
                 if h["id"] not in taken and explainer._relevant(h.get("tags", ""), want)]
        wide = [h for h in cands if h["videos"]["medium"].get("width", 0) > h["videos"]["medium"].get("height", 1)]
        pool = wide[:8]
        random.shuffle(pool)
        for h in pool[:3]:
            looks += 1
            if explainer._fits(h, q):
                return h
            if looks >= 6:
                return None
    return None


def pick_visual(page, scene, taken):
    import explainer
    if page["image"].get("commons", True) and str(scene.get("commons") or "").strip():
        hit = explainer.commons_image(str(scene["commons"]).strip(), taken)
        if hit:
            return hit
    if str(scene.get("search") or "").strip():
        hit = _landscape_clip(page, str(scene["search"]).strip(), taken)
        if hit:
            return hit
        if page["image"].get("commons", True):
            hit = explainer.commons_image(str(scene["search"]).strip(), taken)
            if hit:
                return hit
    return {"id": f"card{len(taken)}", "card": True, "tags": "title card"}


def _seg_still(img, d, out, k):
    """Whole picture over a blurred copy of itself, slow push-in (direction alternates)."""
    import transform
    frames = max(int(d * FPS), 1)
    z = "min(1+0.00045*on,1.10)" if k % 2 == 0 else "max(1.10-0.00045*on,1.0)"
    transform._run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS), "-i", str(img),
                    "-t", f"{d:.3f}", "-filter_complex",
                    f"[0]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=28:2,"
                    f"eq=brightness=-0.18[bg];[0]scale={W - 160}:{H - 120}:force_original_aspect_ratio=decrease[fg];"
                    f"[bg][fg]overlay=(W-w)/2:(H-h)/2,scale={int(W * 1.1)}:-2,"
                    f"zoompan=z='{z}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},"
                    "setsar=1,format=yuv420p", "-frames:v", str(frames), "-an", *transform.VCODEC, str(out)],
                   timeout=1800)


def _seg_clip(src, d, out):
    import transform
    transform._run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(src), "-t", f"{d:.3f}", "-an",
                    "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS},"
                    "eq=brightness=-0.03:saturation=1.05", *transform.VCODEC, str(out)], timeout=1800)


def _seg_card(d, out, color):
    import transform
    transform._run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s={W}x{H}:r={FPS}",
                    "-t", f"{d:.3f}", "-an", "-vf", "format=yuv420p", *transform.VCODEC, str(out)], timeout=600)


# ---------------------------------------------------------------- audio
def _silence(path, secs):
    import transform
    transform._run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                    "-t", f"{secs:.3f}", "-c:a", "pcm_s16le", str(path)])


def _concat_wavs(parts, out):
    import transform
    lst = Path(out).with_suffix(".txt")
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    transform._run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(out)])


def _ts(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


# ---------------------------------------------------------------- build
def build(page, topic, minutes, workdir):
    import transform
    from explainer import _download
    work = Path(workdir)
    outline = write_outline(page, topic, minutes)
    log(f"[{page['key']}] outline: {outline['title']} | " + " / ".join(c["title"] for c in outline["chapters"]))
    chapters, sources, kept = [], [], []
    for i in range(len(outline["chapters"])):
        scenes, src = write_chapter(page, outline, i, minutes)
        if not scenes:
            continue
        chapters.append(scenes)
        kept.append(outline["chapters"][i])
        sources += src
        log(f"[{page['key']}] chapter {i + 1} ready ({sum(len(s['vo'].split()) for s in scenes)} words, "
            f"{len(scenes)} scenes)")
    if len(chapters) < 4:
        raise RuntimeError(f"only {len(chapters)} chapters passed the fact-check, need at least 4")
    outline["chapters"] = kept

    # voice: hook, then a short gap + each chapter
    parts, timeline = [], []   # timeline: (kind, start, dur, payload)
    t = 0.4
    _silence(work / "lead.wav", 0.4)
    parts.append(work / "lead.wav")
    hook_wav = work / "hook.wav"
    hook_len = transform.speak(outline["hook"], page, hook_wav)
    parts.append(hook_wav)
    hook_scene = {"vo": outline["hook"], "commons": outline.get("thumb_query", ""),
                  "search": "", "label": ""}
    timeline.append(("scene", t, hook_len, hook_scene))
    t += hook_len
    chapter_marks = [("Intro", 0.0)]
    for i, scenes in enumerate(chapters):
        gap = work / f"gap{i}.wav"
        _silence(gap, GAP)
        parts.append(gap)
        chapter_marks.append((outline["chapters"][i]["title"], t))
        timeline.append(("chapter", t, GAP, {"n": i + 1, "title": outline["chapters"][i]["title"]}))
        t += GAP
        wav = work / f"ch{i}.wav"
        secs = transform.speak(" ".join(s["vo"] for s in scenes), page, wav)
        parts.append(wav)
        words = [max(len(s["vo"].split()), 1) for s in scenes]
        for s, w in zip(scenes, words):
            d = secs * w / sum(words)
            timeline.append(("scene", t, d, s))
            t += d
    _silence(work / "tail.wav", END_SCREEN)
    parts.append(work / "tail.wav")
    end_start = t
    t += END_SCREEN
    total = t
    voice = work / "voice.wav"
    _concat_wavs(parts, voice)
    log(f"[{page['key']}] narration {end_start / 60:.1f} min, video {total / 60:.1f} min")

    # visuals
    th = page["image"]["theme"]
    taken, segs, labels, cards, credits, k = set(), [], [], [], set(), 0
    first_vis = None
    for kind, start, d, item in timeline:
        seg = work / f"v{len(segs):03d}.mp4"
        if kind == "chapter":
            _seg_card(d, seg, th.get("bg_bottom", "#111111"))
            cards.append({"start": round(start, 3), "end": round(start + d, 3), "n": item["n"], "title": item["title"]})
            segs.append(seg)
            continue
        vis = pick_visual(page, item, taken)
        taken.add(vis["id"])
        if vis.get("card"):
            _seg_card(d, seg, th.get("bg_top", "#222222"))
            cards.append({"start": round(start, 3), "end": round(start + d, 3), "n": 0,
                          "title": str(item.get("label") or "").strip() or outline["chapters"][0]["title"]})
        elif vis.get("image_url"):
            _seg_still(vis["image_path"], d, seg, k)
            credits.add(f"Wikimedia Commons (public domain): {vis.get('tags', '')[:80]}"
                        + (f" - {vis['credit']}" if vis.get("credit") else ""))
            first_vis = first_vis or vis.get("image_path")
            k += 1
        else:
            src = work / f"src{len(segs):03d}.mp4"
            _download(vis["videos"]["medium"]["url"], src)
            _seg_clip(src, d, seg)
            credits.add("Pexels" if str(vis["id"]).startswith("pxv") else "Pixabay")
        if str(item.get("label") or "").strip() and not vis.get("card"):
            labels.append({"start": round(start + 0.6, 3), "end": round(start + min(d, 6.0), 3),
                           "text": str(item["label"]).strip()[:48]})
        segs.append(seg)
        log(f"[{page['key']}] scene {len(segs)}: {vis['id']} ({d:.1f}s)")
    tail = work / "vtail.mp4"
    _seg_card(END_SCREEN, tail, th.get("bg_bottom", "#111111"))
    segs.append(tail)
    lst = work / "segs.txt"
    lst.write_text("".join(f"file '{s}'\n" for s in segs))
    joined = work / "joined.mp4"
    transform._run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                    str(joined)], timeout=1800)

    out = work / "longform.mp4"
    props = {"total": round(total, 3), "video": "joined.mp4", "audio": "voice.wav", "brand": page["name"],
             "title": outline["title"], "cards": cards, "labels": labels, "endStart": round(end_start, 3),
             "endText": page.get("end_text") or f"Subscribe to {page['name']} for the next story",
             "theme": {"accent": th["accent"], "onAccent": th.get("on_accent", "#FFFFFF"),
                       "bg": th.get("bg_bottom", "#111111"), "text": th.get("text", "#FFFFFF"),
                       "muted": th.get("muted", "#CCCCCC"), "titleFont": "title.ttf", "bodyFont": "body.ttf"}}
    try:
        render_doc(page, props, joined, voice, out, work)
    except Exception as exc:
        log(f"[{page['key']}] remotion failed, plain edit instead: {str(exc)[-300:]}")
        transform._run(["ffmpeg", "-y", "-v", "error", "-i", str(joined), "-i", str(voice), "-map", "0:v",
                        "-map", "1:a", "-c:v", "copy", *transform.ACODEC, "-shortest", "-movflags", "+faststart",
                        str(out)], timeout=1800)

    thumb = work / "thumbnail.jpg"
    make_thumbnail(page, outline, first_vis, thumb)
    desc = [outline.get("description", "").strip(), "",
            "Chapters:"] + [f"{_ts(s)} {n}" for n, s in chapter_marks] + [""]
    if sources:
        desc += ["Sources:"] + [f"- {u}" for u in list(dict.fromkeys(sources))[:12]] + [""]
    if credits:
        desc += ["Images and footage:"] + [f"- {c}" for c in sorted(credits)][:20] + [""]
    desc += ["Narration voice is AI-generated. Script researched and fact-checked against encyclopedias and "
             "museum sources.", "", " ".join("#" + re.sub(r"\W", "", str(x)) for x in (outline.get("tags") or [])[:3])]
    meta = {"title": outline["title"], "alt_titles": outline.get("alt_titles", []),
            "thumb_text": outline.get("thumb_text", ""), "description": "\n".join(desc),
            "tags": outline.get("tags", []), "minutes": round(total / 60, 1),
            "chapters": [{"title": n, "start": _ts(s)} for n, s in chapter_marks]}
    return out, thumb, meta


def render_doc(page, props, joined, voice, out, work):
    th = page["image"]["theme"]
    pub = work / "public"
    pub.mkdir(exist_ok=True)
    shutil.copy(joined, pub / "joined.mp4")
    shutil.copy(voice, pub / "voice.wav")
    for src, dst in ((th.get("title_font", "Anton.ttf"), "title.ttf"), (th.get("body_font", "Poppins-Bold.ttf"), "body.ttf")):
        f = ROOT / "fonts" / src
        shutil.copy(f if f.exists() else ROOT / "fonts" / "Poppins-Bold.ttf", pub / dst)
    pj = work / "doc_props.json"
    pj.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    cmd = ["npx", "remotion", "render", "src/index.ts", "Doc", str(Path(out).resolve()), f"--props={pj}",
           f"--public-dir={pub}", "--codec=h264", "--crf=21", f"--concurrency={max(1, os.cpu_count() or 2)}",
           "--log=error"]
    if os.environ.get("REMOTION_BROWSER"):
        cmd.append(f"--browser-executable={os.environ['REMOTION_BROWSER']}")
    r = subprocess.run(cmd, cwd=ROOT / "remotion", capture_output=True, text=True,
                       timeout=int(os.environ.get("REMOTION_TIMEOUT", "5400")))
    if r.returncode != 0 or not Path(out).exists():
        raise RuntimeError((r.stderr or r.stdout or "no output")[-600:])


def make_thumbnail(page, outline, img_path, out):
    """1280x720: the strongest picture, darkened on the left, 2-4 big words."""
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    th = page["image"]["theme"]
    w, h = 1280, 720
    if img_path and Path(img_path).is_file():
        im = Image.open(img_path).convert("RGB")
        r = max(w / im.width, h / im.height)
        im = im.resize((int(im.width * r) + 1, int(im.height * r) + 1))
        im = im.crop(((im.width - w) // 2, (im.height - h) // 2, (im.width - w) // 2 + w, (im.height - h) // 2 + h))
    else:
        im = Image.new("RGB", (w, h), th.get("bg_top", "#222222"))
    shade = Image.new("L", (w, h))
    sd = ImageDraw.Draw(shade)
    for x in range(w):
        sd.line([(x, 0), (x, h)], fill=int(max(0, 215 - x * 0.28)))
    im = Image.composite(Image.new("RGB", (w, h), "#000000"), im, shade)
    d = ImageDraw.Draw(im)
    font_file = ROOT / "fonts" / th.get("title_font", "Anton.ttf")
    words = str(outline.get("thumb_text") or outline["title"]).upper().split()[:4]
    lines = [" ".join(words[:2]), " ".join(words[2:])] if len(words) > 2 else [" ".join(words)]
    size = 132
    font = ImageFont.truetype(str(font_file if font_file.exists() else ROOT / "fonts" / "Poppins-Bold.ttf"), size)
    while max(d.textlength(l, font=font) for l in lines) > 700 and size > 70:
        size -= 6
        font = ImageFont.truetype(font.path, size)
    y = h // 2 - len(lines) * size // 2 - 10
    for k, line in enumerate(lines):
        d.text((70, y), line, font=font, fill=th["accent"] if k == len(lines) - 1 else th.get("text", "#FFFFFF"),
               stroke_width=4, stroke_fill="#000000")
        y += int(size * 1.08)
    im.save(out, "JPEG", quality=92)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="HIST")
    ap.add_argument("--topic", default="")
    ap.add_argument("--minutes", type=float, default=0)
    args = ap.parse_args()
    cfg = load_config()
    page = channel_page(cfg, args.channel)
    minutes = args.minutes or float(page.get("minutes", 10))
    topic = args.topic.strip() or pick_topic(page)
    work = Path(tempfile.mkdtemp(prefix="long_"))
    out, thumb, meta = build(page, topic, minutes, work)
    from common import drive_service, google_creds, render_folder_id, upload_render
    drive = drive_service(google_creds())
    folder = render_folder_id(drive)
    stem = f"preview_long_{page['key']}_{utcnow():%Y%m%d_%H%M}"
    _, vlink = upload_render(drive, out, stem + ".mp4", folder)
    _, tlink = upload_render(drive, thumb, stem + "_thumbnail.jpg", folder, mime="image/jpeg")
    mp = work / "meta.txt"
    mp.write_text(f"TITLE: {meta['title']}\nALTERNATIVES: {' | '.join(meta['alt_titles'])}\n"
                  f"LENGTH: {meta['minutes']} min\nTAGS: {', '.join(meta['tags'])}\n\nDESCRIPTION:\n{meta['description']}\n",
                  encoding="utf-8")
    _, mlink = upload_render(drive, mp, stem + "_details.txt", folder, mime="text/plain")
    log(f"[{page['key']}] long-form preview: video {vlink} | thumbnail {tlink} | details {mlink}")
    print(json.dumps(meta, ensure_ascii=False, indent=1)[:3000])


if __name__ == "__main__":
    main()
