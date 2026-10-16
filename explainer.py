"""Original faceless "explainer" Reels built from scratch for every post:

  1. Gemini turns the day's topic into a 30-40s script split into 4-6 scenes, each with a
     stock-footage search phrase.
  2. Each scene gets its own licensed clip from Pixabay Videos (free API, no attribution needed),
     never reusing a clip the page has used before.
  3. Gemini TTS voices the script; ffmpeg cuts the clips to the voice, crops them to 9:16 and adds
     the hook title (in the page's brand colour), word-by-word captions and the page name.

Every Reel is a new edit with its own script and voice, which is what Meta counts as original.
"""
import json
import os
import random
import re
import tempfile
from pathlib import Path

from common import log

PROMPT = """You make short, original, value-packed faceless explainer Reels for the Facebook Page "{brand}".
Audience: {audience}
Voiceover language and tone: {language}

Today's topic (turn it into a Reel; you may add one extra genuinely useful insight):
Headline: {headline}
Details: {details}

Build trust the way good teachers do (problem first, then proof by logic):
- Open on a REAL problem or moment this audience recognises from their own life (a specific situation,
  not a generic topic). The viewer should think "that's me".
- Promise one concrete, realistic outcome they get by the end.
- Give the answer, and for each point say WHY it works in plain words (the reason is what builds trust).
- Include one honest limit or caveat (when it does not apply, or when to ask a professional).
- Sound like a helpful friend who knows the subject, not a salesperson. No hype, no income or result promises.

Rules:
- Only well-established facts. Never invent statistics, studies, names, prices, laws or dates.
- No medical, legal or financial advice for individuals; general education only.
- No engagement bait ("like if", "share if", "comment YES", "save this", "watch till the end").
- The FIRST sentence names the problem and makes a bold but true point (the hook).
- End with one short, genuine question to the viewer.
{format_rules}

Return JSON with exactly these keys:
"hook": on-screen opening title, max 6 words, no emojis,
"scenes": {scene_count} objects in order, each with
    "vo": the part of the script spoken during this scene (1-2 short sentences),
    {num_field}"search": 2-4 plain ENGLISH words describing ONE concrete, filmable subject for a real stock
              video clip that matches this scene (e.g. "dog running grass", "car engine closeup",
              "hotel pool sunset", "coins piggy bank"). No brand names, no text, no famous people.
              Every search phrase MUST include this page's main visual subject ({subject}) or a close
              variant, so the footage clearly fits the page (e.g. "{subject} closeup", "{subject} at night").
"caption": Facebook caption, 1-3 short lines adding value, ending with a genuine question. Max 2 emojis,
"hashtags": 3-5 relevant hashtags."""

STORY_RULES = "- Spoken script 60-85 words in total, natural and conversational, short sentences."
LIST_RULES = """- FORMAT: a numbered list of exactly {n} practical points ("Number one...", "Number two..."),
  most surprising or most useful point LAST so people keep watching. Each point = what to do + why it works.
- Spoken script 120-150 words in total, natural and conversational, short sentences."""

W, H, FPS = 1080, 1920, 30


def write_script(page, card):
    import transform
    from google.genai import types
    client = transform._gemini_client()
    details = " ".join([str(card.get("body") or "")] + [str(b) for b in card.get("bullets") or []]).strip()
    as_list = use_list(page, card)
    n = random.choice([3, 4, 5])
    prompt = PROMPT.format(brand=page["brand"], audience=page["audience"],
                           language=page["image"].get("language") or page["language"],
                           headline=card["headline"], details=details or "-",
                           subject=page["image"].get("reel_subject") or page["image"].get("reel_fallback_query", ""),
                           format_rules=LIST_RULES.format(n=n) if as_list else STORY_RULES,
                           scene_count=f"{n + 2} (1 intro scene, {n} numbered scenes, 1 closing scene)" if as_list
                           else "4 to 6",
                           num_field='"num": the point number (1..%d) for numbered scenes, 0 for intro/closing,\n    ' % n
                           if as_list else "")
    for _ in range(3):
        resp, _model = transform.generate(client, prompt, types.GenerateContentConfig(
            response_mime_type="application/json", temperature=0.8))
        try:
            data = json.loads(resp.text or "{}")
        except Exception:
            data = {}
        if isinstance(data, list):
            data = data[0] if data and isinstance(data[0], dict) else {}
        scenes = [s for s in (data.get("scenes") or []) if isinstance(s, dict)
                  and str(s.get("vo", "")).strip() and str(s.get("search", "")).strip()]
        if data.get("hook") and 3 <= len(scenes) <= 8:
            data["scenes"] = scenes
            data["total"] = n if as_list else 0
            if not as_list:
                for sc in scenes:
                    sc.pop("num", None)
            return data
        log(f"[{page['key']}] explainer script incomplete, asking again")
    raise RuntimeError("explainer script missing scenes")


def use_list(page, card):
    """Numbered-list Reels for practical topics (tips/myths), plus a share of the rest."""
    share = float(page["image"].get("list_share", 0.5))
    if share <= 0:
        return False
    return str(card.get("type", "")) in ("tips", "myth") or random.random() < share


def find_clips(page, scenes, used_ids):
    """One Pixabay video per scene; prefers vertical clips; never reuses an id."""
    import requests
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("no PIXABAY_API_KEY")
    fallback = page["image"].get("reel_fallback_query") or page["brand"]
    picked, taken = [], set(used_ids)
    for sc in scenes:
        hit = None
        words = str(sc["search"]).split()
        for q in (" ".join(words), " ".join(words[:2]), fallback):
            r = requests.get("https://pixabay.com/api/videos/", timeout=30, params={
                "key": key, "q": q[:100], "safesearch": "true", "per_page": 30, "video_type": "film"})
            if not r.ok:
                continue
            want = [w.lower() for w in q.split() if len(w) > 3] or [w.lower() for w in q.split()]
            hits = [h for h in r.json().get("hits", []) if f"pv{h['id']}" not in taken
                    and (h.get("videos") or {}).get("medium", {}).get("url")
                    and _relevant(h.get("tags", ""), want)]
            if hits:
                vertical = [h for h in hits if h["videos"]["medium"].get("height", 0) > h["videos"]["medium"].get("width", 1)]
                hit = random.choice((vertical or hits)[:8])
                break
        if not hit:
            raise RuntimeError(f"no stock clip for '{sc['search']}'")
        taken.add(f"pv{hit['id']}")
        picked.append(hit)
    return picked


BLOCK = {"military", "soldier", "soldiers", "army", "war", "weapon", "gun", "police", "blood",
         "funeral", "protest", "bikini", "lingerie", "alcohol", "beer", "wine", "cigarette", "smoking"}


def _relevant(tags, want):
    """Clip tags must mention at least one search word and nothing off-brand."""
    tl = {t.strip().lower() for t in str(tags).replace(",", " ").split()}
    if tl & BLOCK:
        return False
    return any(any(w in t or t in w for t in tl if len(t) > 2) for w in want)


def _download(url, dest):
    import requests
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)


def _hex(c):
    return "0x" + c.lstrip("#").upper()


def render(page, script, clips, out_path, clip_paths=None):
    """clip_paths lets tests pass local files instead of downloading."""
    import transform
    work = Path(tempfile.mkdtemp(prefix="expl_"))
    full = " ".join(str(s["vo"]).strip() for s in script["scenes"])
    wav = work / "vo.wav"
    vo_len = transform.speak(full, page, wav)
    lead, tail = 0.3, 0.9
    total = lead + vo_len + tail
    words = [max(len(str(s["vo"]).split()), 1) for s in script["scenes"]]
    shares = [w / sum(words) * vo_len for w in words]
    shares[0] += lead
    shares[-1] += tail

    segs = []
    for i, (d, clip) in enumerate(zip(shares, clips)):
        src = Path(clip_paths[i]) if clip_paths else work / f"src{i}.mp4"
        if not clip_paths:
            _download(clip["videos"]["medium"]["url"], src)
        seg = work / f"seg{i}.mp4"
        transform._run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(src),
                        "-t", f"{d:.3f}", "-an", "-vf",
                        f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                        f"setsar=1,fps={FPS},eq=brightness=-0.04:saturation=1.08",
                        *transform.VCODEC, str(seg)])
        segs.append(seg)
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{s}'\n" for s in segs))
    joined = work / "joined.mp4"
    transform._run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(joined)])

    caps = work / "caps.ass"
    transform.write_captions(full, lead, vo_len, caps)
    th = page["image"]["theme"]
    hook = transform._text_file(work, "hook.txt", str(script["hook"]).upper(), 16)
    on_acc = th.get("on_accent", "#FFFFFF")
    counter, t0 = "", 0.0
    total_n = int(script.get("total") or 0)
    for sc, d in zip(script["scenes"], shares):
        try:
            k = int(sc.get("num") or 0)
        except (TypeError, ValueError):
            k = 0
        if total_n and 0 < k <= total_n:
            counter += (f"drawtext=fontfile={transform.FONT}:text='{k}/{total_n}':expansion=none:fontsize=96:"
                        f"fontcolor={_hex(on_acc)}:box=1:boxcolor={_hex(th['accent'])}@0.94:boxborderw=26:"
                        f"x=70:y=300:enable='between(t,{t0:.2f},{t0 + d:.2f})',")
        t0 += d
    vf = (counter + f"drawtext=fontfile={transform.FONT}:textfile={hook}:expansion=none:fontsize=82:"
          f"fontcolor={_hex(on_acc)}:line_spacing=16:box=1:boxcolor={_hex(th['accent'])}@0.94:"
          "boxborderw=30:x=(w-text_w)/2:y=330:enable='lt(t,3.2)',"
          f"subtitles={caps}" + transform._brand(page))
    transform._run(["ffmpeg", "-y", "-v", "error", "-i", str(joined), "-i", str(wav),
                    "-filter_complex",
                    f"[0:v]{vf}[v];[1:a]adelay={int(lead * 1000)}|{int(lead * 1000)},"
                    "aresample=48000,pan=stereo|c0=c0|c1=c0,apad[a]",
                    "-map", "[v]", "-map", "[a]", "-t", f"{total:.2f}",
                    *transform.VCODEC, *transform.ACODEC, "-movflags", "+faststart", str(out_path)])
    log(f"[{page['key']}] explainer reel {total:.1f}s, {len(segs)} scenes")
    return total


def make(page, card, out_path, used_ids=()):
    """Script -> clips -> video. Returns (seconds, caption_message, [clip ids])."""
    script = write_script(page, card)
    clips = find_clips(page, script["scenes"], used_ids)
    secs = render(page, script, clips, out_path)
    tags = script.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.split()
    tags = [t if str(t).startswith("#") else f"#{t}" for t in tags][:5]
    message = str(script.get("caption") or card.get("caption") or "").strip()
    if tags:
        message += "\n\n" + " ".join(tags)
    log(f"[{page['key']}] explainer scenes: " + " | ".join(
        f"{sc['search']} -> pv{c['id']} ({c.get('tags', '')[:40]})" for sc, c in zip(script["scenes"], clips)))
    return secs, message, [f"pv{c['id']}" for c in clips]


def contact_sheet(mp4, out_png, small_mp4=None):
    """QA helpers for previews: 6-frame strip + a small, light copy of the video."""
    import subprocess
    import transform
    dur, _ = transform.probe(mp4)
    step = max(dur / 6, 0.5)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp4), "-vf",
                    f"fps=1/{step:.2f},scale=270:480,tile=6x1", "-frames:v", "1", str(out_png)], check=True)
    if small_mp4:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp4), "-vf", "scale=540:960",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-c:a", "aac", "-b:a", "64k",
                        str(small_mp4)], check=True)
