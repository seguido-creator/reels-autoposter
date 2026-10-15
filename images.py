"""Image posts: original, branded "info cards" (facts, tips, myths, quotes, questions).

Gemini writes the card for the Page's niche (checking the last posts so topics don't repeat),
Pillow draws it in the Page's brand style (1080x1350, the best size for the Facebook feed),
and it is posted as a photo with a caption. Every post is logged in the "Images" tab.

  python images.py               # post for any Page whose image slot is open now
  python images.py --force PH    # post one card to PH right now
  python images.py --preview PH  # render a card to preview_PH.png without posting
"""
import argparse
import datetime as dt
import json
import os
import re
import textwrap
from pathlib import Path
from zoneinfo import ZoneInfo

from common import ROOT, load_config, log, parse_time, utcnow

W, H = 1080, 1350
FONTS = ROOT / "fonts"
LOG_TAB = "Images"
LOG_HEADER = ["page", "slot", "posted_at_utc", "type", "topic", "headline", "fb_post_id", "note"]

CARD_PROMPT = """You run the Facebook Page "{brand}". Create ONE original image post (an info card)
that people will want to save, share or comment on because it is genuinely useful or interesting.

Niche and angle: {angle}
Audience: {audience}
Language for ALL text: {language}
Card types allowed: {types}
Recent topics already posted (do NOT repeat or closely rephrase any of them):
{recent}

Rules:
- Only well-established facts. Never invent statistics, studies, names, prices, laws or dates.
  If a number is not common knowledge, leave it out.
- No medical, legal or financial advice for individuals; general education only, and say
  "talk to a professional" when it matters.
- No engagement bait ("like if", "share if", "tag someone", "comment YES", "type AMEN").
- Respectful, positive, nothing political, religious, sexual or shocking.
- Card text must be SHORT so it is readable on a phone.

Return JSON with exactly these keys:
"type": one of {types},
"topic": 3-6 word label for this topic (used to avoid repeats),
"tag": small label on top of the card, max 3 words (e.g. "DID YOU KNOW?", "QUICK TIP", "MYTH vs FACT"),
"headline": the main line, max 12 words,
"body": 1-2 sentences, max 40 words (for fact/quote/question; "" for tips/myth),
"bullets": list of 3-5 short items, max 9 words each (for tips; for myth use exactly 2 items:
    "Myth: ..." and "Fact: ..."; [] for other types),
"caption": Facebook caption, 2-4 short lines that add a little more value, ending with a
    genuine question. Max 2 emojis,
"hashtags": 3-5 relevant hashtags,
"image_prompt": a vivid description (40-70 words, in English) of ONE eye-catching, realistic
    editorial-style photo that illustrates this card's topic for this audience. Natural light,
    shallow depth of field, rich but realistic colours. Absolutely NO text, letters, numbers,
    logos, watermarks, brand names or recognisable real people/places in the image,
"photo_search": 2-4 simple English words to find a matching real stock photo
    (e.g. "golden retriever puppy", "sports car engine", "elderly hands holding tea")."""

IMAGE_STYLE = ("Photorealistic, high-end editorial photography, sharp subject, pleasing composition "
               "with the main subject in the upper two thirds of the frame. No text, no letters, "
               "no logos, no watermarks, no brand names.")


# ---------------------------------------------------------------- pages
def all_pages(cfg):
    """Reel pages that have an image block, plus image-only pages."""
    pages = [p for p in cfg["pages"] if p.get("image")]
    return pages + cfg.get("image_pages", [])


def image_slots(page, now_utc, window_hours):
    tz = ZoneInfo(page["timezone"])
    now = now_utc.astimezone(tz)
    out = []
    for day_offset in (-1, 0):
        day = (now + dt.timedelta(days=day_offset)).date()
        for slot in page["image"]["slots"]:
            hh, mm = (int(x) for x in slot.split(":"))
            start = dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
            if start <= now < start + dt.timedelta(hours=window_hours):
                out.append("img " + start.strftime("%Y-%m-%d %H:%M"))
    return out


def any_image_due(cfg, now_utc):
    return any(image_slots(p, now_utc, cfg.get("image_window_hours", 5)) for p in all_pages(cfg))


# ---------------------------------------------------------------- content
def write_card(page, recent):
    import transform
    from google.genai import types
    client = transform._gemini_client()
    style = page["image"]
    prompt = CARD_PROMPT.format(
        brand=page["brand"], angle=style.get("angle") or page.get("content_angle", ""),
        audience=page["audience"], language=style.get("language") or page["language"],
        types=", ".join(style.get("types", ["fact", "tips", "myth", "question"])),
        recent="\n".join(f"- {t}" for t in recent[-40:]) or "- (none yet)")
    resp, used = transform.generate(client, prompt, types.GenerateContentConfig(
        response_mime_type="application/json", temperature=0.9))
    data = json.loads(resp.text)
    if isinstance(data, list):
        data = data[0]
    if not str(data.get("headline", "")).strip() or not str(data.get("caption", "")).strip():
        raise RuntimeError("AI card missing headline/caption")
    data["bullets"] = [clean(b) for b in (data.get("bullets") or []) if clean(b)][:5]
    tags = data.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.split()
    data["hashtags"] = [t if t.startswith("#") else f"#{t}" for t in tags][:5]
    data["model"] = used
    return data


def stock_photo(page, card, used_ids):
    """Free real photo from Pexels (needs PEXELS_API_KEY). Picks a portrait photo for the card's
    search words that this Page hasn't used before. Returns (image, credit, photo_id) or Nones."""
    import io
    import random
    import requests
    from PIL import Image
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    query = str(card.get("photo_search") or "").strip()
    if not query:
        return None, None, None
    if not key:
        return pixabay_photo(page, query, used_ids)
    for q in (query, " ".join(query.split()[:2])):
        try:
            r = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": key},
                             params={"query": q, "orientation": "portrait", "per_page": 30},
                             timeout=30)
            r.raise_for_status()
            photos = [p for p in r.json().get("photos", []) if str(p["id"]) not in used_ids]
        except Exception as exc:
            log(f"[{page['key']}] Pexels search failed: {str(exc)[:120]}")
            return None, None, None
        if photos:
            p = random.choice(photos[:12])
            raw = requests.get(p["src"].get("large2x") or p["src"]["original"], timeout=60).content
            credit = f"Photo: {p.get('photographer', 'Pexels')} / Pexels"
            return Image.open(io.BytesIO(raw)).convert("RGB"), credit, str(p["id"])
    return pixabay_photo(page, query, used_ids)


def pixabay_photo(page, query, used_ids):
    """Free real photo from Pixabay (needs PIXABAY_API_KEY). Pixabay asks API users to download
    and re-host images (no hotlinking), which is what posting to Facebook does."""
    import io
    import random
    import requests
    from PIL import Image
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not key:
        return None, None, None
    for q in (query, " ".join(query.split()[:2])):
        try:
            r = requests.get("https://pixabay.com/api/", timeout=30, params={
                "key": key, "q": q[:100], "image_type": "photo", "orientation": "vertical",
                "safesearch": "true", "per_page": 50, "min_width": 900})
            r.raise_for_status()
            hits = [h for h in r.json().get("hits", []) if f"px{h['id']}" not in used_ids]
        except Exception as exc:
            log(f"[{page['key']}] Pixabay search failed: {str(exc)[:120]}")
            return None, None, None
        if hits:
            h = random.choice(hits[:15])
            raw = requests.get(h["largeImageURL"], timeout=60).content
            credit = f"Image: {h.get('user', 'Pixabay')} / Pixabay"
            return Image.open(io.BytesIO(raw)).convert("RGB"), credit, f"px{h['id']}"
    return None, None, None


def generate_photo(page, card, cfg):
    """Paid Gemini image model -> PIL image (4:5). Uses its own key (GEMINI_IMAGE_API_KEY) so the
    free text/voice key stays on the free tier. Returns (image, model) or (None, reason)."""
    import base64
    import io
    from PIL import Image
    key = os.environ.get("GEMINI_IMAGE_API_KEY", "").strip()
    if not key:
        return None, "no image key"
    prompt = str(card.get("image_prompt") or "").strip()
    if not prompt:
        return None, "no image prompt"
    from google import genai
    import transform
    client = genai.Client(api_key=key)
    last = ""
    for model in cfg.get("image_models", ["gemini-nano-banana-2.1"]):
        try:
            it = transform.with_retry(lambda: client.interactions.create(
                model=model, input=f"{prompt}\n\n{IMAGE_STYLE}",
                response_format={"type": "image", "mime_type": "image/jpeg",
                                 "aspect_ratio": "4:5", "image_size": "1K"}), tries=3)
            data = it.output_image.data
            raw = base64.b64decode(data) if isinstance(data, str) else bytes(data)
            return Image.open(io.BytesIO(raw)).convert("RGB"), model
        except Exception as exc:
            last = f"{model}: {str(exc)[:160]}"
            log(f"[{page['key']}] image model {model} failed: {str(exc)[:160]}")
    return None, last


def clean(text):
    """Strip emojis/symbols the fonts can't draw; keep normal punctuation and accents."""
    keep = "’‘“”–—…•·"
    text = "".join(ch for ch in str(text) if ord(ch) < 0x2000 or ch in keep)
    return re.sub(r"\s+", " ", text).strip().strip('"')


# ---------------------------------------------------------------- drawing
def font(name, size):
    from PIL import ImageFont
    return ImageFont.truetype(str(FONTS / name), size)


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def wrap(draw, text, fnt, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textlength(test, font=fnt) <= width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit(draw, text, fname, width, max_lines, sizes):
    """Largest font size where text fits in max_lines."""
    for size in sizes:
        f = font(fname, size)
        lines = wrap(draw, text, f, width)
        if len(lines) <= max_lines:
            return f, lines
    f = font(fname, sizes[-1])
    return f, wrap(draw, text, f, width)[:max_lines]


def draw_background(img, theme):
    from PIL import Image, ImageDraw
    top, bottom = hex_rgb(theme["bg_top"]), hex_rgb(theme["bg_bottom"])
    grad = Image.new("RGB", (1, H))
    for y in range(H):
        t = y / (H - 1)
        grad.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    img.paste(grad.resize((W, H)))
    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(deco)
    acc = hex_rgb(theme["accent"])
    motif = theme.get("motif", "circles")
    if motif == "stripes":
        for x in range(-H, W, 120):
            d.line([(x, H), (x + H, 0)], fill=acc + (14,), width=34)
    elif motif == "dots":
        for y in range(40, H, 70):
            for x in range(40 + (y // 70 % 2) * 35, W, 70):
                d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=acc + (22,))
    else:
        d.ellipse([W - 420, -260, W + 260, 420], fill=acc + (30,))
        d.ellipse([-300, H - 380, 360, H + 280], fill=acc + (22,))
    img.paste(deco, (0, 0), deco)


def _cover(photo, w, h):
    """Scale+crop a photo to fill w x h, keeping the top (subject) area."""
    from PIL import Image
    s = max(w / photo.width, h / photo.height)
    p = photo.resize((int(photo.width * s) + 1, int(photo.height * s) + 1), Image.LANCZOS)
    left = (p.width - w) // 2
    top = max(0, min(int((p.height - h) * 0.3), p.height - h))
    return p.crop((left, top, left + w, top + h))


def render_card(page, card, out_path, photo=None):
    from PIL import Image, ImageDraw
    th = page["image"]["theme"]
    img = Image.new("RGB", (W, H))
    draw_background(img, th)
    d = ImageDraw.Draw(img)
    fg, acc, muted = hex_rgb(th["text"]), hex_rgb(th["accent"]), hex_rgb(th.get("muted", th["text"]))
    on_acc = hex_rgb(th.get("on_accent", "#FFFFFF"))
    margin, width = 90, W - 180

    if photo is not None:
        # ---- photo layout: AI photo fills the card, text sits on a brand-coloured panel below
        img.paste(_cover(photo, W, H), (0, 0))
        card = dict(card, bullets=(card.get("bullets") or [])[:3])  # keep the photo visible
        avail = 600
        for hmax in range(88, 50, -6):
            ops, y, body_size = _layout(d, card, th, fg, muted, margin, width, hmax, avail=avail)
            if body_size >= 40 and y <= avail:
                break
        panel_top = H - 190 - y - 64
        shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shade)
        for i in range(140):  # soft shadow above the panel so the edge reads on any photo
            sd.line([(0, panel_top - 140 + i), (W, panel_top - 140 + i)], fill=(0, 0, 0, int(i * 0.6)))
        sd.rounded_rectangle([28, panel_top, W - 28, H - 28], 44,
                             fill=hex_rgb(th.get("panel") or th["bg_top"]) + (252,))
        img.paste(shade, (0, 0), shade)
        d = ImageDraw.Draw(img)
        off = panel_top + 56
    else:
        # panel
        if th.get("panel"):
            panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(panel).rounded_rectangle([50, 60, W - 50, H - 200], 48,
                                                    fill=hex_rgb(th["panel"]) + (235,))
            img.paste(panel, (0, 0), panel)
            d = ImageDraw.Draw(img)

        # ---- layout first (measure), then draw centred between the top and the footer
        for hmax in range(112, 56, -8):  # shrink the headline until the body text stays readable
            ops, y, body_size = _layout(d, card, th, fg, muted, margin, width, hmax)
            if body_size >= 42:
                break
        top_limit, bottom_limit = 120, H - 230
        off = top_limit + max(0, (bottom_limit - top_limit - y) // 2)
    for op in ops:
        kind, oy = op[0], op[1] + off
        if kind == "tag":
            tw = d.textlength(op[2], font=op[3])
            d.rounded_rectangle([margin, oy, margin + tw + 68, oy + 80], 40, fill=acc)
            d.text((margin + 34, oy + 40), op[2], font=op[3], fill=on_acc, anchor="lm")
        elif kind == "text":
            d.text((op[5], oy), op[2], font=op[3], fill=op[4])
        elif kind == "bar":
            d.rectangle([margin, oy, margin + 120, oy + 10], fill=acc)
        elif kind == "dot":
            d.ellipse([margin + 4, oy - 13, margin + 30, oy + 13], fill=acc)

    _footer(img, page, th, fg, muted, margin)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def _layout(d, card, th, fg, muted, margin, width, hmax, avail=None):
    ops, y, body_size = [], 0, 99
    tag = clean(card.get("tag") or "").upper()[:26]
    if tag:
        tf = font(th["tag_font"], 42)
        ops.append(("tag", y, tag, tf))
        y += 132

    head = clean(card["headline"])
    if th.get("upper_headline"):
        head = head.upper()
    hf, hlines = fit(d, head, th["title_font"], width, 4, list(range(hmax, 54, -4)))
    lh = int(hf.size * th.get("line_height", 1.12))
    for line in hlines:
        ops.append(("text", y, line, hf, fg, margin))
        y += lh
    y += 36
    ops.append(("bar", y))
    y += 60

    top_limit, bottom_limit = 120, H - 230
    room = (avail if avail else bottom_limit - top_limit) - y
    bullets = card.get("bullets") or []
    if bullets:
        for size in range(56, 30, -2):
            bf = font(th["body_font"], size)
            blocks = [wrap(d, clean(b), bf, width - 70) for b in bullets]
            need = sum(len(b) for b in blocks) * int(size * 1.3) + (len(blocks) - 1) * 30
            if need <= room:
                break
        for b in blocks:
            ops.append(("dot", y + int(bf.size * 0.62)))
            for line in b:
                ops.append(("text", y, line, bf, fg, margin + 62))
                y += int(bf.size * 1.3)
            y += 30
        y -= 30
    else:
        body = clean(card.get("body") or "")
        if body:
            for size in range(58, 30, -2):
                bf = font(th["body_font"], size)
                lines = wrap(d, body, bf, width)
                if len(lines) * int(size * 1.38) <= room:
                    break
            for line in lines:
                ops.append(("text", y, line, bf, muted, margin))
                y += int(bf.size * 1.38)
    if bullets or card.get("body"):
        body_size = bf.size
    return ops, y, body_size


def _footer(img, page, th, fg, muted, margin):
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(img)
    fy = H - 150
    x = margin
    mono = page["image"].get("monogram") or "".join(w[0] for w in page["brand"].split()[:2]).upper()
    acc, on_acc = hex_rgb(th["accent"]), hex_rgb(th.get("on_accent", "#FFFFFF"))
    d.ellipse([x, fy - 2, x + 104, fy + 102], fill=acc)
    d.text((x + 52, fy + 50), mono, font=font(th["tag_font"], 44 if len(mono) < 3 else 34),
           fill=on_acc, anchor="mm")
    x += 128
    d.text((x, fy + 6), page["brand"], font=font(th["title_font"], 46), fill=fg)
    d.text((x, fy + 64), clean(page["image"].get("footer", "")), font=font(th["body_font"], 30),
           fill=muted)


# ---------------------------------------------------------------- facebook
def post_photo(page_id, token, path, message, api_ver):
    import requests
    with open(path, "rb") as fh:
        r = requests.post(f"https://graph.facebook.com/{api_ver}/{page_id}/photos",
                          data={"message": message, "published": "true", "access_token": token},
                          files={"source": ("card.png", fh, "image/png")}, timeout=120)
    if not r.ok:
        raise RuntimeError(f"Photo post failed: {r.status_code} {r.text[:300]}")
    j = r.json()
    return j.get("post_id") or j.get("id")


# ---------------------------------------------------------------- log sheet
def log_sheet(sheet):
    try:
        return sheet.worksheet(LOG_TAB)
    except Exception:
        ws = sheet.add_worksheet(title=LOG_TAB, rows=2, cols=len(LOG_HEADER))
        ws.update(values=[LOG_HEADER], range_name="A1")
        ws.freeze(rows=1)
        return ws


def process(page, cfg, ws, rows, now, force=False, preview=False):
    page_id = os.environ.get(page["page_id_env"], "").strip()
    token = os.environ.get(page["token_env"], "").strip()
    if not preview and (not page_id or not token):
        log(f"[{page['key']}] no Page ID/token secret yet, skipping images")
        return
    mine = [r for r in rows if r.get("page") == page["key"]]
    done = {r["slot"] for r in mine}
    if force or preview:
        label = "img manual " + now.astimezone(ZoneInfo(page["timezone"])).strftime("%Y-%m-%d %H:%M")
    else:
        due = [s for s in image_slots(page, now, cfg.get("image_window_hours", 5)) if s not in done]
        if not due:
            return
        label = due[0]
    recent = [r["topic"] for r in mine if r.get("topic")]
    card = write_card(page, recent)
    out = Path(f"preview_{page['key']}.png") if preview else Path(f"/tmp/card_{page['key']}.png")
    # photo source order: free real stock photo -> paid AI photo (if a key is set) -> text design
    used = {m for r in mine for m in re.findall(r"pexels:(px\d+|\d+)", r.get("note", ""))}
    photo, credit, pid = stock_photo(page, card, used)
    if photo is not None:
        card["photo"], card["credit"] = f"pexels:{pid}", credit
    else:
        photo, photo_info = generate_photo(page, card, cfg)
        card["photo"] = photo_info if photo is not None else f"no photo ({photo_info})"
    render_card(page, card, out, photo=photo)
    if preview:
        print(json.dumps(card, ensure_ascii=False, indent=1))
        if os.environ.get("GOOGLE_REFRESH_TOKEN"):
            from common import drive_service, google_creds, render_folder_id, upload_render
            drive = drive_service(google_creds())
            _, link = upload_render(drive, out, f"preview_{page['key']}_{utcnow():%Y%m%d_%H%M}.png",
                                    render_folder_id(drive), mime="image/png")
            log(f"[{page['key']}] preview card: {link}")
        return
    message = card["caption"].strip() + ("\n\n" + " ".join(card["hashtags"]) if card["hashtags"] else "")
    if card.get("credit"):
        message += f"\n\n📷 {card['credit']}"
    try:
        post_id = post_photo(page_id, token, out, message, cfg["graph_api_version"])
        note = f"text {card['model']}; photo {card['photo']}"
        log(f"[{page['key']}] {label}: posted image '{card['headline']}' ({post_id})")
    except Exception as exc:
        post_id, note = "", str(exc)[:400]
        log(f"[{page['key']}] {label}: image post FAILED: {exc}")
        label += " (failed)"  # so the next hourly run in the same window tries again
    ws.append_row([page["key"], label, utcnow().isoformat(timespec="seconds"), card.get("type", ""),
                   clean(card.get("topic", "")), clean(card["headline"]), post_id, note],
                  value_input_option="RAW")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", default="")
    ap.add_argument("--preview", default="")
    ap.add_argument("--precheck", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    now = utcnow()
    if args.precheck:
        due = any_image_due(cfg, now) and bool(os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip())
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
                fh.write(f"due={'true' if due else 'false'}\n")
        log(f"Precheck: an image slot is {'OPEN' if due else 'closed'}")
        return
    only = (args.force or args.preview).strip().upper()
    if not only and not any_image_due(cfg, now):
        log("No image slot open")
        return
    if not os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip():
        log("Setup not finished (Google secrets missing)")
        return
    from common import google_creds, open_sheet
    ws = log_sheet(open_sheet(google_creds()))
    rows = ws.get_all_records(expected_headers=LOG_HEADER) if ws.row_count > 1 else []
    for page in all_pages(cfg):
        if only and page["key"].upper() != only:
            continue
        try:
            process(page, cfg, ws, rows, now, force=bool(args.force), preview=bool(args.preview))
        except Exception as exc:
            log(f"[{page['key']}] image error: {exc}")


if __name__ == "__main__":
    main()
