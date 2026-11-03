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

{style_block}

Rules:
- Only well-established facts. Never invent statistics, studies, names, prices, laws or dates.
- No medical, legal or financial advice for individuals; general education only.
- No engagement bait ("like if", "share if", "comment YES", "save this", "watch till the end").
- End with one short, genuine question to the viewer.
{hook_rules}
{format_rules}{extra_rules}

Return JSON with exactly these keys:
"hooks": exactly 3 DIFFERENT hook options, each using a different style from the hook list above, each an
    object with "style" (the style name), "hook" (on-screen opening title, max 6 words, no emojis; the topic
    must be obvious even on mute) and "intro_vo" (the first spoken 1-2 sentences, max 16 words, opening the
    video in that style and leading naturally into scene 2),
"scenes": {scene_count} objects in order, each with
    "vo": the part of the script spoken during this scene (1-2 short sentences),
    "key": the single most important word of this scene, copied exactly as it appears in "vo" (shown big on screen),
    {num_field}"search": 2-4 plain ENGLISH words describing ONE concrete, filmable subject for a real stock
              video clip that matches this scene (e.g. "dog running grass", "car engine closeup",
              "hotel pool sunset", "coins piggy bank"). No brand names, no text, no famous people.
{subject_rule}
{commons_field}{map_field}{timeline_field}{highlight_field}"caption": Facebook caption, 1-3 short lines adding value, ending with a genuine question. Max 2 emojis,
"hashtags": 3-5 relevant hashtags."""

TRUST_BLOCK = """Build trust the way good teachers do (problem first, then proof by logic):
- Open on a REAL problem or moment this audience recognises from their own life (a specific situation,
  not a generic topic). The viewer should think "that's me".
- Promise one concrete, realistic outcome they get by the end.
- Give the answer, and for each point say WHY it works in plain words (the reason is what builds trust).
- Include one honest limit or caveat (when it does not apply, or when to ask a professional).
- Sound like a helpful friend who knows the subject, not a salesperson. No hype, no income or result promises."""

SUBJECT_RULE = """              Every search phrase MUST include this page's main visual subject ({subject}) or a close
              variant, so the footage clearly fits the page (e.g. "{subject} closeup", "{subject} at night")."""

COMMONS_FIELD = """    "commons": (optional) when the scene names a specific famous artwork, historic photograph, old map or
              ancient artifact that is public domain (e.g. "The Starry Night Van Gogh", "Mona Lisa",
              "Rosetta Stone", "1889 Eiffel Tower photograph"), its exact name for a Wikimedia Commons search;
              otherwise "". Use it for at most half of the scenes.
"""

TIMELINE_FIELD = """"timeline": a list for an animated timeline shown at the end, used when the video compares WHEN things
              happened: 2 to 5 objects in chronological order, each {"year": "1096" or "around 1325" or "1500s" (max 14
              characters), "label": "max 4 words"}. Every year must match the voice-over exactly. [] if the video is not
              about dates.
"""

MAP_FIELD = """    "map": (optional, at most 2 scenes) only when the scene is about a specific real place on Earth: an object
              {"place": "Giza, Egypt", "lat": 29.98, "lon": 31.13} with the place's accurate coordinates; add
              "from_place", "from_lat", "from_lon" only for a real journey or route between two places. Otherwise null.
"""

HIGHLIGHT_FIELD = """"highlights": 2-6 key names and dates copied exactly as they are spoken in the voice-over (people, places, years),
              shown in the accent colour in the captions,
"""

PAIR_NOTE = """              Mark the two events that the twist connects with "pair": true (exactly two items).
"""

HOOK_RULES = """
HOOKS AND RETENTION (patterns used by the most-watched short-form creators; use the patterns, never copy their words):
- The first 2-3 seconds decide everything. The on-screen hook + first spoken line must make the topic obvious
  instantly, even with the sound off, and use plain words a 12-year-old understands.
- Anchor it in something the audience already knows (a famous brand, place, object, everyday habit).
- Promise only what the video truly delivers; the payoff must match the hook (no bait, no fake shock).
- Hook styles to choose from:
  curiosity_gap ("Most people get this wrong about X"), myth_bust ("Stop doing X"), surprising_fact (a verified,
  surprising number or fact up front), end_first (show/say the result or answer first, then how), direct_question
  ("Did you know...?" / "Why does X...?"), pain_point (a specific moment the viewer lives: "If your cat does X..."),
  familiar_anchor (start from something famous and twist it), time_parallel ("While X was happening, Y...").
- Keep it moving: every 3-5 seconds a new beat (a "but...", "so...", a new fact, a new image). Save the most
  surprising point for last, and end on a line that makes the start feel worth rewatching.
- The FIRST spoken word starts the hook. No greeting, no page name, no "in this video", no "hey guys", no
  throat-clearing. Say on screen and out loud the same idea (sound-on and sound-off viewers both get it).
- Open a loop in the first line (a question or promise that is only fully answered in the last scene) and
  close it at the end. Halfway through, re-hook with a turn ("But here's the part most people miss...").
- The last sentence should lead naturally back into the first one, so an automatic replay feels seamless.
- Scene 1 footage ("search") must be the most eye-catching, MOVING shot of the exact thing the hook names.
  Where it fits naturally, show a person or hands doing something in scene 1 (people on screen in the first
  3 seconds hold viewers longer). Never open on a static, empty or generic shot.
"""

JUDGE_PROMPT = """Three opening hooks were written for a short faceless Reel on the Facebook Page "{brand}" (audience:
{audience}). The video is about: {headline}.
{options}
Pick the ONE most likely to stop a scrolling viewer in the first 2 seconds AND keep them watching, judged on:
instantly clear on mute, specific and concrete, anchored in something familiar, emotionally intriguing, honest (the
video can deliver it), and right for this audience. {history}
Reply with JSON: {{"pick": 1, 2 or 3, "why": "one short sentence"}}"""


def pick_hook(page, data, card):
    """Chooses the strongest of the 3 hook options; falls back to the first. Sets hook + scene-1 voice-over."""
    import transform
    from google.genai import types
    opts = [h for h in (data.get("hooks") or []) if isinstance(h, dict) and str(h.get("hook", "")).strip()
            and str(h.get("intro_vo", "")).strip()]
    if not opts:
        return data
    best = 0
    if len(opts) > 1:
        lines = "\n".join(f"{i + 1}. [{o.get('style', '')}] on-screen: {o['hook']} | spoken: {o['intro_vo']}"
                          for i, o in enumerate(opts))
        try:
            resp, _ = transform.generate(transform._gemini_client(), JUDGE_PROMPT.format(
                brand=page["brand"], audience=page.get("audience", ""), headline=card.get("headline", ""),
                options=lines, history=page.get("_hook_hint", "")),
                types.GenerateContentConfig(response_mime_type="application/json", temperature=0))
            best = max(0, min(len(opts) - 1, int(json.loads(resp.text or "{}").get("pick", 1)) - 1))
        except Exception as exc:
            log(f"[{page['key']}] hook judge skipped ({str(exc)[:80]})")
    o = opts[best]
    data["hook"] = str(o["hook"]).strip()
    data["hook_style"] = re.sub(r"[^a-z_]", "", str(o.get("style", "")).lower().replace(" ", "_").replace("-", "_")) or "other"
    if data.get("scenes"):
        data["scenes"][0]["vo"] = str(o["intro_vo"]).strip()
    log(f"[{page['key']}] hook ({data['hook_style']}): {data['hook']} | options: "
        + " / ".join(f"{x.get('style')}: {x.get('hook')}" for x in opts))
    return data


STORY_RULES = "- Spoken script 50-70 words in total (about 20-28 seconds), natural and conversational, short sentences."
LIST_RULES = """- FORMAT: a numbered list of exactly {n} practical points ("Number one...", "Number two..."),
  most surprising or most useful point LAST so people keep watching. Each point = what to do + why it works.
- Spoken script 75-95 words in total (about 30-35 seconds), natural and conversational, short sentences.
  Each point is ONE punchy sentence of what to do + a short reason. No filler between points."""

W, H, FPS = 1080, 1920, 30


def pick_opener(page):
    """Rotates the page's signature openers so the same one never runs twice in a row (posts are hours apart,
    and the slot gaps never share a multiple of the list length)."""
    import time
    ops = page["image"].get("openers") or []
    return ops[int(time.time() // 3600) % len(ops)] if ops else ""


def write_script(page, card):
    import transform
    from google.genai import types
    client = transform._gemini_client()
    details = " ".join([str(card.get("body") or "")] + [str(b) for b in card.get("bullets") or []]).strip()
    if card.get("_facts"):
        details += ("\nVerified facts (use ONLY these numbers/claims; attribute claims that are not settled fact, "
                    "e.g. a company's own figures, to their source): " + card["_facts"])
    part = card.get("_part") or {}
    if part.get("n") == 1:
        details += ("\nThis Reel is PART 1 of 2 (Part 2 posts tomorrow). Deliver a real, satisfying answer, then set up "
                    f"Part 2 honestly; do not reveal what Part 2 covers: {part.get('plan', '')}. Do not say 'Part 1' "
                    "or 'follow'; those lines are added automatically.")
    elif part.get("n") == 2:
        details += (f"\nThis Reel is PART 2 of 2. Part 1 was: \"{part.get('prev', '')}\". Open with a one-line recap of "
                    "Part 1 so new viewers follow along, then deliver the promised reveal. Do not say 'Part 2' or "
                    "'follow'; those lines are added automatically.")
    if card.get("_issues"):
        details += ("\nA fact-checker rejected the previous draft for these reasons - fix every one: "
                    + "; ".join(map(str, card["_issues"])))
    as_list = use_list(page, card)
    casefile = page["image"].get("look") == "casefile"
    opener = pick_opener(page)
    n = random.choice([3, 3, 4])  # short lists hold viewers; 5-point Reels ran 55-70s
    subject = page["image"].get("reel_subject") or page["image"].get("reel_fallback_query", "")
    extra = page["image"].get("extra_rules")
    prompt = PROMPT.format(brand=page["brand"], audience=page["audience"],
                           style_block=(page["image"].get("style_block") or TRUST_BLOCK) + (
                               "\n\nNARRATOR (write every spoken line in this character's voice):\n"
                               + page["image"]["narrator"] if page["image"].get("narrator") else "") + (
                               f"\nOpen this Reel with a first line in the spirit of: \"{opener}\" (reword it naturally; "
                               "the hook itself must still land within the first words)." if opener else ""),
                           subject_rule=SUBJECT_RULE.format(subject=subject) if page["image"].get("reel_subject")
                           else "              Pick footage that clearly shows the place, object or era named in the scene.",
                           extra_rules=("\nPage-specific rules (they override the general rules above where they "
                                        "conflict):\n" + extra) if extra else "",
                           language=page["image"].get("language") or page["language"],
                           headline=card["headline"], details=details or "-",
                           format_rules=LIST_RULES.format(n=n) if as_list else STORY_RULES,
                           hook_rules=HOOK_RULES,
                           scene_count=f"{n + 2} (1 intro scene, {n} numbered scenes, 1 closing scene)" if as_list
                           else "4 to 6",
                           num_field='"num": the point number (1..%d) for numbered scenes, 0 for intro/closing,\n    ' % n
                           if as_list else "",
                           commons_field=COMMONS_FIELD if page["image"].get("commons") else "",
                           map_field=MAP_FIELD if casefile else "",
                           highlight_field=HIGHLIGHT_FIELD if casefile else "",
                           timeline_field=(TIMELINE_FIELD + (PAIR_NOTE if casefile else ""))
                           if page["image"].get("timeline") else "")
    base = int(page["image"].get("max_words") or 70)  # Taglish pages speak fewer words per second
    budget = base + 25 if as_list else base
    ask = prompt
    for attempt in range(3):
        resp, _model = transform.generate(client, ask, types.GenerateContentConfig(
            response_mime_type="application/json", temperature=0.8))
        try:
            data = json.loads(resp.text or "{}")
        except Exception:
            data = {}
        if isinstance(data, list):
            data = data[0] if data and isinstance(data[0], dict) else {}
        scenes = [s for s in (data.get("scenes") or []) if isinstance(s, dict)
                  and str(s.get("vo", "")).strip() and str(s.get("search", "")).strip()]
        if (data.get("hooks") or data.get("hook")) and 3 <= len(scenes) <= 8:
            data["scenes"] = scenes
            data = pick_hook(page, data, card)
            if not data.get("hook"):
                log(f"[{page['key']}] explainer script without a usable hook, asking again")
                continue
            words = sum(len(str(sc["vo"]).split()) for sc in scenes)
            if words > budget * 1.2 and attempt < 2:
                log(f"[{page['key']}] explainer script too long ({words} words, max {budget}), asking again")
                ask = (prompt + f"\n\nIMPORTANT: your previous script was {words} spoken words. The hard limit is "
                       f"{budget} words in total. Short Reels keep viewers; cut filler, keep the best points.")
                continue
            data["total"] = n if as_list else 0
            data["timeline"] = clean_timeline(data.get("timeline")) if page["image"].get("timeline") else []
            if not as_list:
                for sc in scenes:
                    sc.pop("num", None)
            return data
        log(f"[{page['key']}] explainer script incomplete, asking again")
    raise RuntimeError("explainer script missing scenes")


def clean_timeline(items):
    """2-5 short {year, label} items for the animated end timeline; anything malformed drops the timeline."""
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        year, label = str(it.get("year") or "").strip(), str(it.get("label") or "").strip()
        if year and label and len(year) <= 14:
            out.append({"year": year, "label": " ".join(label.split()[:5])[:32], "pair": bool(it.get("pair"))})
    return out if 2 <= len(out) <= 5 else []


def use_list(page, card):
    """Numbered-list Reels for practical topics (tips/myths), plus a share of the rest."""
    share = float(page["image"].get("list_share", 0.5))
    if share <= 0:
        return False
    return str(card.get("type", "")) in ("tips", "myth") or random.random() < share


GENERIC = {"home", "house", "closeup", "close", "view", "scene", "person", "people", "modern", "indoor",
           "outdoor", "background", "shot", "footage", "video", "inside", "small", "large", "beautiful"}
MAX_LOOKS = 4      # Gemini thumbnail checks per scene (lean plan)
MAX_STILLS = 3     # scenes that may fall back to the post's own (already checked) photo


def _queries(search, fallback):
    """Most specific first: full phrase, word pairs, then each concrete word, then the page's fallback."""
    words = [w for w in str(search).split() if w]
    qs = [" ".join(words), " ".join(words[:2]), " ".join(words[-2:])]
    qs += [w for w in words if len(w) > 3 and w.lower() not in GENERIC]
    qs.append(fallback)
    out = []
    for q in qs:
        if q and q.lower() not in [x.lower() for x in out]:
            out.append(q)
    return out


def _pixabay_videos(q, key):
    import requests
    try:
        r = requests.get("https://pixabay.com/api/videos/", timeout=30, params={
            "key": key, "q": q[:100], "safesearch": "true", "per_page": 30, "video_type": "film"})
        if not r.ok:
            log(f"pixabay video search '{q}' failed: {r.status_code} {r.text[:80]}")
            return []
        return [dict(h, id=f"pv{h['id']}") for h in r.json().get("hits", [])
                if (h.get("videos") or {}).get("medium", {}).get("url")]
    except Exception as exc:
        log(f"pixabay video search '{q}' failed: {str(exc)[:80]}")
        return []


def _pexels_videos(q, key):
    """Pexels video search, reshaped like Pixabay hits (tags come from the video's page name)."""
    import requests
    if not key:
        return []
    try:
        r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": key}, timeout=30,
                         params={"query": q[:100], "per_page": 30, "size": "medium"})
        if not r.ok:
            log(f"pexels video search '{q}' failed: {r.status_code}")
            return []
        out = []
        for v in r.json().get("videos", []):
            files = [f for f in v.get("video_files") or [] if f.get("link") and f.get("file_type") == "video/mp4"
                     and 700 <= min(f.get("width") or 0, f.get("height") or 0) <= 1300]
            if not files:
                continue
            f = min(files, key=lambda f: (f.get("width") or 0) * (f.get("height") or 0))
            slug = re.sub(r"\d+/?$", "", str(v.get("url", "")).rstrip("/").rsplit("/", 1)[-1])
            out.append({"id": f"pxv{v['id']}", "tags": ", ".join(w for w in slug.split("-") if w),
                        "videos": {"medium": {"url": f["link"], "width": f.get("width") or 0,
                                              "height": f.get("height") or 0, "thumbnail": v.get("image")}}})
        return out
    except Exception as exc:
        log(f"pexels video search '{q}' failed: {str(exc)[:80]}")
        return []


def find_clips(page, scenes, used_ids, still=None):
    """One stock video per scene from Pixabay + Pexels. Every clip must be tagged for the scene AND pass a
    visual check (Gemini looks at the thumbnail); off-topic clips are never used. If nothing fits, up to two
    scenes reuse the post's own photo (already checked) as a slow-zoom still; otherwise the Reel is skipped."""
    pkey = os.environ.get("PIXABAY_API_KEY", "").strip()
    xkey = os.environ.get("PEXELS_API_KEY", "").strip()
    if not pkey and not xkey:
        raise RuntimeError("no PIXABAY_API_KEY / PEXELS_API_KEY")
    fallback = page["image"].get("reel_fallback_query") or page["brand"]
    must = [w.lower() for w in str(page["image"].get("reel_subject") or "").split() if len(w) > 2]
    picked, taken, stills = [], set(used_ids), 0
    for sc in scenes:
        hit = None
        if page["image"].get("commons") and str(sc.get("commons") or "").strip():
            hit = commons_image(str(sc["commons"]).strip(), taken)
            if hit:
                taken.add(hit["id"])
                picked.append(hit)
                continue
        looks = 0
        for q in _queries(sc["search"], fallback):
            want = [w.lower() for w in q.split() if len(w) > 2 and w.lower() not in GENERIC] or \
                   [w.lower() for w in q.split()]
            cands = [h for h in (_pixabay_videos(q, pkey) if pkey else []) + _pexels_videos(q, xkey)
                     if h["id"] not in taken and _relevant(h.get("tags", ""), want, must, page["image"].get("place_guard"))]
            if not cands:
                continue
            vertical = [h for h in cands if h["videos"]["medium"].get("height", 0) > h["videos"]["medium"].get("width", 1)]
            pool = (vertical or cands)[:10]
            random.shuffle(pool)
            for h in pool[:3]:
                looks += 1
                if _fits(h, q):  # judged against the search that found it (always a word from the scene or page)
                    hit = h
                    break
                if looks >= MAX_LOOKS:
                    break
            if hit or looks >= MAX_LOOKS:
                break
        log(f"[{page['key']}] clip for '{sc['search']}': " + (f"{hit['id']} after {looks} look(s)" if hit
                                                              else f"none fitted ({looks} looked at)"))
        if not hit and still and stills < MAX_STILLS:
            stills += 1
            hit = {"id": f"st{stills}", "image_url": "still", "image_path": still, "tags": "post photo"}
            log(f"[{page['key']}] no fitting clip for '{sc['search']}', using the post photo for this scene")
        if not hit:
            hit = _reuse_clip([c for c in picked if c])
            if hit:
                log(f"[{page['key']}] no fitting clip for '{sc['search']}', reusing {hit['id']} from {hit['offset']:.0f}s")
        if not hit:
            picked.append(None)  # filled after the loop from a later scene's clip (e.g. scene 1 had no match)
            continue
        if not hit.get("reused"):
            taken.add(hit["id"])
        picked.append(hit)
    for i, c in enumerate(picked):
        if c is None:
            # on-topic footage from this Reel first; the page's generic subject clip only when nothing else exists
            # (a generic shot during a specific topic gets the Reel blocked by video QA)
            hit = _reuse_clip([x for x in picked if x]) or _fallback_clip(page, fallback, must, taken)
            if not hit:
                raise RuntimeError(f"no fitting stock clip for '{scenes[i]['search']}'")
            log(f"[{page['key']}] no fitting clip for '{scenes[i]['search']}', using {hit['id']}"
                + (f" from {hit['offset']:.0f}s" if hit.get("offset") else ""))
            if not hit.get("reused"):
                taken.add(hit["id"])
            picked[i] = hit
    return picked


def _fallback_clip(page, fallback, must, taken):
    """Second chance for a scene: a clip of the page's own main subject (e.g. 'dog cat pet', 'elderly hands'),
    still checked by Gemini. A clean on-brand shot beats dropping the whole Reel to a static card, which is
    what lost most viewers in the first 2 seconds (Oct 2026 data)."""
    pkey = os.environ.get("PIXABAY_API_KEY", "").strip()
    xkey = os.environ.get("PEXELS_API_KEY", "").strip()
    looks = 0
    for q in [x for x in [fallback, " ".join(fallback.split()[:2]), fallback.split()[0] if fallback else ""] if x]:
        want = [w.lower() for w in q.split() if len(w) > 2] or [q.lower()]
        cands = [h for h in (_pixabay_videos(q, pkey) if pkey else []) + _pexels_videos(q, xkey)
                 if h["id"] not in taken and _relevant(h.get("tags", ""), want, must, page["image"].get("place_guard"))]
        vertical = [h for h in cands if h["videos"]["medium"].get("height", 0) > h["videos"]["medium"].get("width", 1)]
        pool = (vertical or cands)[:8]
        random.shuffle(pool)
        for h in pool[:2]:
            looks += 1
            if _fits(h, q):
                log(f"[{page['key']}] fallback clip '{q}' -> {h['id']}")
                return h
            if looks >= 3:
                return None
    return None


def _reuse_clip(picked):
    """Last resort: a later part of a clip already used in this Reel (different moment, so it does not look
    like a repeat). Stills and public-domain images are never reused."""
    vids = [c for c in picked if not c.get("image_url") and not c.get("reused")]
    if not vids:
        return None
    src = vids[len(picked) % len(vids)]
    n = sum(1 for c in picked if c.get("reused") and c["id"] == src["id"]) + 1
    return dict(src, reused=True, offset=float(4 * n))


WIKI_UA = {"User-Agent": "HistoryDecodedBot/1.0 (https://www.facebook.com/61595243776702; freeguideshub@gmail.com) python-requests"}


def _commons_file(urls, wid):
    """Downloads a Commons image and checks it really is a picture (Wikimedia sometimes answers bots with
    an error page). Returns a local, normalised JPEG path or None. ffmpeg never sees a broken file."""
    import io
    import tempfile
    import requests
    from PIL import Image
    for url in [u for u in urls if u]:
        try:
            r = requests.get(url, headers=WIKI_UA, timeout=60)
            r.raise_for_status()
            im = Image.open(io.BytesIO(r.content))
            im.load()
            im = im.convert("RGB")
            im.thumbnail((1600, 1600))
            if min(im.size) < 300:
                continue
            path = Path(tempfile.gettempdir()) / f"{wid}.jpg"
            im.save(path, "JPEG", quality=92)
            return str(path)
        except Exception as exc:
            log(f"commons download failed ({str(exc)[:100]}): {url[:90]}")
    return None
PD_LICENSES = ("public domain", "pd-", "cc0", "pdm")


def _title_matches(query, title):
    """The Commons file name must share at least one real word with the query (a name, place or year), so a search
    for a person never returns an unrelated building whose page merely mentions him."""
    import unicodedata
    norm = lambda x: unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode().lower()
    stop = {"the", "and", "of", "de", "los", "las", "del", "y", "la", "el", "portrait", "photograph", "photo",
            "painting", "image", "picture", "century", "old", "historic", "file", "jpg", "png"}
    q = {w for w in re.findall(r"[a-z0-9]+", norm(query)) if len(w) > 2 and w not in stop}
    t = set(re.findall(r"[a-z0-9]+", norm(title)))
    return not q or bool(q & t)


def commons_image(query, taken=()):
    """A public-domain still (artwork, historic photo, map) from Wikimedia Commons, checked by Gemini.
    Returns a clip-like dict {id, image_url, tags, credit} or None."""
    import requests
    try:
        r = requests.get("https://commons.wikimedia.org/w/api.php", headers=WIKI_UA, timeout=30, params={
            "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
            "gsrsearch": f"filetype:bitmap {query}", "gsrlimit": 8, "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 1600})
        pages = sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    except Exception as exc:
        log(f"commons search failed: {str(exc)[:120]}")
        return None
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic = " ".join(str((meta.get(k) or {}).get("value", "")) for k in ("LicenseShortName", "License")).lower()
        wid = f"wc{p.get('pageid')}"
        if wid in taken or not any(x in lic for x in PD_LICENSES):
            continue
        if not _title_matches(query, p.get("title", "")):
            continue
        if info.get("mime") not in ("image/jpeg", "image/png") or min(info.get("width", 0), info.get("height", 0)) < 600:
            continue
        url = info.get("thumburl") or info.get("url")
        path = _commons_file([url, info.get("url")], wid)
        if not path or not _shows({"videos": {"medium": {"thumbnail": url}}}, [query], path):
            continue
        artist = re.sub(r"<[^>]+>", "", str((meta.get("Artist") or {}).get("value", ""))).strip()[:60]
        log(f"commons: '{query}' -> {p.get('title')} ({lic[:30]})")
        return {"id": wid, "image_url": url, "image_path": path, "tags": str(p.get("title", "")), "credit": artist}
    return None


BLOCK = {"military", "soldier", "soldiers", "army", "war", "weapon", "gun", "police", "blood",
         "funeral", "protest", "bikini", "lingerie", "alcohol", "beer", "wine", "cigarette", "smoking"}


PLACES = {"dubai", "burjkalifa", "burjkhalifa", "uae", "emirate", "emirates", "abudhabi", "qatar", "doha", "saudi",
          "newyork", "nyc", "manhattan", "usa", "america", "london", "paris", "france", "italy", "rome", "venice",
          "spain", "germany", "tokyo", "japan", "seoul", "korea", "china", "beijing", "shanghai", "hongkong",
          "singapore", "bangkok", "thailand", "vietnam", "bali", "indonesia", "india", "mumbai", "istanbul",
          "turkey", "egypt", "cairo", "mosque", "hijab", "quran", "philippines", "manila", "cebu", "philippine"}


def _relevant(tags, want, must=(), guard=False):
    """Clip tags must mention the page's subject (e.g. 'car'), at least one search word,
    and nothing off-brand. A clip tagged with a specific place (Dubai, Tokyo...) is only used when the search
    names that same place, so 'Manila skyline' never gets the Burj Khalifa (pages with image.place_guard)."""
    tl = {t.strip().lower() for t in str(tags).replace(",", " ").split()}
    if tl & BLOCK:
        return False
    wl = {w.lower() for w in want}
    if guard and (tl & PLACES) - wl and not (tl & wl & PLACES):
        return False
    hit = lambda w: any(t in (w, w + "s", w + "es") or (len(w) > 3 and len(t) > 3 and (w in t or t in w))
                        for t in tl)
    if must and not any(hit(w) for w in must):
        return False
    return any(hit(w) for w in want)


def _shows(hit, subject, local=None):
    """True if the clip's thumbnail (or a local image file) clearly shows the subject (checked by Gemini).
    Errors -> True."""
    import requests
    import transform
    from google.genai import types
    thumb = (hit.get("videos") or {}).get("medium", {}).get("thumbnail")
    if not thumb and not local:
        return True
    try:
        if local:
            data = Path(local).read_bytes()
        else:
            img = requests.get(thumb, timeout=20)
            img.raise_for_status()
            data = img.content
        resp, _ = transform.generate(transform._gemini_client(), [
            types.Part.from_bytes(data=data, mime_type="image/jpeg"),
            f"Is a {' or '.join(subject)} clearly visible in this image? Answer only YES or NO."],
            types.GenerateContentConfig(temperature=0))
        return "YES" in (resp.text or "").upper()
    except Exception as exc:
        log(f"thumbnail check skipped ({str(exc)[:80]})")
        return True


FIT_PROMPT = """This is a thumbnail of a stock video clip. The clip is for a scene described as: "{scene}".
Does the clip clearly show the MAIN SUBJECT of that description (the thing or animal a viewer must see, e.g. the
dog, the car, the mop, the air conditioner)? The exact action, angle or setting may differ. Answer NO if the main
subject is missing or it is mainly something unrelated (another animal, a random street, a person exercising).
Answer only YES or NO."""


def _fits(hit, scene):
    """Lenient but honest visual check for a stock clip: main subject visible. Errors -> True."""
    import requests
    import transform
    from google.genai import types
    thumb = (hit.get("videos") or {}).get("medium", {}).get("thumbnail")
    if not thumb:
        return True
    try:
        img = requests.get(thumb, timeout=20)
        img.raise_for_status()
        resp, _ = transform.generate(transform._gemini_client(), [
            types.Part.from_bytes(data=img.content, mime_type="image/jpeg"), FIT_PROMPT.format(scene=scene)],
            types.GenerateContentConfig(temperature=0))
        return "YES" in (resp.text or "").upper()
    except Exception as exc:
        log(f"clip check skipped ({str(exc)[:80]})")
        return True


def _download(url, dest):
    import requests
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)


def _hex(c):
    return "0x" + c.lstrip("#").upper()


def _seek(src, offset):
    """Start point for a reused clip: the wanted offset, wrapped inside the clip's length."""
    import subprocess
    try:
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                    "default=nw=1:nk=1", str(src)], capture_output=True, text=True, timeout=30).stdout)
    except Exception:
        return 0.0
    return (offset % dur) if dur > 1 else 0.0


_WHISPER = {}


def _norm_word(w):
    import unicodedata
    w = unicodedata.normalize("NFKD", str(w)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", w)


def align_words(wav, script_words, page):
    """Start time (seconds from the start of the voice-over) of every script word, found by listening to the
    audio with a small Whisper model (faster-whisper, MIT, CPU) and matching what it heard to the script.
    Words it missed are filled in between their neighbours. Returns None when alignment is not possible, and
    the old estimate is used instead."""
    if not script_words or os.environ.get("ALIGN_CAPTIONS", "1") == "0":
        return None
    try:
        from faster_whisper import WhisperModel
        if "m" not in _WHISPER:
            _WHISPER["m"] = WhisperModel(os.environ.get("ALIGN_MODEL", "base"), device="cpu", compute_type="int8")
        lang = "tl" if "taglish" in str(page["image"].get("language") or page.get("language") or "").lower() else "en"
        import subprocess
        import numpy as np
        # decode with ffmpeg ourselves (faster-whisper's own decoder breaks with newer PyAV versions)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                             capture_output=True, check=True, timeout=120).stdout
        audio = np.frombuffer(raw, dtype=np.float32)
        segs, _ = _WHISPER["m"].transcribe(audio, language=lang, word_timestamps=True, beam_size=1,
                                           condition_on_previous_text=False)
        heard = [(w.word, float(w.start)) for sg in segs for w in (sg.words or [])]
    except Exception as exc:
        log(f"[{page['key']}] caption alignment skipped ({str(exc)[:100]})")
        return None
    return match_times(script_words, heard, page["key"])


def match_times(script_words, heard, key=""):
    """Maps heard (word, start) pairs onto the script words; interpolates the gaps; None if too little matched."""
    import difflib
    a = [_norm_word(w) for w in script_words]
    b = [_norm_word(w) for w, _ in heard]
    times = [None] * len(a)
    for i, j, n in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(n):
            if a[i + k]:
                times[i + k] = heard[j + k][1]
    known = [i for i, t in enumerate(times) if t is not None]
    if len(known) < max(3, 0.35 * len(a)):
        log(f"[{key}] caption alignment: only {len(known)}/{len(a)} words matched, using estimate")
        return None
    # keep anchors in order (drop any that go backwards)
    clean, last = [], -1.0
    for i in known:
        if times[i] > last:
            clean.append(i)
            last = times[i]
        else:
            times[i] = None
    first, lastk = clean[0], clean[-1]
    rate = (times[lastk] - times[first]) / max(lastk - first, 1)
    for i in range(first):
        times[i] = max(0.0, times[first] - rate * (first - i))
    for x, y in zip(clean, clean[1:]):
        for i in range(x + 1, y):
            times[i] = times[x] + (times[y] - times[x]) * (i - x) / (y - x)
    for i in range(lastk + 1, len(a)):
        times[i] = times[lastk] + rate * (i - lastk)
    log(f"[{key}] caption alignment: {len(clean)}/{len(a)} words matched to the audio")
    return [round(t, 3) for t in times]


def render(page, script, clips, out_path, clip_paths=None):
    """clip_paths lets tests pass local files instead of downloading."""
    import transform
    work = Path(tempfile.mkdtemp(prefix="expl_"))
    full = " ".join(str(s["vo"]).strip() for s in script["scenes"])
    wav = work / "vo.wav"
    vo_len = transform.speak(full, page, wav)
    engine = page["image"].get("render_engine") or os.environ.get("RENDER_ENGINE", "ffmpeg")
    lead, tail = 0.3, (1.9 if engine == "remotion" else 0.9)
    total = lead + vo_len + tail
    words = [max(len(str(s["vo"]).split()), 1) for s in script["scenes"]]
    shares = [w / sum(words) * vo_len for w in words]
    shares[0] += lead
    shares[-1] += tail
    # real word timings from the audio (captions and scene cuts follow the actual speech, not an estimate)
    script["_word_times"] = align_words(wav, full.split(), page)
    if script["_word_times"]:
        starts, k = [], 0
        for n in [len(str(s["vo"]).split()) for s in script["scenes"]]:
            starts.append(script["_word_times"][min(k, len(full.split()) - 1)])
            k += n
        cuts = [0.0] + [lead + max(t - 0.12, 0) for t in starts[1:]] + [total]
        aligned = [b - a for a, b in zip(cuts, cuts[1:])]
        if all(d > 0.4 for d in aligned):
            shares = aligned

    segs = []
    for i, (d, clip) in enumerate(zip(shares, clips)):
        seg = work / f"seg{i}.mp4"
        if clip.get("image_url") and not clip_paths:
            # public-domain still: whole picture on a blurred copy of itself, slow push-in
            img = Path(clip.get("image_path") or "")
            if not img.is_file():
                raise RuntimeError(f"commons image missing for scene {i + 1}")
            frames = max(int(d * FPS), 1)
            transform._run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS), "-i", str(img), "-t", f"{d:.3f}",
                            "-filter_complex",
                            f"[0]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:2,"
                            f"eq=brightness=-0.12[bg];[0]scale={W - 60}:{H - 500}:force_original_aspect_ratio=decrease[fg];"
                            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,scale={int(W * 1.12)}:-2,"
                            f"zoompan=z='min(1+0.0008*on,1.08)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                            f"s={W}x{H}:fps={FPS},setsar=1,format=yuv420p",
                            "-frames:v", str(frames), "-an", *transform.VCODEC, str(seg)])
            segs.append(seg)
            continue
        src = Path(clip_paths[i]) if clip_paths else work / f"src{i}.mp4"
        if not clip_paths:
            _download(clip["videos"]["medium"]["url"], src)
        seek = ["-ss", f"{_seek(src, clip.get('offset', 0)):.2f}"] if clip.get("offset") else []
        transform._run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", *seek, "-i", str(src),
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

    if engine == "remotion":
        try:
            render_remotion(page, script, shares, lead, vo_len, total, joined, wav, out_path, work)
            log(f"[{page['key']}] explainer reel {total:.1f}s, {len(segs)} scenes (remotion)")
            return total
        except Exception as exc:
            log(f"[{page['key']}] remotion render failed, using ffmpeg overlay: {str(exc)[-300:]}")

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
          f"subtitles={caps}" + transform._brand(page) + transform._follow(dict(page, follow_cta=script.get("_outro") or page.get("follow_cta")), work, total))
    transform._run(["ffmpeg", "-y", "-v", "error", "-i", str(joined), "-i", str(wav),
                    "-filter_complex",
                    f"[0:v]{vf}[v];[1:a]adelay={int(lead * 1000)}|{int(lead * 1000)},"
                    "aresample=48000,pan=stereo|c0=c0|c1=c0,apad[a]",
                    "-map", "[v]", "-map", "[a]", "-t", f"{total:.2f}",
                    *transform.VCODEC, *transform.ACODEC, "-movflags", "+faststart", str(out_path)])
    log(f"[{page['key']}] explainer reel {total:.1f}s, {len(segs)} scenes")
    return total


REMOTION_DIR = Path(__file__).resolve().parent / "remotion"
FONT_DIR = Path(__file__).resolve().parent / "fonts"


def _num(x, lo, hi):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if lo <= v <= hi else None


def casefile_props(page, script, pub, total):
    """Extra props for the "case file" look: theme, stamp, file label, map per scene, highlights, sound files."""
    import shutil
    img = page["image"]
    if img.get("look") != "casefile":
        return {}
    cf = img.get("casefile") or {}
    full = " ".join(str(s.get("vo", "")) for s in script.get("scenes", [])).lower()
    hl = [str(h).strip() for h in (script.get("highlights") or []) if str(h).strip() and str(h).strip().lower() in full][:6]
    maps = []
    for sc in script.get("scenes", []):
        m = sc.get("map") if isinstance(sc.get("map"), dict) else None
        lat, lon = (_num(m.get("lat"), -85, 85), _num(m.get("lon"), -180, 180)) if m else (None, None)
        if m and lat is not None and lon is not None and str(m.get("place") or "").strip():
            mm = {"place": str(m["place"]).strip()[:34], "lat": lat, "lon": lon}
            flat, flon = _num(m.get("from_lat"), -85, 85), _num(m.get("from_lon"), -180, 180)
            if flat is not None and flon is not None and str(m.get("from_place") or "").strip():
                mm.update(fromPlace=str(m["from_place"]).strip()[:24], fromLat=flat, fromLon=flon)
            maps.append(mm if sum(1 for x in maps if x) < 2 else None)
        else:
            maps.append(None)
    music = None
    try:
        import sound
        sound.sfx(pub)
        sound.ambient_music(pub / "music.wav", total)
        music = "music.wav"
    except Exception as exc:
        log(f"[{page['key']}] sound design skipped ({str(exc)[:100]})")
    cap = FONT_DIR / (cf.get("caption_font") or "Inter-SemiBold.ttf")
    shutil.copy(cap if cap.exists() else FONT_DIR / "Poppins-Bold.ttf", pub / "caption.ttf")
    return {
        "look": "casefile", "maps": maps, "highlights": hl, "music": music, "sfx": music is not None,
        "stamp": str(cf.get("stamp") or "LITTLE-KNOWN"),
        "fileLabel": f"{cf.get('file_word') or 'FILE'} {int(script.get('_file_no') or 1):03d}",
        "cf": {"accent": cf.get("accent", "#E0A33A"), "paper": cf.get("paper", "#EADBC0"),
               "paperDark": cf.get("paper_dark", "#D3BC92"), "ink": cf.get("ink", "#2A1F14"),
               "stamp": cf.get("stamp_color", "#B3261E"), "text": "#FFFFFF", "shade": cf.get("shade", "#6B4A22")},
    }


def master_audio(path):
    """Loudness mastering (about -14 LUFS, the level Facebook/YouTube normalise to), video copied untouched."""
    import subprocess
    tmp = Path(str(path) + ".m.mp4")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-c:v", "copy", "-af",
                        "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "aac", "-b:a", "160k",
                        "-movflags", "+faststart", str(tmp)], capture_output=True, text=True, timeout=300)
    if r.returncode == 0 and tmp.exists():
        tmp.replace(path)
    else:
        log(f"audio mastering skipped ({(r.stderr or '')[-120:]})")


def render_remotion(page, script, shares, lead, vo_len, total, joined, wav, out_path, work):
    """Animated overlays (hook, counters, keyword pops, karaoke captions, outro) via Remotion."""
    import shutil
    import subprocess
    th = page["image"]["theme"]
    pub = work / "public"
    pub.mkdir(exist_ok=True)
    shutil.copy(joined, pub / "joined.mp4")
    shutil.copy(wav, pub / "vo.wav")
    for src, dst in ((th.get("title_font", "Anton.ttf"), "title.ttf"), (th.get("body_font", "Poppins-Bold.ttf"), "body.ttf")):
        f = FONT_DIR / src
        shutil.copy(f if f.exists() else FONT_DIR / "Poppins-Bold.ttf", pub / dst)
    scenes, t0 = [], 0.0
    for sc, d in zip(script["scenes"], shares):
        try:
            num = int(sc.get("num") or 0)
        except (TypeError, ValueError):
            num = 0
        key = str(sc.get("key") or "").strip()
        if key and key.lower() not in str(sc["vo"]).lower():
            key = ""
        scenes.append({"start": round(t0, 3), "end": round(t0 + d, 3), "num": num, "key": key})
        t0 += d
    # spoken words spread over the voice-over only (lead .. lead+vo_len), weighted per scene
    words, spoken_t = [], lead
    scene_words = [str(sc["vo"]).split() for sc in script["scenes"]]
    allw = [w for ws in scene_words for w in ws]
    weights = [len(w) + 2 for w in allw] or [1]
    tot = sum(weights)
    real = script.get("_word_times")
    for i, (w, wt) in enumerate(zip(allw, weights)):
        t = lead + real[i] if real and i < len(real) else spoken_t
        words.append({"w": w, "t": round(t, 3)})
        spoken_t += vo_len * wt / tot
    brand = page["brand"]
    mono = th.get("monogram") or page["image"].get("monogram") or "".join(x[0] for x in brand.split()[:2]).upper()
    props = {
        "total": round(total, 3), "lead": lead, "video": "joined.mp4", "audio": "vo.wav",
        "hook": str(script["hook"]), "brand": brand, "monogram": mono,
        "outro": str(script.get("_outro") or page.get("follow_cta") or page["image"].get("footer") or "Follow for more"), "totalN": int(script.get("total") or 0),
        "scenes": scenes, "words": words,
        "intro": page["image"].get("reel_intro") or "pill", "rec": bool(page["image"].get("rec_zoom")),
        "timeline": script.get("timeline") or [],
        **casefile_props(page, script, pub, total),
        "theme": {"accent": th["accent"], "onAccent": th.get("on_accent", "#FFFFFF"),
                  "bgTop": th.get("bg_top", "#111111"), "bgBottom": th.get("bg_bottom", "#000000"),
                  "text": th.get("text", "#FFFFFF"), "titleFont": "title.ttf", "bodyFont": "body.ttf",
                  "upper": bool(th.get("upper_headline", True))},
    }
    pj = work / "props.json"
    pj.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    cmd = ["npx", "remotion", "render", "src/index.ts", "Reel", str(Path(out_path).resolve()),
           f"--props={pj}", f"--public-dir={pub}", "--codec=h264", "--crf=20",
           f"--concurrency={max(1, os.cpu_count() or 2)}", "--log=error"]
    if os.environ.get("REMOTION_BROWSER"):
        cmd.append(f"--browser-executable={os.environ['REMOTION_BROWSER']}")
    if os.environ.get("REMOTION_CHROME_MODE"):
        cmd.append(f"--chrome-mode={os.environ['REMOTION_CHROME_MODE']}")
    r = subprocess.run(cmd, cwd=REMOTION_DIR, capture_output=True, text=True,
                       timeout=int(os.environ.get("REMOTION_TIMEOUT", "2400")))
    if r.returncode != 0 or not Path(out_path).exists():
        raise RuntimeError((r.stderr or r.stdout or "no output")[-600:])
    if page["image"].get("look") == "casefile":
        master_audio(out_path)


def follow_up(page, script, card):
    """A clear reason to follow, spoken at the very end and shown on screen in the last 2 seconds.
    Part 1 of a two-part story ends with 'Part 2 is tomorrow, follow so you don't miss it'."""
    part = card.get("_part") or {}
    if part.get("n") in (1, 2) and script.get("hook") and not str(script["hook"]).lower().startswith("part"):
        script["hook"] = f"Part {part['n']}: {script['hook']}"
    if part.get("n") == 1 and card.get("_part_cta"):
        line, screen = card["_part_cta"], card.get("_part_screen") or card["_part_cta"]
    else:
        line = str(page.get("follow_line") or "").strip()
        screen = str(page.get("follow_cta") or "").strip()
    if line and script.get("scenes"):
        last = script["scenes"][-1]
        last["vo"] = str(last["vo"]).rstrip() + " " + line
    if screen:
        script["_outro"] = screen


def make(page, card, out_path, used_ids=()):
    """Script -> clips -> video. Returns (seconds, caption_message, [clip ids])."""
    script = write_script(page, card)
    if page["image"].get("fact_check"):
        import factcheck
        res = factcheck.check_script(page, script, card)
        if res is not True:
            script = write_script(page, dict(card, _issues=res))
            res = factcheck.check_script(page, script, card)
            if res is not True:
                raise RuntimeError("script failed fact-check twice: " + "; ".join(map(str, res))[:300])
    follow_up(page, script, card)
    m = re.search(r"#(\d+)", str(card.get("_series") or ""))
    script["_file_no"] = int(m.group(1)) if m else int(__import__("datetime").date.today().strftime("%j"))
    clips = find_clips(page, script["scenes"], used_ids, card.get("_still"))
    secs = render(page, script, clips, out_path)
    qa = video_qa(page, out_path, script, card)  # raises when the finished Reel must not be posted
    tags = script.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.split()
    tags = [t if str(t).startswith("#") else f"#{t}" for t in tags][:5]
    message = str(script.get("caption") or card.get("caption") or "").strip()
    if any(str(c["id"]).startswith("wc") for c in clips):
        message += "\n\nHistoric images: Wikimedia Commons (public domain)"
    if tags:
        message += "\n\n" + " ".join(tags)
    ref = lambda c: str(c["id"])
    log(f"[{page['key']}] explainer scenes: " + " | ".join(
        f"{sc['search']} -> {ref(c)} ({c.get('tags', '')[:40]})" for sc, c in zip(script["scenes"], clips)))
    return secs, message, [ref(c) for c in clips] + [f"hook:{script.get('hook_style', 'other')}", f"qa:{qa}"]


QA_PROMPT = """You are the final quality checker for a short faceless Reel on the Facebook Page "{brand}"
(audience: {audience}). Watch the whole video and listen to it.

The Reel is about: {headline}
Spoken script: {script}
Each scene was meant to show: {scenes}

Report problems a viewer would notice. Severity "block" ONLY for:
- two or more scenes whose footage is clearly unrelated to what is being said (e.g. a cat during an air-conditioner tip)
- anything inappropriate for a family audience, violent, sexual or disturbing footage
- footage that contradicts the voice-over in a misleading way
- missing or garbled voice, long black or frozen sections
- on-screen text that is badly misspelled, cut off or unreadable for more than a moment
Everything else (one weak clip, small timing issues, a generic shot) is severity "minor".

Return ONLY JSON: {{"verdict": "pass" or "block", "issues": [{{"severity": "block" or "minor", "what": "short description",
"time": "approx seconds"}}]}}"""


def video_qa(page, mp4, script, card):
    """The QA agent: Gemini watches the finished Reel before it is posted. Returns "pass", "minor" or "skipped";
    raises when it finds a blocking problem (the caller then posts the safer photo Reel instead)."""
    if not page["image"].get("video_qa", True):
        return "off"
    import subprocess
    import tempfile
    import transform
    from google.genai import types
    small = Path(tempfile.mkdtemp(prefix="qa_")) / "qa.mp4"
    try:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp4), "-vf", "scale=432:768,fps=12",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "32", "-c:a", "aac", "-b:a", "48k",
                        str(small)], check=True, timeout=300)
        if small.stat().st_size > 18 * 1024 * 1024:
            return "skipped"
        prompt = QA_PROMPT.format(
            brand=page["brand"], audience=page.get("audience", ""), headline=card.get("headline", ""),
            script=" ".join(str(s.get("vo", "")) for s in script.get("scenes", []))[:2500],
            scenes=" | ".join(str(s.get("search", "")) for s in script.get("scenes", [])))
        resp, _ = transform.generate(transform._gemini_client(), [
            types.Part.from_bytes(data=small.read_bytes(), mime_type="video/mp4"), prompt],
            types.GenerateContentConfig(response_mime_type="application/json", temperature=0))
        data = json.loads(resp.text or "{}")
    except Exception as exc:
        log(f"[{page['key']}] video QA skipped ({str(exc)[:120]})")
        return "skipped"
    issues = [i for i in (data.get("issues") or []) if isinstance(i, dict)]
    blocking = [i for i in issues if str(i.get("severity", "")).lower() == "block"]
    text = "; ".join(f"{i.get('severity')}: {i.get('what')} @{i.get('time', '?')}s" for i in issues)[:400]
    if blocking or str(data.get("verdict", "")).lower() == "block":
        log(f"[{page['key']}] video QA BLOCKED: {text}")
        raise RuntimeError(f"video QA blocked: {text[:200]}")
    log(f"[{page['key']}] video QA pass" + (f" ({text})" if text else ""))
    return "minor" if issues else "pass"


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
