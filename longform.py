"""Long-form YouTube documentaries (8-12 min, 16:9) for the US channels.

Pipeline (one run = one video, saved to Drive for review; nothing is published here):
  1. Outline: title, thumbnail idea, opening hook and 5-7 chapters with their era (Claude, Gemini fallback).
  2. Chapters: 7-10 short scenes each. Every scene says which visual it needs: a painted illustration, an
     animated map, a step-by-step diagram or a real artifact photo. Each chapter is fact-checked
     (Wikipedia + Google Search, see factcheck.py); a chapter that keeps failing is left out.
  3. Voice: one narrator recording PER SCENE, so every visual starts exactly with its sentence.
  4. Visuals: illustrations are generated in the channel's own art style (Gemini image model); artifact photos
     come from Wikimedia Commons (public domain); maps and diagrams are drawn by Remotion. Never other creators'
     videos.
  5. Edit (Remotion): camera moves on every shot, brand intro, chapter cards with a moving timeline, labels,
     end-screen panel.
  6. Package: MP4 + branded thumbnail + title/description (chapters, sources, credits, AI note) to Drive.

  python longform.py --channel HIST_YT --topic "What the world looked like when the Great Pyramid was built"
  python longform.py --channel HIST_YT            # the writer proposes and picks a topic
"""
import argparse
import base64
import hashlib
import io
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from common import load_config, log, utcnow

FPS = 30
GAP = 2.4          # silence before each chapter (the chapter card shows during it)
INTRO = 3.0        # brand sting after the hook
PAUSE = 0.35       # breath between scenes
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
- Thumbnail: "thumb_text" 2-4 punchy words that ADD to the title (do not repeat it); "thumb_art" a one-sentence
  scene for a dramatic painted thumbnail illustration (one clear subject, close and bold, strong light).
- Hook: the spoken opening, 45-70 words. Start with the most surprising TRUE fact of the whole video,
  promise what the viewer will understand by the end, no "in this video", no greetings. "hook_art": the
  painted scene shown under the hook.
- 5 to 7 chapters in a clear order that builds curiosity; the strongest reveal near the end.
- Each chapter: a short title (max 6 words), 2-4 bullet "beats" (facts or story points), "era" (as shown on
  screen, e.g. "c. 2600 BC") and "year" (an integer, negative for BC, e.g. -2600).
- Only well-documented facts that appear in standard encyclopedias. Ancient dates are estimates
  ("around", "about"). No invented quotes.
Return ONLY JSON: {{"title": "...", "alt_titles": ["...", "..."], "thumb_text": "...", "thumb_art": "...",
"hook": "...", "hook_art": "...", "chapters": [{{"title": "...", "beats": ["..."], "era": "...", "year": -2600}}],
"description": "2-3 sentence YouTube description in plain language", "tags": ["up to 12 search tags"]}}"""

CHAPTER_PROMPT = """You write one chapter of the YouTube documentary "{title}" for the channel "{brand}".
Audience: {audience}. Voice and style: {language}
{style_block}
{extra_rules}

The whole video, for context (do not repeat other chapters):
{outline}

Write chapter {n} of {count}: "{chapter}" ({era}). Cover these beats: {beats}
{issues}
Rules for the narration:
- {words} spoken words for this chapter, split into 7 to 10 SHORT scenes of 18-35 words each (one idea per scene,
  so the picture changes every 6-12 seconds).
- Spoken, warm, vivid storytelling for the ear: short sentences, concrete images, years anchored, a small
  "but..." or "meanwhile..." turn every few sentences. End the chapter on a line that pulls into the next one
  (the last chapter ends with a one-line takeaway and a genuine question for the comments).
- Only well-documented facts; hedge estimates; no invented quotes.
Rules for the visuals - EVERY scene picks exactly one "kind":
- "illustration" (default): "art" = one sentence describing a painted scene that shows EXACTLY what this scene
  says (who, doing what, where, period-accurate clothing, tools and buildings, camera framing: wide, medium or
  close-up). Never text or labels in the picture. Vary framing between scenes.
- "map": when the story moves to a different place. "map" = {{"place": "short name", "lat": number, "lon": number,
  "from_place": "where we came from or empty", "from_lat": number or null, "from_lon": number or null}} with
  real modern coordinates of the site. Max 2 maps per chapter.
- "steps": when the scene explains HOW something was done (a method or process). "steps_title" (max 6 words),
  "steps" = 3-4 short steps (max 6 words each, factual), and "art" for the background painting. Max 1 per chapter.
- "artifact": only when the scene is about one famous real object that exists in a museum or a famous real
  monument photo (e.g. the Standard of Ur). "commons" = Wikimedia Commons search words for it.
"label": optional on-screen place/date label (max 5 words, e.g. "Ur, Mesopotamia - c. 2600 BC"), else "".
Return ONLY JSON: {{"scenes": [{{"vo": "...", "kind": "illustration|map|steps|artifact", "art": "...",
"map": {{...}} or null, "steps_title": "", "steps": [], "commons": "", "label": ""}}]}}"""

TOPIC_PROMPT = """Suggest 6 topics for long-form YouTube documentaries on the channel "{brand}".
Audience: {audience}. Angle: {angle}
{signals}
Pick topics with proven, evergreen search demand in the US (people already search or watch this), a clear
curiosity gap, enough well-documented facts for 10 minutes, and strong visual potential.
Then choose the single best one for a channel's first videos.
Return ONLY JSON: {{"ideas": ["..."], "best": "...", "why": "one sentence"}}"""

DEFAULT_ART = ("Painted documentary illustration, cinematic 16:9 composition, rich gouache-and-oil texture, "
               "soft volumetric light, historically accurate clothing, tools and architecture for the period, "
               "realistic proportions. No text, no letters, no logos, no watermarks, no modern objects, "
               "not a photograph.")


def _json(resp):
    text = (resp.text or "").strip()
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    data = json.loads(m.group(0) if m else text)
    return data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else data


def _gen(prompt, temperature=0.7):
    import transform
    from google.genai import types
    for _ in range(3):
        resp, used = transform.generate(transform._gemini_client(), prompt, types.GenerateContentConfig(
            response_mime_type="application/json", temperature=temperature))
        try:
            return _json(resp)
        except Exception:
            log(f"longform: unreadable JSON from {used}, asking again")
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
    for c in chapters:
        try:
            c["year"] = int(c.get("year"))
        except (TypeError, ValueError):
            c["year"] = None
    data["chapters"] = chapters
    return data


def _clean_scene(s):
    kind = str(s.get("kind") or "illustration").lower()
    if kind not in ("illustration", "map", "steps", "artifact"):
        kind = "illustration"
    mp = s.get("map") if isinstance(s.get("map"), dict) else None
    if kind == "map":
        try:
            mp = {"place": str(mp.get("place") or "")[:30], "lat": float(mp["lat"]), "lon": float(mp["lon"]),
                  "fromPlace": str(mp.get("from_place") or "")[:30] or None,
                  "fromLat": float(mp["from_lat"]) if mp.get("from_lat") is not None else None,
                  "fromLon": float(mp["from_lon"]) if mp.get("from_lon") is not None else None}
            if not mp["place"] or not (-90 <= mp["lat"] <= 90 and -180 <= mp["lon"] <= 180):
                raise ValueError
        except Exception:
            kind, mp = "illustration", None
    steps = [str(x).strip()[:60] for x in (s.get("steps") or []) if str(x).strip()][:4]
    if kind == "steps" and len(steps) < 2:
        kind = "illustration"
    return {"vo": str(s["vo"]).strip(), "kind": kind, "art": str(s.get("art") or "").strip(),
            "map": mp if kind == "map" else None, "steps": steps if kind == "steps" else [],
            "steps_title": str(s.get("steps_title") or "").strip()[:60], "commons": str(s.get("commons") or "").strip(),
            "label": str(s.get("label") or "").strip()[:48]}


def write_chapter(page, outline, i, minutes):
    import factcheck
    im = page["image"]
    ch = outline["chapters"][i]
    count = len(outline["chapters"])
    words = int((minutes * 150 - 60) / count)
    sketch = "\n".join(f"{k + 1}. {c['title']} ({c.get('era', '')}): {'; '.join(map(str, c.get('beats') or []))}"
                       for k, c in enumerate(outline["chapters"]))
    issues = ""
    for attempt in range(4):
        data = _gen(CHAPTER_PROMPT.format(
            title=outline["title"], brand=page["name"], audience=page["audience"], language=page["language"],
            style_block=im.get("style_block", ""), extra_rules=im.get("extra_rules", ""), outline=sketch,
            n=i + 1, count=count, chapter=ch["title"], era=ch.get("era", ""),
            beats="; ".join(map(str, ch.get("beats") or [])), issues=issues, words=words))
        scenes = [_clean_scene(s) for s in data.get("scenes") or [] if isinstance(s, dict) and str(s.get("vo", "")).strip()]
        if not 5 <= len(scenes) <= 12:
            issues = "\nThe previous draft had the wrong number of scenes. Write 7 to 10."
            continue
        if not im.get("fact_check", True):
            return scenes, []
        extra = []
        for s in scenes:
            if s["kind"] == "steps":
                extra.append(f"On-screen steps '{s['steps_title']}': " + "; ".join(s["steps"]))
            if s["label"]:
                extra.append(f"On-screen label: {s['label']}")
        text = f"Chapter: {ch['title']} ({ch.get('era', '')})\n" + " ".join(s["vo"] for s in scenes) + \
            ("\n" + "\n".join(extra) if extra else "")
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
def gen_art(page, prompt, out_path, cfg):
    """Painted illustration in the channel's style (Gemini image model, 16:9). Returns path or None."""
    from PIL import Image
    key = (os.environ.get("GEMINI_IMAGE_API_KEY") or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key or not prompt:
        return None
    from google import genai
    import transform
    style = page.get("art_style") or DEFAULT_ART
    client = genai.Client(api_key=key)
    for model, size in [(m, z) for m in cfg.get("image_models", ["gemini-nano-banana-2.1"]) for z in ("2K", "1K")]:
        try:
            it = transform.with_retry(lambda: client.interactions.create(
                model=model, input=f"{prompt}\n\nStyle: {style}",
                response_format={"type": "image", "mime_type": "image/jpeg", "aspect_ratio": "16:9",
                                 "image_size": size}), tries=2)
            data = it.output_image.data
            raw = base64.b64decode(data) if isinstance(data, str) else bytes(data)
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            w, h = im.size
            if abs(w / h - 16 / 9) > 0.05:  # crop to 16:9 if the model returned another shape
                nh = int(w * 9 / 16)
                if nh <= h:
                    im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
                else:
                    nw = int(h * 16 / 9)
                    im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
            im.resize((1920, 1080)).save(out_path, "JPEG", quality=90)
            return out_path
        except Exception as exc:
            log(f"[{page['key']}] art model {model} ({size}) failed: {str(exc)[:160]}")
    return None


def _landscape_clip(query, taken):
    import explainer
    pkey = os.environ.get("PIXABAY_API_KEY", "").strip()
    xkey = os.environ.get("PEXELS_API_KEY", "").strip()
    looks = 0
    for q in explainer._queries(query, "")[:3]:
        if not q:
            continue
        want = [w.lower() for w in q.split() if len(w) > 2] or q.lower().split()
        cands = [h for h in (explainer._pixabay_videos(q, pkey) if pkey else []) + explainer._pexels_videos(q, xkey)
                 if h["id"] not in taken and explainer._relevant(h.get("tags", ""), want)]
        wide = [h for h in cands if h["videos"]["medium"].get("width", 0) > h["videos"]["medium"].get("height", 1)]
        random.shuffle(wide)
        for h in wide[:2]:
            looks += 1
            if explainer._fits(h, q):
                return h
            if looks >= 3:
                return None
    return None


def build_visual(page, sc, k, pub, taken, cfg, credits):
    """Fills sc with img/clip/kind for the renderer. Never fails: falls back to a title card."""
    import explainer
    kind = sc["kind"]
    if kind == "map":
        return {"kind": "map", "map": sc["map"]}
    if kind == "artifact" and sc["commons"]:
        hit = explainer.commons_image(sc["commons"], taken)
        if hit:
            taken.add(hit["id"])
            name = f"a{k:03d}.jpg"
            shutil.copy(hit["image_path"], pub / name)
            credits.add(f"Wikimedia Commons (public domain): {hit.get('tags', '')[:80]}"
                        + (f" - {hit['credit']}" if hit.get("credit") else ""))
            return {"kind": "artifact", "img": name}
        kind = "illustration"
        if not sc["art"]:
            sc["art"] = f"A detailed museum-style painting of {sc['commons']}, shown clearly as it looked when new"
    if sc["art"]:
        name = f"i{k:03d}.jpg"
        if gen_art(page, sc["art"], pub / name, cfg):
            credits.add("Original illustrations made for this channel (AI-assisted)")
            out = {"kind": "steps" if kind == "steps" else "illustration", "img": name, "motion": k % 6}
            if kind == "steps":
                out.update(steps=sc["steps"], stepsTitle=sc["steps_title"])
            return out
    if kind == "steps":
        return {"kind": "steps", "steps": sc["steps"], "stepsTitle": sc["steps_title"]}
    hit = _landscape_clip(sc["art"][:60] or sc["vo"][:60], taken)
    if hit:
        taken.add(hit["id"])
        name = f"c{k:03d}.mp4"
        explainer._download(hit["videos"]["medium"]["url"], pub / name)
        credits.add("Pexels" if str(hit["id"]).startswith("pxv") else "Pixabay")
        return {"kind": "clip", "clip": name}
    return {"kind": "card", "title": sc["label"] or sc["vo"][:80]}


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
    cfg = load_config()
    work = Path(workdir)
    pub = work / "public"
    pub.mkdir(exist_ok=True)
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
        kinds = {}
        for s in scenes:
            kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
        log(f"[{page['key']}] chapter {i + 1} ready ({sum(len(s['vo'].split()) for s in scenes)} words, {kinds})")
    if len(chapters) < 4:
        raise RuntimeError(f"only {len(chapters)} chapters passed the fact-check, need at least 4")
    outline["chapters"] = kept

    # one recording per scene -> exact sync
    parts, items, t = [], [], 0.0
    pause = work / "pause.wav"
    _silence(pause, PAUSE)

    def add_scene(sc, idx):
        nonlocal t
        wav = work / f"vo{idx:03d}.wav"
        secs = transform.speak(sc["vo"], page, wav)
        parts.extend([wav, pause])
        items.append(("scene", t, secs + PAUSE, sc))
        t += secs + PAUSE

    lead = work / "lead.wav"
    _silence(lead, 0.3)
    parts.append(lead)
    t = 0.3
    hook = {"vo": outline["hook"], "kind": "illustration", "art": outline.get("hook_art") or outline.get("thumb_art", ""),
            "map": None, "steps": [], "steps_title": "", "commons": "", "label": ""}
    add_scene(hook, 0)
    intro_start = t
    gi = work / "intro.wav"
    _silence(gi, INTRO)
    parts.append(gi)
    t += INTRO
    chapter_marks = [("Intro", 0.0)]
    chap_props, n = [], 1
    for ci, scenes in enumerate(chapters):
        gap = work / f"gap{ci}.wav"
        _silence(gap, GAP)
        parts.append(gap)
        c = outline["chapters"][ci]
        chapter_marks.append((c["title"], t))
        chap_props.append({"start": round(t, 3), "dur": GAP, "n": ci + 1, "title": c["title"],
                           "era": c.get("era") or "", "year": c.get("year")})
        t += GAP
        for sc in scenes:
            add_scene(sc, n)
            n += 1
    end_start = t
    tail = work / "tail.wav"
    _silence(tail, END_SCREEN)
    parts.append(tail)
    total = t + END_SCREEN
    voice = pub / "voice.wav"
    _concat_wavs(parts, voice)
    log(f"[{page['key']}] narration {end_start / 60:.1f} min in {len(items)} scenes, video {total / 60:.1f} min")

    # visuals
    taken, credits, scene_props, counts = set(), set(), [], {}
    for k, (_kind, start, dur, sc) in enumerate(items):
        v = build_visual(page, sc, k, pub, taken, cfg, credits)
        counts[v["kind"]] = counts.get(v["kind"], 0) + 1
        v.update(start=round(start, 3), dur=round(dur, 3), label=sc.get("label") or "")
        scene_props.append(v)
    log(f"[{page['key']}] visuals: {counts}")

    th = dict(page["image"].get("theme") or {}, **(page.get("doc_theme") or {}))
    years = [c["year"] for c in chap_props if c.get("year") is not None]
    span = (max(years) - min(years)) if years else 0
    props = {"total": round(total, 3), "audio": "voice.wav", "brand": page["name"],
             "monogram": page.get("monogram") or "".join(w[0] for w in page["name"].split()[:2]).upper(),
             "title": outline["title"],
             "theme": {"accent": th.get("accent", "#C8923A"), "onAccent": th.get("on_accent", "#14110D"),
                       "bg": th.get("bg", "#0F1418"), "ink": th.get("ink", "#0B0F12"),
                       "text": th.get("text", "#F3EADB"), "muted": th.get("muted", "#C9BBA3"),
                       "land": th.get("land", "#C9B48C"), "sea": th.get("sea", "#16222B"),
                       "titleFont": "title.ttf", "bodyFont": "body.ttf"},
             "scenes": scene_props, "chapters": chap_props, "intro": {"start": round(intro_start, 3), "dur": INTRO},
             "yearMin": (min(years) - max(span * 0.1, 50)) if years else -3000,
             "yearMax": (max(years) + max(span * 0.1, 50)) if years else 2000,
             "endStart": round(end_start, 3),
             "endText": page.get("end_text") or f"Subscribe to {page['name']} for the next story"}
    out = work / "longform.mp4"
    render_doc(page, props, pub, out, work)

    thumb = work / "thumbnail.jpg"
    make_thumbnail(page, outline, th, thumb, cfg, work)
    desc = [outline.get("description", "").strip(), "",
            "Chapters:"] + [f"{_ts(s)} {nm}" for nm, s in chapter_marks] + [""]
    if sources:
        desc += ["Sources:"] + [f"- {u}" for u in list(dict.fromkeys(sources))[:12]] + [""]
    if credits:
        desc += ["Images and footage:"] + [f"- {c}" for c in sorted(credits)][:20] + [""]
    desc += ["Narration voice and illustrations are AI-generated; scenes are artistic reconstructions, not photographs. "
             "Script researched and fact-checked against encyclopedias and museum sources.", "",
             " ".join("#" + re.sub(r"\W", "", str(x)) for x in (outline.get("tags") or [])[:3])]
    meta = {"title": outline["title"], "alt_titles": outline.get("alt_titles", []),
            "thumb_text": outline.get("thumb_text", ""), "description": "\n".join(desc),
            "tags": outline.get("tags", []), "minutes": round(total / 60, 1),
            "chapters": [{"title": nm, "start": _ts(s)} for nm, s in chapter_marks]}
    return out, thumb, meta


def render_doc(page, props, pub, out, work):
    th = page["image"].get("theme") or {}
    for src, dst in ((page.get("title_font") or th.get("title_font", "Anton.ttf"), "title.ttf"),
                     (page.get("body_font") or th.get("body_font", "Poppins-Bold.ttf"), "body.ttf")):
        f = ROOT / "fonts" / src
        shutil.copy(f if f.exists() else ROOT / "fonts" / "Poppins-Bold.ttf", pub / dst)
    pj = work / "doc_props.json"
    pj.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    cmd = ["npx", "remotion", "render", "src/index.ts", "Doc", str(Path(out).resolve()), f"--props={pj}",
           f"--public-dir={pub}", "--codec=h264", "--crf=20", f"--concurrency={max(1, os.cpu_count() or 2)}",
           "--log=error"]
    if os.environ.get("REMOTION_BROWSER"):
        cmd.append(f"--browser-executable={os.environ['REMOTION_BROWSER']}")
    r = subprocess.run(cmd, cwd=ROOT / "remotion", capture_output=True, text=True,
                       timeout=int(os.environ.get("REMOTION_TIMEOUT", "7200")))
    if r.returncode != 0 or not Path(out).exists():
        raise RuntimeError((r.stderr or r.stdout or "no output")[-800:])


def make_thumbnail(page, outline, th, out, cfg, work):
    """1280x720 brand template: bold painted subject, dark side panel, 2-4 huge words, accent bar, monogram."""
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    w, h = 1280, 720
    art = gen_art(page, (outline.get("thumb_art") or outline.get("hook_art") or outline["title"])
                  + " Dramatic, high contrast, subject large on the right side of the frame, empty darker space on the left.",
                  work / "thumb_art.jpg", cfg)
    im = Image.open(art).convert("RGB").resize((w, h)) if art else Image.new("RGB", (w, h), th.get("bg", "#0F1418"))
    shade = Image.new("L", (w, h))
    sd = ImageDraw.Draw(shade)
    for x in range(w):
        sd.line([(x, 0), (x, h)], fill=int(max(0, 235 - x * 0.36)))
    im = Image.composite(Image.new("RGB", (w, h), th.get("bg", "#0F1418")), im, shade)
    d = ImageDraw.Draw(im)
    accent = th.get("accent", "#C8923A")
    d.rectangle([0, 0, 16, h], fill=accent)
    fnt = lambda name, size: ImageFont.truetype(str((ROOT / "fonts" / name) if (ROOT / "fonts" / name).exists()
                                                    else ROOT / "fonts" / "Poppins-Bold.ttf"), size)
    words = str(outline.get("thumb_text") or outline["title"]).upper().split()[:4]
    lines = [" ".join(words[:2]), " ".join(words[2:])] if len(words) > 2 else [" ".join(words)]
    size = 150
    title_font = page.get("thumb_font") or "Anton.ttf"
    f1 = fnt(title_font, size)
    while max(d.textlength(l, font=f1) for l in lines) > 690 and size > 80:
        size -= 6
        f1 = fnt(title_font, size)
    y = h // 2 - int(len(lines) * size * 1.02) // 2
    for k, line in enumerate(lines):
        d.text((64, y), line, font=f1, fill=accent if k == len(lines) - 1 else th.get("text", "#F3EADB"),
               stroke_width=5, stroke_fill="#000000")
        y += int(size * 1.04)
    # monogram + brand name, top-left
    mono = page.get("monogram") or "".join(x[0] for x in page["name"].split()[:2]).upper()
    d.ellipse([60, 44, 132, 116], outline=accent, width=5, fill=th.get("bg", "#0F1418"))
    f2 = fnt(page.get("title_font") or "Playfair-Bold.ttf", 30)
    d.text((96, 80), mono, font=f2, fill=th.get("text", "#F3EADB"), anchor="mm")
    f3 = fnt(page.get("body_font") or "Poppins-Bold.ttf", 26)
    d.text((148, 80), page["name"].upper(), font=f3, fill=th.get("text", "#F3EADB"), anchor="lm")
    im.save(out, "JPEG", quality=92)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="HIST_YT")
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
