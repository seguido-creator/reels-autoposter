"""Community posts: one short, personal post a day per Page that invites real comments
(the creator style that grows big Pages: plain words, a question people want to answer).

Kinds (rotated by day):
  guess    - a real stock photo + "What is this / what's happening here? Guesses?"; answer revealed later
  teaser   - "This surprises almost everyone... any guesses?"; answer revealed later
  opinion  - a light "this or that" / "keep or skip" debate inside the niche
  story    - a short first-person, relatable moment from the niche + a question
  trust    - (pages listed in community.trust_pages, on trust_days of the month) a scam warning:
             "we will never DM you asking for money"
Reveal: reveal_hours after a guess/teaser post, the Page answers in the comments.

  python community.py              # post whatever is due now (runner calls this every 20 min)
  python community.py --preview FIN [--kind teaser]   # print a post, publish nothing
Switch off with "community": {"enabled": false} in config.json.
"""
import argparse
import datetime as dt
import io
import json
import os
from zoneinfo import ZoneInfo

from common import load_config, log, utcnow

LOG_TAB = "Community"
LOG_HEADER = ["page", "slot", "posted_at_utc", "kind", "topic", "text", "fb_post_id", "answer", "note"]
ROTATION = ["teaser", "opinion", "guess", "story", "teaser", "guess", "opinion"]

PROMPT = """You are the admin of the Facebook Page "{brand}" and you write its daily COMMUNITY post:
a short, personal, plain-text post like a friendly creator talking to followers, not an ad.
Niche: {angle}
Audience: {audience}
Language and tone: {language}
Write in the first person ("I", "we") as the Page admin. Faceless: never claim a name, age,
family, job, location or experience you can't back up; small everyday observations are fine.
Recent topics (do NOT repeat): {recent}

Kind of post: {kind}
{kind_rules}

Rules for every post:
- 1-3 short lines, max 45 words, max 2 emojis, no hashtags, no links.
- Only true, well-established facts. Never invent statistics, studies, names, prices, laws or dates.
- No engagement bait: never "like if", "share if", "tag someone", "comment YES", "type AMEN",
  "follow us", "wrong answers only", and never ask people to react with an emoji to vote.
- Nothing political, religious, sexual, shocking, or about real people. No individual
  medical, legal or financial advice.

Return JSON with keys:
"topic": 3-6 word label,
"text": the post text,
"answer": the answer the Page will reply with later (1-2 sentences, true, adds a little extra value;
    "" for opinion/story/trust),
"photo_search": 2-4 simple English words for a stock photo that clearly shows the thing ("" unless kind is guess),
"photo_subject": 1-2 words naming the main thing that must be visible in the photo ("" unless guess)"""

KIND_RULES = {
    "guess": ("A photo will show ONE everyday object, tool, part, animal behaviour or situation from the niche "
              "that many people can't name or explain. Ask followers to guess what it is or why it happens. "
              "Do not give the answer. Pick something a stock photo can show clearly."),
    "teaser": ("Tease ONE surprising, true fact from the niche without revealing it, e.g. 'Most people get this "
               "wrong about ... Any guesses?'. Make the question specific enough to answer. Do not give the answer."),
    "opinion": ("A light, harmless debate inside the niche: 'this or that', 'keep or skip', 'worth it or not'. "
                "Share your own short take in one line, then ask theirs. Never about specific brands' quality, "
                "health decisions, money products or people."),
    "story": ("A short, relatable everyday moment from the niche told in first person (a small funny or "
              "familiar situation most of the audience has lived), then ask if it happens to them too. "
              "No invented dramatic events, no claims of expertise or credentials."),
    "trust": ("A short, warm scam-safety reminder: this Page will NEVER message anyone asking for money, "
              "investments, 'fees', passwords or OTP codes, and never sells courses in DMs. Tell followers "
              "to report and block anyone pretending to be the Page. End with one helpful line."),
}


def all_pages(cfg):
    return [p for p in cfg["pages"] if p.get("image")] + cfg.get("image_pages", [])


def due_slot(page, ccfg, now_utc):
    t = (ccfg.get("slots") or {}).get(page["key"])
    if not t:
        return None
    tz = ZoneInfo(page["timezone"])
    now = now_utc.astimezone(tz)
    hh, mm = (int(x) for x in t.split(":"))
    for off in (0, -1):
        day = (now + dt.timedelta(days=off)).date()
        start = dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
        if start <= now < start + dt.timedelta(hours=ccfg.get("window_hours", 4)):
            return "com " + start.strftime("%Y-%m-%d %H:%M"), start
    return None


def pick_kind(page, ccfg, day):
    if page["key"] in (ccfg.get("trust_pages") or []) and day.day in (ccfg.get("trust_days") or [1, 15]):
        return "trust"
    kinds = ccfg.get("kinds") or ROTATION
    return kinds[day.toordinal() % len(kinds)]


def write_post(page, kind, recent):
    import transform
    from google.genai import types
    style = page.get("image") or {}
    prompt = PROMPT.format(
        brand=page["brand"], angle=style.get("angle") or page.get("content_angle", ""),
        audience=page.get("audience", ""), language=style.get("language") or page.get("language", ""),
        recent="; ".join(recent[-30:]) or "(none yet)", kind=kind, kind_rules=KIND_RULES[kind])
    for _ in range(3):
        resp, _used = transform.generate(transform._gemini_client(), prompt, types.GenerateContentConfig(
            response_mime_type="application/json", temperature=0.95))
        try:
            data = json.loads(resp.text or "{}")
        except Exception:
            data = {}
        if isinstance(data, list):
            data = data[0] if data and isinstance(data[0], dict) else {}
        if str(data.get("text", "")).strip():
            return {k: str(data.get(k) or "").strip() for k in
                    ("topic", "text", "answer", "photo_search", "photo_subject")}
    raise RuntimeError("AI community post came back empty")


def guess_photo(page, post, used):
    """Stock photo for a guess post, kept only if Gemini confirms the subject is clearly visible."""
    import images
    import transform
    from google.genai import types
    q = post.get("photo_search")
    if not q:
        return None, None
    for _ in range(2):
        img, credit, pid = images.pixabay_photo(page, q, used)
        if img is None:
            return None, None
        used.add(pid)
        buf = io.BytesIO()
        img.thumbnail((1080, 1350))
        img.save(buf, "JPEG", quality=90)
        try:
            resp, _ = transform.generate(transform._gemini_client(), [
                types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"),
                f"Is a {post.get('photo_subject') or q} clearly the main subject of this photo? Answer only YES or NO."],
                types.GenerateContentConfig(temperature=0))
            ok = "YES" in (resp.text or "").upper()
        except Exception:
            ok = False
        if ok:
            return buf.getvalue(), pid
    return None, None


def publish(page_id, token, api, text, photo=None):
    import requests
    if photo:
        r = requests.post(f"https://graph.facebook.com/{api}/{page_id}/photos",
                          data={"message": text, "published": "true", "access_token": token},
                          files={"source": ("guess.jpg", photo, "image/jpeg")}, timeout=120)
    else:
        r = requests.post(f"https://graph.facebook.com/{api}/{page_id}/feed",
                          data={"message": text, "access_token": token}, timeout=60)
    if not r.ok:
        raise RuntimeError(f"{r.status_code} {r.text[:300]}")
    j = r.json()
    return j.get("post_id") or j.get("id")


def comment(obj_id, token, api, text):
    import requests
    r = requests.post(f"https://graph.facebook.com/{api}/{obj_id}/comments",
                      data={"message": text, "access_token": token}, timeout=60)
    if not r.ok:
        raise RuntimeError(f"{r.status_code} {r.text[:200]}")
    return r.json().get("id", "")


def log_sheet(sheet):
    try:
        return sheet.worksheet(LOG_TAB)
    except Exception:
        ws = sheet.add_worksheet(title=LOG_TAB, rows=2, cols=len(LOG_HEADER))
        ws.update(values=[LOG_HEADER], range_name="A1")
        ws.freeze(rows=1)
        return ws


def reveal_text(page, answer):
    lang = (page.get("language") or "").lower()
    lead = "Sagot:" if ("taglish" in lang or "tagalog" in lang) else "Answer:"
    return f"{lead} {answer}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", default="")
    ap.add_argument("--kind", default="")
    args = ap.parse_args()
    cfg = load_config()
    ccfg = cfg.get("community") or {}
    now = utcnow()
    pages = all_pages(cfg)
    if args.preview:
        page = next(p for p in pages if p["key"].upper() == args.preview.upper())
        kind = args.kind or pick_kind(page, ccfg, now.astimezone(ZoneInfo(page["timezone"])).date())
        print(json.dumps({"kind": kind, **write_post(page, kind, [])}, ensure_ascii=False, indent=1))
        return
    if not ccfg.get("enabled"):
        return
    reveal_h = float(ccfg.get("reveal_hours", 7))
    due = {p["key"]: due_slot(p, ccfg, now) for p in pages}
    # cheap exit: no community slot open and no reveal can be due (reveals only run inside 30h after a slot)
    if not any(due.values()) and not any(
            due_slot(p, {**ccfg, "window_hours": reveal_h + 30}, now) for p in pages):
        return
    if not os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip():
        return
    from common import google_creds, open_sheet
    ws = log_sheet(open_sheet(google_creds()))
    rows = ws.get_all_records(expected_headers=LOG_HEADER) if ws.row_count > 1 else []
    api = cfg["graph_api_version"]
    for page in pages:
        page_id = os.environ.get(page["page_id_env"], "").strip()
        token = os.environ.get(page["token_env"], "").strip()
        if not page_id or not token:
            continue
        mine = [r for r in rows if r.get("page") == page["key"]]
        done = {r["slot"] for r in mine}
        # 1) answers for earlier guess/teaser posts
        for r in mine:
            pid, ans = str(r.get("fb_post_id") or ""), str(r.get("answer") or "")
            if not pid or not ans or f"reveal {pid}" in done:
                continue
            try:
                age_h = (now - dt.datetime.fromisoformat(r["posted_at_utc"])).total_seconds() / 3600
            except Exception:
                continue
            if age_h < reveal_h or age_h > reveal_h + 24:
                continue
            try:
                cid = comment(pid, token, api, reveal_text(page, ans))
                note = f"answer comment {cid}"
            except Exception as exc:
                note = f"answer FAILED {str(exc)[:200]}"
            log(f"[{page['key']}] reveal on {pid}: {note}")
            ws.append_row([page["key"], f"reveal {pid}", utcnow().isoformat(timespec="seconds"), "reveal",
                           r.get("topic", ""), "", pid, "", note], value_input_option="RAW")
            done.add(f"reveal {pid}")
        # 2) today's community post
        slot = due[page["key"]]
        if not slot or slot[0] in done:
            continue
        label, start = slot
        if sum(1 for r in mine if r.get("slot") == label + " (failed)") >= 2:
            continue
        kind = pick_kind(page, ccfg, start.date())
        photo, note = None, ""
        try:
            post = write_post(page, kind, [r.get("topic", "") for r in mine if r.get("topic")])
            if kind == "guess":
                used = {str(r.get("note", "")).split("photo ")[-1].split(";")[0] for r in mine}
                photo, pid_img = guess_photo(page, post, used)
                if photo is None:  # no clear photo: turn it into a plain teaser instead
                    kind, post = "teaser", write_post(page, "teaser", [r.get("topic", "") for r in mine])
                else:
                    note = f"photo {pid_img}"
            if kind not in ("guess", "teaser"):
                post["answer"] = ""
            fb_id = publish(page_id, token, api, post["text"], photo)
            log(f"[{page['key']}] {label}: community {kind} posted ({fb_id})")
        except Exception as exc:
            fb_id, label, note = "", label + " (failed)", f"FAILED {str(exc)[:300]}"
            post = locals().get("post") or {"topic": "", "text": "", "answer": ""}
            log(f"[{page['key']}] community post failed: {exc}")
        ws.append_row([page["key"], label, utcnow().isoformat(timespec="seconds"), kind, post.get("topic", ""),
                       post.get("text", ""), fb_id, post.get("answer", "") if fb_id else "", note],
                      value_input_option="RAW")


if __name__ == "__main__":
    main()
