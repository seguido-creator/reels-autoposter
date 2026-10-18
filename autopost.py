"""Posting stage (runs hourly): publishes a prepared reel when a Page's slot is due.

Which reel gets posted, in Sheet order:
  - approve = OK                                   -> posts (READY or NEEDS_OK)
  - approve blank, status READY, ready > review_hours ago -> posts (you didn't object)
  - approve blank, READY but newer                 -> posts only in the last hour of a slot
                                                      window if nothing else is available
  - approve = SKIP, status NEEDS_OK / FAILED / ...  -> never posts

  python autopost.py --precheck        # time-only check for GitHub Actions
  python autopost.py                   # normal run
  python autopost.py --force PH        # post the best available reel to PH now
"""
import argparse
import datetime as dt
import os
import shutil
import tempfile
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from common import load_config, log, parse_time, utcnow


# ---------------------------------------------------------------- scheduling
def slot_starts(page, now_utc, window_hours):
    """(label, start) for slots whose posting window is open now."""
    tz = ZoneInfo(page["timezone"])
    now = now_utc.astimezone(tz)
    out = []
    for day_offset in (-1, 0):
        day = (now + dt.timedelta(days=day_offset)).date()
        for slot in page["slots"]:
            hh, mm = (int(x) for x in slot.split(":"))
            start = dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
            if start <= now < start + dt.timedelta(hours=window_hours):
                out.append((start.strftime("%Y-%m-%d %H:%M"), start))
    return sorted(out)


def precheck(cfg):
    now = utcnow()
    due = any(slot_starts(p, now, cfg["slot_window_hours"]) for p in cfg["pages"])
    if not os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip():
        log("Setup not finished (Google secrets missing) - nothing to do yet")
        due = False
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as fh:
            fh.write(f"due={'true' if due else 'false'}\n")
    log(f"Precheck: a posting window is {'OPEN' if due else 'closed'}")


def pick_reel(rows, cfg, now, allow_fresh):
    """Choose the row to post. rows: list of (row_number, dict)."""
    review = dt.timedelta(hours=cfg["review_hours"])
    approved, aged, fresh = [], [], []
    for r, row in rows:
        approve, status = row["approve"].upper(), row["status"]
        if not row["render_id"] or status not in ("READY", "NEEDS_OK") or approve == "SKIP":
            continue
        if approve == "OK":
            approved.append((r, row))
        elif status == "READY":
            ready = parse_time(row["ready_at_utc"])
            (aged if ready and now - ready >= review else fresh).append((r, row))
    for group in (approved, aged, fresh if allow_fresh else []):
        if group:
            return group[0]
    return None


# ---------------------------------------------------------------- Facebook
def publish_reel(page_id, token, video_path, description, api_ver):
    import requests

    graph = f"https://graph.facebook.com/{api_ver}"
    r = requests.post(f"{graph}/{page_id}/video_reels",
                      json={"upload_phase": "start", "access_token": token}, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Start failed: {r.status_code} {r.text[:300]}")
    video_id = r.json()["video_id"]

    size = os.path.getsize(video_path)
    with open(video_path, "rb") as fh:
        r = requests.post(f"https://rupload.facebook.com/video-upload/{api_ver}/{video_id}",
                          headers={"Authorization": f"OAuth {token}", "offset": "0",
                                   "file_size": str(size),
                                   "Content-Type": "application/octet-stream"},
                          data=fh, timeout=900)
    if not r.ok or not r.json().get("success"):
        raise RuntimeError(f"Upload failed: {r.status_code} {r.text[:300]}")

    r = requests.post(f"{graph}/{page_id}/video_reels",
                      params={"access_token": token, "video_id": video_id,
                              "upload_phase": "finish", "video_state": "PUBLISHED",
                              "description": description}, timeout=60)
    if not r.ok or not r.json().get("success"):
        raise RuntimeError(f"Publish failed: {r.status_code} {r.text[:300]}")

    for _ in range(36):  # poll up to ~6 minutes
        time.sleep(10)
        s = requests.get(f"{graph}/{video_id}", params={"fields": "status", "access_token": token},
                         timeout=30).json().get("status", {})
        err = (s.get("processing_phase") or {}).get("error")
        if err:
            raise RuntimeError(f"Processing error: {err}")
        if (s.get("publishing_phase") or {}).get("status") == "complete" or s.get("video_status") == "ready":
            return video_id, "published"
    return video_id, "still processing (Facebook will finish it)"


# ---------------------------------------------------------------- main
def process_page(page, cfg, drive, sheet, now, force=False):
    from common import delete_render, download, read_rows, update_row

    page_id = os.environ.get(page["page_id_env"], "").strip()
    token = os.environ.get(page["token_env"], "").strip()
    if not page_id or not token:
        log(f"[{page['key']}] no Page ID/token secret yet, skipping")
        return

    ws = sheet.worksheet(page["sheet_tab"])
    rows = read_rows(ws)
    done_slots = {row["slot"] for _, row in rows if row["slot"]}

    if force:
        label = "manual " + now.astimezone(ZoneInfo(page["timezone"])).strftime("%Y-%m-%d %H:%M")
        allow_fresh = True
    else:
        open_ = [(l, s) for l, s in slot_starts(page, now, cfg["slot_window_hours"])
                 if l not in done_slots]
        if not open_:
            log(f"[{page['key']}] nothing due")
            return
        label, start = open_[0]
        last_hour = now >= start + dt.timedelta(hours=cfg["slot_window_hours"] - 1)
        allow_fresh = last_hour

    recent = sum(1 for _, row in rows
                 if (t := parse_time(row["posted_at_utc"])) and now - t < dt.timedelta(hours=24))
    if recent >= cfg["max_posts_per_24h_per_page"]:
        log(f"[{page['key']}] 24h cap reached ({recent}), skipping")
        return

    for _ in range(2):  # if one upload fails, try the next reel
        choice = pick_reel(rows, cfg, now, allow_fresh)
        if not choice:
            log(f"[{page['key']}] slot {label}: no reel available yet "
                f"({'waiting for review window' if not allow_fresh else 'run Prepare'})")
            return
        r, row = choice
        work = Path(tempfile.mkdtemp(prefix="post_"))
        try:
            log(f"[{page['key']}] slot {label}: posting row {r} '{row['file_name']}'")
            path = work / "reel.mp4"
            download(drive, row["render_id"], path)
            video_id, state = publish_reel(page_id, token, path, row["caption"],
                                           cfg["graph_api_version"])
            delete_render(drive, row["render_id"])
            import engage
            state += engage.after_post(page, cfg, video_id, token, row["caption"])
            update_row(ws, r, {"status": "POSTED", "slot": label,
                               "posted_at_utc": utcnow().isoformat(timespec="seconds"),
                               "fb_video_id": video_id, "render_id": "", "preview": "",
                               "note": state})
            log(f"[{page['key']}] POSTED video {video_id} ({state})")
            return
        except Exception as exc:
            log(f"[{page['key']}] FAILED row {r}: {exc}")
            update_row(ws, r, {"status": "POST_FAILED", "note": str(exc)[:450]})
            row["status"] = "POST_FAILED"
        finally:
            shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--precheck", action="store_true")
    ap.add_argument("--force", default="", help="page key to post to immediately, e.g. PH")
    args = ap.parse_args()
    cfg = load_config()
    if args.precheck:
        precheck(cfg)
        return

    from common import drive_service, google_creds, open_sheet
    creds = google_creds()
    drive, sheet = drive_service(creds), open_sheet(creds)
    now = utcnow()
    force = args.force.strip().upper()
    for page in cfg["pages"]:
        if force and page["key"].upper() != force:
            continue
        try:
            process_page(page, cfg, drive, sheet, now, force=bool(force))
        except Exception as exc:
            log(f"[{page['key']}] error: {exc}")


if __name__ == "__main__":
    main()
