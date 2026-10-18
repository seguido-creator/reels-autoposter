"""Engagement helpers.

after_post(): right after a post goes live, the Page adds its own first comment (a bonus fact or an
easy either/or question) so the comment section is never empty. Gemini writes it in the Page's
language; it never raises, so posting can't be blocked by it. Switch off with "first_comment": false
in config.json.
"""
import json
import time

from common import log

COMMENT_PROMPT = """You manage the Facebook Page "{brand}". The Page just published this post:
---
{caption}
---
Write the Page's own FIRST COMMENT under it, to start a real conversation.
Language and tone: {language}
Audience: {audience}
Pick ONE of these:
- a short bonus fact or tip that adds something new to the post (true and well established),
  followed by a simple question, or
- an easy either/or question people can answer in one or two words.
Rules: max 30 words, max 1 emoji. Do not repeat the caption or its question.
No engagement bait ("like if", "share if", "tag someone", "comment YES", "type AMEN", "follow us"),
no links, no hashtags, nothing political, religious or sexual, no medical, legal or financial advice
for individuals. Never invent statistics, studies, names, prices or dates.
Return JSON: {{"comment": "..."}}"""


def write_comment(page, caption):
    import transform
    from google.genai import types
    client = transform._gemini_client()
    prompt = COMMENT_PROMPT.format(
        brand=page["brand"], caption=str(caption)[:1200],
        language=(page.get("image") or {}).get("language") or page.get("language", ""),
        audience=page.get("audience", ""))
    resp, _used = transform.generate(client, prompt, types.GenerateContentConfig(
        response_mime_type="application/json", temperature=0.8))
    try:
        data = json.loads(resp.text or "{}")
    except Exception:
        data = {}
    if isinstance(data, list):
        data = data[0] if data and isinstance(data[0], dict) else {}
    return str(data.get("comment", "")).strip().strip('"')[:400]


def after_post(page, cfg, object_id, token, caption):
    """The Page's first comment under a new post. Returns a short note for the log; never raises."""
    if not cfg.get("first_comment", True) or not object_id or not token:
        return ""
    try:
        import requests
        text = write_comment(page, caption)
        if not text:
            return "; comment skipped (empty)"
        api = cfg["graph_api_version"]
        last = ""
        for attempt in range(3):  # a fresh reel can need a moment before it accepts comments
            r = requests.post(f"https://graph.facebook.com/{api}/{object_id}/comments",
                              data={"message": text, "access_token": token}, timeout=60)
            if r.ok:
                log(f"[{page['key']}] first comment posted on {object_id}")
                return f"; comment {r.json().get('id', '')}"
            last = f"{r.status_code} {r.text[:160]}"
            if attempt < 2:
                time.sleep(20)
        log(f"[{page['key']}] first comment failed on {object_id}: {last}")
        return f"; comment FAILED {last}"
    except Exception as exc:
        log(f"[{page['key']}] first comment error: {exc}")
        return f"; comment FAILED {str(exc)[:160]}"
