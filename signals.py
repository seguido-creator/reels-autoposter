"""Real-world signals: what is getting views on TikTok in each page's niche right now (via Apify).

Every ~2 days (config "signals.every_hours") it runs Apify's TikTok Scraper on ONE hashtag per page
(rotating through the page's "signals_hashtags"), keeps the most-watched recent videos (views, likes,
shares, comments, caption) and saves them to Drive as signals_YYYYMMDD_HHMM.json.
images.py hands the top ones to the writer as inspiration (angles and hooks only; never copied).

Cost control: about 8 pages x 12 results = ~96 results per run, every 2 days (~1,500 a month), which
fits Apify's free monthly credit at the actor's listed price. Needs the APIFY_TOKEN secret.

  python signals.py            # runs only when due
  python signals.py --force    # run now
"""
import argparse
import datetime as dt
import json
import os
import tempfile
from pathlib import Path

from common import load_config, log, utcnow

ACTOR = "clockworks~tiktok-scraper"
PREFIX = "signals_"


def latest_file(drive):
    q = (f"name contains '{PREFIX}' and trashed=false and 'me' in owners and "
         "mimeType != 'application/vnd.google-apps.folder'")
    files = drive.files().list(q=q, orderBy="createdTime desc", pageSize=3,
                               fields="files(id,name,createdTime)").execute().get("files", [])
    files = [f for f in files if f["name"].endswith(".json")]
    return files[0] if files else None


def load(drive):
    """{page_key: [video dicts]} from the newest signals file, or {}."""
    try:
        from common import download
        f = latest_file(drive)
        if not f:
            return {}
        tmp = Path(tempfile.mkdtemp()) / "signals.json"
        download(drive, f["id"], tmp)
        data = json.loads(tmp.read_text(encoding="utf-8"))
        log(f"Signals loaded from {f['name']}")
        return {k.upper(): v for k, v in (data.get("pages") or {}).items() if isinstance(v, list)}
    except Exception as exc:
        log(f"Signals not loaded: {str(exc)[:120]}")
        return {}


def scrape(token, hashtag, n):
    import requests
    r = requests.post(f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items",
                      params={"token": token, "timeout": 240}, timeout=300,
                      json={"hashtags": [hashtag], "resultsPerPage": n, "shouldDownloadVideos": False,
                            "shouldDownloadCovers": False, "shouldDownloadSubtitles": False,
                            "shouldDownloadSlideshowImages": False, "shouldDownloadAvatars": False,
                            "shouldDownloadMusicCovers": False})
    if not r.ok:
        raise RuntimeError(f"{r.status_code} {r.text[:200]}")
    items = r.json()
    return items if isinstance(items, list) else []


def run(cfg, force=False):
    scfg = cfg.get("signals") or {}
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not scfg.get("enabled", True) or not token:
        return
    if not force and utcnow().hour < 4:
        return
    from common import drive_service, google_creds, render_folder_id, upload_render
    drive = drive_service(google_creds())
    last = latest_file(drive)
    if last and not force:
        made = dt.datetime.fromisoformat(last["createdTime"].replace("Z", "+00:00"))
        if utcnow() - made < dt.timedelta(hours=scfg.get("every_hours", 47)):
            return
    n = int(scfg.get("results_per_page", 12))
    since = utcnow() - dt.timedelta(days=scfg.get("max_age_days", 30))
    day = utcnow().timetuple().tm_yday
    out, total = {}, 0
    for page in cfg["pages"] + cfg.get("image_pages", []):
        tags = (page.get("image") or {}).get("signals_hashtags") or []
        if not tags:
            continue
        tag = tags[(day // 2) % len(tags)]
        try:
            items = scrape(token, tag, n)
        except Exception as exc:
            log(f"[{page['key']}] signals: Apify run failed for #{tag}: {str(exc)[:160]}")
            continue
        total += len(items)
        vids = []
        for it in items:
            if not isinstance(it, dict) or it.get("isAd") or it.get("isSponsored"):
                continue
            try:
                when = dt.datetime.fromisoformat(str(it.get("createTimeISO", "")).replace("Z", "+00:00"))
            except Exception:
                when = None
            if when and when < since:
                continue
            vids.append({"hashtag": tag, "text": str(it.get("text") or "")[:240],
                         "plays": int(it.get("playCount") or 0), "likes": int(it.get("diggCount") or 0),
                         "comments": int(it.get("commentCount") or 0), "shares": int(it.get("shareCount") or 0),
                         "url": it.get("webVideoUrl") or "", "created": str(it.get("createTimeISO") or "")[:10],
                         "seconds": int(((it.get("videoMeta") or {}).get("duration")) or 0)})
        vids.sort(key=lambda v: v["plays"], reverse=True)
        out[page["key"]] = vids[:8]
        log(f"[{page['key']}] signals: #{tag} -> {len(vids)} recent videos, top {vids[0]['plays'] if vids else 0:,} views")
    if not out:
        return
    path = Path(tempfile.mkdtemp()) / f"{PREFIX}{utcnow():%Y%m%d_%H%M}.json"
    path.write_text(json.dumps({"source": "Apify TikTok Scraper", "made_at_utc": utcnow().isoformat(timespec="seconds"),
                                "results_scraped": total, "pages": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    upload_render(drive, path, path.name, render_folder_id(drive), mime="application/json")
    log(f"signals: saved {path.name} ({total} results scraped)")


def hint(videos, k=5):
    """Prompt text for the writer: what is getting attention in the niche (inspiration, never copied)."""
    top = [v for v in videos if v.get("text")][:k]
    if not top:
        return ""
    lines = "\n".join(f"- {v['plays']:,} views, {v['shares']:,} shares: \"{v['text'][:160]}\"" for v in top)
    return ("Most-watched recent TikToks in this niche (real numbers; use only to understand which TOPICS and ANGLES "
            "people care about right now; never copy their wording, claims or numbers; verify any fact yourself):\n" + lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if not os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip():
        return
    run(load_config(), force=args.force)


if __name__ == "__main__":
    main()
