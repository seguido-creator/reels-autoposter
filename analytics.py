"""Performance feedback loop.

Once a day (first runner check after 03:00 UTC) every post from the last 21 days that is at least
24 hours old gets its numbers from Facebook (plays/reach, reactions, comments, shares) and is written
to the "Performance" tab of the Google Sheet (one row per post, refreshed while the post is young).

images.py then reads the best and worst topics per page (perf_hint) and tells the AI to lean toward
what audiences actually rewarded and away from what flopped. Nothing is ever posted from here.

  python analytics.py           # daily refresh (skips if already done today)
  python analytics.py --force   # refresh now
"""
import argparse
import datetime as dt
import os

from common import load_config, log, utcnow

TAB = "Performance"
HEADER = ["page", "post_id", "kind", "topic", "posted_at_utc", "plays", "reach", "reactions",
          "comments", "shares", "score", "checked_at_utc"]
DAYS = 21


def _get(url, params):
    import requests
    try:
        r = requests.get(url, params=params, timeout=30)
        return r.json() if r.ok else {}
    except Exception:
        return {}


def post_numbers(api, obj_id, token, is_video):
    """Best-effort numbers for one post. Metrics Facebook doesn't offer for a post stay 0."""
    base = f"https://graph.facebook.com/{api}/{obj_id}"
    out = {"plays": 0, "reach": 0, "reactions": 0, "comments": 0, "shares": 0}
    j = _get(base, {"access_token": token,
                    "fields": "reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0),shares"})
    out["reactions"] = int(((j.get("reactions") or {}).get("summary") or {}).get("total_count") or 0)
    out["comments"] = int(((j.get("comments") or {}).get("summary") or {}).get("total_count") or 0)
    out["shares"] = int((j.get("shares") or {}).get("count") or 0)
    if is_video:
        for metric, key in (("blue_reels_play_count", "plays"), ("post_impressions_unique", "reach")):
            j = _get(base + "/video_insights", {"access_token": token, "metric": metric})
            vals = (j.get("data") or [{}])[0].get("values") or [{}]
            try:
                out[key] = int(vals[0].get("value") or 0)
            except (TypeError, ValueError):
                pass
    else:
        j = _get(base + "/insights", {"access_token": token, "metric": "post_impressions_unique"})
        vals = (j.get("data") or [{}])[0].get("values") or [{}]
        try:
            out["reach"] = int(vals[0].get("value") or 0)
        except (TypeError, ValueError):
            pass
    # one number to rank posts within a page: shares and comments say "people cared" the most
    seen = out["plays"] or out["reach"]
    out["score"] = round(seen / 100 + out["reactions"] + 4 * out["comments"] + 8 * out["shares"], 1)
    return out


def collect_posts(sheet, cfg):
    """(page, post_id, kind, topic, posted_at) for recent posts from every log tab."""
    since = utcnow() - dt.timedelta(days=DAYS)
    young = utcnow() - dt.timedelta(hours=24)
    posts = []

    def add(page, pid, kind, topic, when):
        try:
            t = dt.datetime.fromisoformat(str(when).replace("Z", "+00:00"))
        except Exception:
            return
        if pid and since <= t <= young:
            posts.append((page, str(pid), kind, str(topic)[:80], t.isoformat(timespec="seconds")))

    for tab, kind_col in (("Images", "type"), ("Community", "kind")):
        try:
            for r in sheet.worksheet(tab).get_all_records():
                slot, pid = str(r.get("slot", "")), str(r.get("fb_post_id", ""))
                if "failed" in slot or slot.startswith(("reveal", "share")):
                    continue
                kind = str(r.get(kind_col, ""))
                kind = ("community:" + kind) if tab == "Community" else (kind + (" photo" if "_" in pid else " reel"))
                add(r.get("page"), pid, kind, r.get("topic") or r.get("headline"), r.get("posted_at_utc"))
        except Exception as exc:
            log(f"analytics: could not read {tab}: {str(exc)[:100]}")
    for page in cfg["pages"]:
        try:
            for r in sheet.worksheet(page.get("sheet_tab") or page["key"]).get_all_records():
                add(page["key"], r.get("fb_video_id"), "pack reel", r.get("hook"), r.get("posted_at_utc"))
        except Exception as exc:
            log(f"analytics: could not read {page['key']} queue: {str(exc)[:100]}")
    return posts


def perf_tab(sheet):
    try:
        return sheet.worksheet(TAB)
    except Exception:
        ws = sheet.add_worksheet(title=TAB, rows=2, cols=len(HEADER))
        ws.update(values=[HEADER], range_name="A1")
        ws.freeze(rows=1)
        return ws


def refresh(cfg, sheet, force=False):
    ws = perf_tab(sheet)
    rows = ws.get_all_values()
    today = utcnow().strftime("%Y-%m-%d")
    if not force and any(len(r) > 11 and r[11].startswith(today) for r in rows[1:]):
        return
    pages = {p["key"]: p for p in cfg["pages"] + cfg.get("image_pages", [])}
    old = {r[1]: i for i, r in enumerate(rows[1:], start=2) if len(r) > 1}
    new_rows, updates = [], []
    for page_key, pid, kind, topic, when in collect_posts(sheet, cfg):
        page = pages.get(page_key)
        token = os.environ.get(page["token_env"], "").strip() if page else ""
        if not token:
            continue
        is_video = "_" not in pid
        n = post_numbers(cfg["graph_api_version"], pid, token, is_video)
        row = [page_key, pid, kind, topic, when, n["plays"], n["reach"], n["reactions"], n["comments"],
               n["shares"], n["score"], utcnow().isoformat(timespec="seconds")]
        if pid in old:
            updates.append({"range": f"A{old[pid]}:L{old[pid]}", "values": [row]})
        else:
            new_rows.append(row)
    if updates:
        ws.batch_update(updates, value_input_option="RAW")
    if new_rows:
        ws.append_rows(new_rows, value_input_option="RAW")
    log(f"analytics: {len(updates)} posts refreshed, {len(new_rows)} new")


def perf_hint(sheet, page_key, n=5):
    """Short text for the content prompt: what this page's audience rewarded and ignored."""
    try:
        rows = [r for r in perf_tab(sheet).get_all_records() if r.get("page") == page_key and r.get("topic")]
    except Exception:
        return ""
    if len(rows) < 8:
        return ""
    rows.sort(key=lambda r: float(r.get("score") or 0), reverse=True)
    top = [f"{r['topic']} ({r['kind']}, score {r['score']})" for r in rows[:n]]
    low = [r["topic"] for r in rows[-n:]]
    return ("What this Page's audience actually rewarded recently (most shares/comments/views first):\n"
            + "\n".join(f"- {t}" for t in top)
            + "\nWhat got little response:\n" + "\n".join(f"- {t}" for t in low)
            + "\nLean toward the kind of topics, angles and hooks that won, without repeating those exact "
              "topics. Avoid the patterns of the weak ones.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if not args.force and utcnow().hour != 3:
        return
    if not os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip():
        return
    from common import google_creds, open_sheet
    refresh(load_config(), open_sheet(google_creds()), force=args.force)


if __name__ == "__main__":
    main()
