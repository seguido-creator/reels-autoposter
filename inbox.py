"""Inbox agent: answers comments on the Pages' recent posts, in each Page's own voice.

Every runner cycle it looks at posts from the last 3 days (Reels, photo posts, community posts),
reads new top-level comments, and for each one decides:
  reply - short, warm, on-topic answer (plus a like)
  like  - only a like (emoji-only, simple praise)
  flag  - no reply; logged for Juls (complaints, distress, personal medical/legal/money situations,
          accusations, anything about minors, hate, threats, anything risky)
  skip  - spam, links, bots, other pages advertising
Everything is logged in the "Inbox" tab of the Google Sheet (comment text, action, reply).
Never sells, never sends links, never asks people to DM, never gives individual medical, legal or
financial advice. Switch off with "inbox": {"enabled": false} in config.json.

  python inbox.py                 # normal run (runner calls this every 20 min)
  python inbox.py --dry FIN       # show what it would do for one Page, post nothing
"""
import argparse
import datetime as dt
import json
import os

from common import load_config, log, utcnow

TAB = "Inbox"
HEADER = ["page", "post_id", "comment_id", "comment_time_utc", "comment", "action", "reply", "reason",
          "handled_at_utc"]

PROMPT = """You manage the comments of the Facebook Page "{brand}" (niche: {angle}; audience: {audience}).
Write replies in this voice and language: {language}. The Page is faceless: never claim a personal name,
age, family, job or experience. Sign nothing.

The post these comments are on: "{post}"

New comments (id: text):
{comments}

For EACH comment choose one action:
- "reply": a short, warm, human reply (max 25 words, max 1 emoji) that answers or adds one small useful
  point related to the post. Match the commenter's language (English, Tagalog/Taglish...). Thank people
  naturally, answer genuine questions in general terms only, keep debates friendly.
- "like": only like it (emoji-only comments, a single word, simple praise) - no reply text needed.
- "flag": do NOT reply - for complaints, angry or upset people, someone in distress, personal medical, legal
  or money situations ("my dad has...", "should I invest my..."), accusations, anything about minors, hate,
  threats, politics or religion fights, or anything you are not sure is safe to answer.
- "skip": spam, links, ads, bots, other pages promoting themselves, gibberish.
Hard rules for replies: no links, no selling, no "DM us" / "message us" (unless the page-specific rules below
allow it), no follow-begging, no invented facts, numbers or promises, no individual medical/legal/financial advice
(general info only, and suggest a professional when it matters). Never argue. Never mention you are AI unless asked
directly; if asked, say the Page uses AI tools to help reply.
{extra}
Return ONLY JSON: a list of objects {{"id": "...", "action": "reply|like|flag|skip", "reply": "text or empty",
"reason": "max 8 words"}}"""


def _get(url, params):
    import requests
    try:
        r = requests.get(url, params=params, timeout=30)
        return r.json() if r.ok else {"error": r.text[:200]}
    except Exception as exc:
        return {"error": str(exc)[:200]}


def _post(url, data):
    import requests
    try:
        r = requests.post(url, data=data, timeout=30)
        return r.ok, (r.json() if r.ok else r.text[:200])
    except Exception as exc:
        return False, str(exc)[:200]


def recent_posts(sheet, cfg, hours):
    """(page_key, post_id, text) for posts made in the last `hours`, newest first."""
    since = utcnow() - dt.timedelta(hours=hours)
    out = []

    def when(x):
        try:
            return dt.datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        except Exception:
            return None

    for tab, text_cols in (("Images", ("headline", "topic")), ("Community", ("text", "topic"))):
        try:
            for r in sheet.worksheet(tab).get_all_records():
                t, pid = when(r.get("posted_at_utc")), str(r.get("fb_post_id", "")).strip()
                if not pid or not t or t < since or "failed" in str(r.get("slot", "")):
                    continue
                out.append((r.get("page"), pid, str(r.get(text_cols[0]) or r.get(text_cols[1]) or "")[:300], t))
        except Exception as exc:
            log(f"inbox: could not read {tab}: {str(exc)[:100]}")
    for page in cfg["pages"]:
        try:
            for r in sheet.worksheet(page.get("sheet_tab") or page["key"]).get_all_records():
                t, pid = when(r.get("posted_at_utc")), str(r.get("fb_video_id", "")).strip()
                if pid and t and t >= since:
                    out.append((page["key"], pid, str(r.get("hook") or r.get("caption") or "")[:300], t))
        except Exception:
            pass
    out.sort(key=lambda x: x[3], reverse=True)
    return [(k, p, txt) for k, p, txt, _ in out]


def decide(page, post_text, comments):
    """Gemini decides reply/like/flag/skip for a batch of comments. Returns {id: decision}."""
    import transform
    from google.genai import types
    style = page.get("image") or {}
    extra = str(style.get("inbox_rules") or "")
    prompt = PROMPT.format(brand=page["brand"], angle=style.get("angle") or page.get("content_angle", ""),
                           audience=page.get("audience", ""), language=style.get("language") or page.get("language", ""),
                           post=post_text, extra=extra,
                           comments="\n".join(f"{c['id']}: {str(c.get('message', ''))[:500]}" for c in comments))
    resp, _ = transform.generate(transform._gemini_client(), prompt, types.GenerateContentConfig(
        response_mime_type="application/json", temperature=0.4))
    data = json.loads(resp.text or "[]")
    if isinstance(data, dict):
        data = data.get("comments") or data.get("items") or [data]
    out = {}
    for d in data if isinstance(data, list) else []:
        if isinstance(d, dict) and d.get("id"):
            act = str(d.get("action", "")).lower()
            out[str(d["id"])] = {"action": act if act in ("reply", "like", "flag", "skip") else "flag",
                                 "reply": str(d.get("reply") or "").strip()[:300],
                                 "reason": str(d.get("reason") or "")[:80]}
    return out


BANNED = ("http", "www.", ".com", "dm us", "message us", "inbox us", "follow us", "follow me")


def safe_reply(page, text):
    t = text.lower()
    if not text or len(text) > 300:
        return False
    if any(b in t for b in BANNED):
        # a keyword-freebie hint ("message IPON to the Page") is allowed only when the Page's rules enable it
        word = str((page.get("image") or {}).get("inbox_keyword") or "").lower()
        return bool(word) and word in t and "http" not in t and "www." not in t
    return True


def run(cfg, sheet, only="", dry=False):
    icfg = cfg.get("inbox") or {}
    if not icfg.get("enabled", True):
        return
    api = cfg["graph_api_version"]
    pages = {p["key"]: p for p in cfg["pages"] + cfg.get("image_pages", [])}
    try:
        ws = sheet.worksheet(TAB)
    except Exception:
        ws = sheet.add_worksheet(title=TAB, rows=2, cols=len(HEADER))
        ws.update(values=[HEADER], range_name="A1")
        ws.freeze(rows=1)
    done = {str(r[2]) for r in ws.get_all_values()[1:] if len(r) > 2}
    max_age = dt.timedelta(hours=icfg.get("max_comment_age_hours", 72))
    per_page = icfg.get("max_replies_per_page_per_run", 12)
    rows, counts = [], {}
    for key, post_id, post_text in recent_posts(sheet, cfg, icfg.get("post_window_hours", 72)):
        page = pages.get(key)
        if not page or (only and key != only) or counts.get(key, 0) >= per_page:
            continue
        token = os.environ.get(page["token_env"], "").strip()
        page_id = os.environ.get(page["page_id_env"], "").strip()
        if not token or not page_id:
            continue
        j = _get(f"https://graph.facebook.com/{api}/{post_id}/comments", {
            "access_token": token, "filter": "toplevel", "order": "reverse_chronological", "limit": 30,
            "fields": "id,message,created_time,from{id},comments.limit(20){from{id}}"})
        if j.get("error"):
            log(f"[{key}] inbox: comments unavailable on {post_id}: {str(j['error'])[:120]}")
            continue
        fresh = []
        for c in j.get("data", []):
            cid = str(c.get("id"))
            if cid in done or str((c.get("from") or {}).get("id")) == page_id:
                continue
            if any(str((x.get("from") or {}).get("id")) == page_id for x in (c.get("comments") or {}).get("data", [])):
                continue  # the Page already answered it
            try:
                t = dt.datetime.fromisoformat(str(c.get("created_time")).replace("+0000", "+00:00"))
            except Exception:
                continue
            if utcnow() - t > max_age or not str(c.get("message", "")).strip():
                continue
            fresh.append(c)
        if not fresh:
            continue
        fresh = fresh[:per_page - counts.get(key, 0)]
        try:
            decisions = decide(page, post_text, fresh)
        except Exception as exc:
            log(f"[{key}] inbox: AI unavailable ({str(exc)[:100]}), will try next run")
            continue
        for c in fresh:
            cid = str(c["id"])
            d = decisions.get(cid) or {"action": "flag", "reply": "", "reason": "no decision"}
            act, reply = d["action"], d["reply"]
            if act == "reply" and not safe_reply(page, reply):
                act, d["reason"] = "flag", "reply failed safety check"
            note = ""
            if not dry and act in ("reply", "like"):
                _post(f"https://graph.facebook.com/{api}/{cid}/likes", {"access_token": token})
            if not dry and act == "reply":
                ok, res = _post(f"https://graph.facebook.com/{api}/{cid}/comments",
                                {"message": reply, "access_token": token})
                if not ok:
                    act, note = "reply failed", str(res)[:120]
                else:
                    counts[key] = counts.get(key, 0) + 1
            log(f"[{key}] inbox {act}: '{str(c.get('message', ''))[:60]}'" + (f" -> '{reply[:80]}'" if reply and act == "reply" else ""))
            rows.append([key, post_id, cid, str(c.get("created_time", "")), str(c.get("message", ""))[:500], act,
                         reply if act == "reply" else "", (d.get("reason") or "") + (f" {note}" if note else ""),
                         utcnow().isoformat(timespec="seconds")])
            done.add(cid)
    if rows and not dry:
        ws.append_rows(rows, value_input_option="RAW")
    flagged = sum(1 for r in rows if r[5] == "flag")
    if rows:
        log(f"inbox: {len(rows)} comments handled ({flagged} flagged for Juls)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", default="", help="page key: show decisions only, post nothing")
    args = ap.parse_args()
    if not os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip():
        return
    from common import google_creds, open_sheet
    run(load_config(), open_sheet(google_creds()), only=args.dry.upper(), dry=bool(args.dry))


if __name__ == "__main__":
    main()
