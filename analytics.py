"""Performance feedback loop.

Once a day (first runner check after 03:00 UTC) every post from the last 21 days that is at least
24 hours old gets its numbers from Facebook (plays/reach, reactions, comments, shares) and is written
to the "Performance" tab of the Google Sheet (one row per post, refreshed while the post is young).

Followers matter more than likes: once a day each Page's follower count is saved to the "Followers"
tab, and each day's new followers are shared out over the posts that were live in that period (in
proportion to their views). That estimate ("est_follows") weighs heavily in the score, so topics that
win followers are preferred over topics that only win likes.

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
          "comments", "shares", "score", "checked_at_utc", "est_follows"]
FOL_TAB = "Followers"
FOL_HEADER = ["date_utc", "page", "followers", "new_since_last", "checked_at_utc"]
FOLLOW_WEIGHT = 15  # one new follower counts like ~2 shares
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


def _tab(sheet, name, header):
    try:
        ws = sheet.worksheet(name)
    except Exception:
        ws = sheet.add_worksheet(title=name, rows=2, cols=len(header))
        ws.update(values=[header], range_name="A1")
        ws.freeze(rows=1)
        return ws
    first = ws.row_values(1)
    if first != header and first == header[:len(first)]:  # a column was added in a newer version
        if ws.col_count < len(header):
            ws.add_cols(len(header) - ws.col_count)
        ws.update(values=[header], range_name="A1")
    return ws


def perf_tab(sheet):
    return _tab(sheet, TAB, HEADER)


def _when(x):
    try:
        return dt.datetime.fromisoformat(str(x).replace("Z", "+00:00"))
    except Exception:
        return None


def follower_snapshot(cfg, sheet):
    """Saves today's follower count per Page (once a day). Returns all snapshot rows (dicts), oldest first."""
    ws = _tab(sheet, FOL_TAB, FOL_HEADER)
    rows = ws.get_all_records()
    today = utcnow().strftime("%Y-%m-%d")
    have = {(str(r.get("date_utc")), r.get("page")) for r in rows}
    last = {}
    for r in rows:
        last[r.get("page")] = r.get("followers")
    new = []
    for page in cfg["pages"] + cfg.get("image_pages", []):
        key = page["key"]
        token = os.environ.get(page["token_env"], "").strip()
        page_id = os.environ.get(page["page_id_env"], "").strip()
        if (today, key) in have or not token or not page_id:
            continue
        j = _get(f"https://graph.facebook.com/{cfg['graph_api_version']}/{page_id}",
                 {"access_token": token, "fields": "followers_count,fan_count"})
        n = j.get("followers_count", j.get("fan_count"))
        if n is None:
            log(f"analytics: no follower count for {key}")
            continue
        prev = last.get(key)
        gain = int(n) - int(prev) if str(prev).strip().lstrip("-").isdigit() else ""
        new.append([today, key, int(n), gain, utcnow().isoformat(timespec="seconds")])
    if new:
        ws.append_rows(new, value_input_option="RAW")
        log("analytics: followers " + ", ".join(f"{r[1]} {r[2]} ({'+' if str(r[3]).isdigit() else ''}{r[3]})"
                                                for r in new))
    return rows + [dict(zip(FOL_HEADER, r)) for r in new]


def estimate_follows(posts, snaps):
    """posts: list of dicts with page, when (datetime), plays/reach. Adds p['est_follows'].
    Each snapshot interval's new followers are split over that Page's posts published from 24h before the
    interval to its end (a post keeps pulling in followers for about a day), weighted by views."""
    for p in posts:
        p["est_follows"] = 0.0
    by_page = {}
    for r in snaps:
        t = _when(r.get("checked_at_utc"))
        if t:
            by_page.setdefault(r.get("page"), []).append((t, r.get("new_since_last")))
    for page, pts in by_page.items():
        pts.sort(key=lambda x: x[0])
        for (t0, _), (t1, gain) in zip(pts, pts[1:]):
            try:
                gain = float(gain)
            except (TypeError, ValueError):
                continue
            if gain <= 0:
                continue
            live = [p for p in posts if p["page"] == page and t0 - dt.timedelta(hours=24) <= p["when"] < t1]
            weight = sum((p["plays"] or p["reach"]) for p in live)
            for p in live:
                share = ((p["plays"] or p["reach"]) / weight) if weight else 1 / len(live)
                p["est_follows"] += gain * share
    for p in posts:
        p["est_follows"] = round(p["est_follows"], 1)


def refresh(cfg, sheet, force=False):
    ws = perf_tab(sheet)
    rows = ws.get_all_values()
    today = utcnow().strftime("%Y-%m-%d")
    if not force and any(len(r) > 11 and r[11].startswith(today) for r in rows[1:]):
        return
    pages = {p["key"]: p for p in cfg["pages"] + cfg.get("image_pages", [])}
    old = {r[1]: i for i, r in enumerate(rows[1:], start=2) if len(r) > 1}
    try:
        snaps = follower_snapshot(cfg, sheet)
    except Exception as exc:
        log(f"analytics: follower snapshot failed: {str(exc)[:120]}")
        snaps = []
    posts = []
    for page_key, pid, kind, topic, when in collect_posts(sheet, cfg):
        page = pages.get(page_key)
        token = os.environ.get(page["token_env"], "").strip() if page else ""
        if not token:
            continue
        is_video = "_" not in pid
        n = post_numbers(cfg["graph_api_version"], pid, token, is_video)
        posts.append(dict(n, page=page_key, pid=pid, kind=kind, topic=topic, posted=when, when=_when(when)))
    estimate_follows(posts, snaps)
    new_rows, updates = [], []
    for n in posts:
        n["score"] = round(n["score"] + FOLLOW_WEIGHT * n["est_follows"], 1)
        row = [n["page"], n["pid"], n["kind"], n["topic"], n["posted"], n["plays"], n["reach"], n["reactions"],
               n["comments"], n["shares"], n["score"], utcnow().isoformat(timespec="seconds"), n["est_follows"]]
        if n["pid"] in old:
            updates.append({"range": f"A{old[n['pid']]}:M{old[n['pid']]}", "values": [row]})
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
    num = lambda r, k: float(r.get(k) or 0) if str(r.get(k) or "0").replace(".", "", 1).isdigit() else 0.0
    follows = sum(num(r, "est_follows") for r in rows)
    views = sum(num(r, "plays") or num(r, "reach") for r in rows)
    winners = sorted((r for r in rows if num(r, "est_follows") > 0), key=lambda r: num(r, "est_follows"),
                     reverse=True)[:3]
    fol = ""
    if views and follows:
        fol = (f"\nFollowers: about {follows / views * 1000:.1f} new followers per 1,000 views recently. "
               "Topics that brought the most NEW FOLLOWERS (more valuable than likes): "
               + "; ".join(str(r["topic"]) for r in winners) + ".")
    return ("What this Page's audience actually rewarded recently (followers, shares, comments, views first):\n"
            + "\n".join(f"- {t}" for t in top) + fol
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
