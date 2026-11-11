"""Byahe ni Nanay: posts the owner's ready-made travel videos (Reels + long-forms) to the
"Byahe ni Nanay" Page, one per day, in the order of queue.json in the Drive folder
"Byahe ni Nanay - Queue". Nothing is generated here; the videos are final files.

  python byahe.py            # called by the runner every 20 min; posts only when live and due
  python byahe.py --check    # safe: tests token, Drive folder and queue, posts nothing
  python byahe.py --now      # post the next item right away (manual run, needs live=true)

State lives in the "BYA" tab of the Reels Queue sheet (one row per posted item).
"""
import datetime as dt
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from common import download, drive_service, google_creds, load_config, log, open_sheet

TAB_HEADER = ["n", "file", "type", "title", "status", "posted_at_utc", "fb_id", "note"]


def settings():
    b = load_config().get("byahe", {})
    b.setdefault("folder", "Byahe ni Nanay - Queue")
    b.setdefault("sheet_tab", "BYA")
    b.setdefault("timezone", "Asia/Manila")
    b.setdefault("post_time", "19:00")
    b.setdefault("live", False)
    b.setdefault("page_id_env", "FB_PAGE_ID_BYA")
    b.setdefault("token_env", "FB_TOKEN_BYA")
    return b


def graph():
    return f"https://graph.facebook.com/{load_config()['graph_api_version']}"


# ---------------------------------------------------------------- Drive
def folder_files(drive, name):
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    found = drive.files().list(q=q, fields="files(id,name)", pageSize=5).execute().get("files", [])
    if not found:
        return None, {}
    fid = found[0]["id"]
    files, token = {}, None
    while True:
        resp = drive.files().list(q=f"'{fid}' in parents and trashed=false", pageSize=1000,
                                  fields="nextPageToken, files(id,name,size)", pageToken=token).execute()
        for f in resp.get("files", []):
            files[f["name"]] = f
        token = resp.get("nextPageToken")
        if not token:
            return fid, files


def load_queue(drive, files):
    if "queue.json" not in files:
        return None
    tmp = Path(tempfile.mkdtemp()) / "queue.json"
    download(drive, files["queue.json"]["id"], tmp)
    return sorted(json.loads(tmp.read_text(encoding="utf-8")), key=lambda x: x["n"])


# ---------------------------------------------------------------- Sheet
def state_tab(sheet, name):
    try:
        return sheet.worksheet(name)
    except Exception:
        ws = sheet.add_worksheet(title=name, rows=200, cols=len(TAB_HEADER))
        ws.append_row(TAB_HEADER, value_input_option="RAW")
        return ws


def posted(ws):
    rows = ws.get_all_values()[1:]
    return {r[1]: r for r in rows if len(r) > 4 and r[4] in ("posted", "processing")}, rows


# ---------------------------------------------------------------- Facebook
def page_name(page_id, token):
    import requests
    r = requests.get(f"{graph()}/{page_id}", params={"fields": "name", "access_token": token}, timeout=30)
    return r.ok, r.json().get("name") if r.ok else r.text[:300]


def fit_reel(path, limit=89.5):
    """Reels API accepts 3-90 s. Trim a slightly long Reel with a soft fade (needs ffmpeg)."""
    import shutil
    import subprocess
    if not shutil.which("ffmpeg"):
        return path
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(path)], capture_output=True, text=True).stdout or 0)
    if dur <= limit:
        return path
    out = path.with_name(path.stem + "_fit.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-t", str(limit),
                    "-vf", f"fade=t=out:st={limit - 1.2}:d=1.2", "-af", f"afade=t=out:st={limit - 2}:d=2",
                    "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)], check=True)
    log(f"[BYA] trimmed {dur:.1f}s -> {limit}s for the Reels limit")
    return out


def set_cover(video_id, token, image_path):
    """Custom cover from the owner's thumbnail. Never fails the post."""
    import requests
    try:
        with open(image_path, "rb") as fh:
            r = requests.post(f"{graph()}/{video_id}/thumbnails", data={"is_preferred": "true", "access_token": token},
                              files={"source": ("thumb.jpg", fh, "image/jpeg")}, timeout=120)
        log(f"[BYA] cover: {r.status_code} {r.text[:200]}")
        return r.ok
    except Exception as exc:
        log(f"[BYA] cover not set: {exc}")
        return False


def set_page_photos(page_id, token, drive, files):
    """Profile picture + cover from page_profile.jpg / page_cover.jpg in the Drive folder."""
    import requests
    tmp = Path(tempfile.mkdtemp())
    for name, kind in (("page_profile.jpg", "profile"), ("page_cover.jpg", "cover")):
        if name not in files:
            print(f"{kind}: {name} not in Drive folder")
            continue
        p = tmp / name
        download(drive, files[name]["id"], p)
        with open(p, "rb") as fh:
            r = requests.post(f"{graph()}/{page_id}/photos", data={"published": "false", "access_token": token},
                              files={"source": (name, fh, "image/jpeg")}, timeout=120)
        if not r.ok:
            print(f"{kind}: photo upload failed {r.status_code} {r.text[:300]}")
            continue
        pid = r.json()["id"]
        if kind == "profile":
            r = requests.post(f"{graph()}/{page_id}/picture", data={"photo": pid, "access_token": token}, timeout=60)
        else:
            r = requests.post(f"{graph()}/{page_id}", data={"cover": pid, "access_token": token}, timeout=60)
        print(f"{kind}: {r.status_code} {r.text[:300]}")


def post_reel(page_id, token, path, caption):
    from autopost import publish_reel
    return publish_reel(page_id, token, str(path), caption, load_config()["graph_api_version"])


def post_video(page_id, token, path, title, description):
    """Long-form: chunked upload to /{page}/videos (upload_phase start/transfer/finish)."""
    import requests
    url = f"https://graph-video.facebook.com/{load_config()['graph_api_version']}/{page_id}/videos"
    size = os.path.getsize(path)
    r = requests.post(url, data={"upload_phase": "start", "file_size": size, "access_token": token}, timeout=120)
    if not r.ok:
        raise RuntimeError(f"Start failed: {r.status_code} {r.text[:300]}")
    j = r.json()
    session, video_id = j["upload_session_id"], j["video_id"]
    start, end = int(j["start_offset"]), int(j["end_offset"])
    with open(path, "rb") as fh:
        while start < end:
            fh.seek(start)
            chunk = fh.read(end - start)
            for attempt in range(4):
                r = requests.post(url, data={"upload_phase": "transfer", "upload_session_id": session,
                                             "start_offset": start, "access_token": token},
                                  files={"video_file_chunk": ("chunk", chunk)}, timeout=600)
                if r.ok:
                    break
                time.sleep(10 * (attempt + 1))
            if not r.ok:
                raise RuntimeError(f"Transfer failed at {start}: {r.status_code} {r.text[:300]}")
            start, end = int(r.json()["start_offset"]), int(r.json()["end_offset"])
            log(f"  uploaded {start / size:.0%}")
    r = requests.post(url, data={"upload_phase": "finish", "upload_session_id": session, "title": title,
                                 "description": description, "published": "true", "access_token": token},
                      timeout=300)
    if not r.ok or not r.json().get("success"):
        raise RuntimeError(f"Finish failed: {r.status_code} {r.text[:300]}")
    return video_id, "published"


# ---------------------------------------------------------------- main
def main():
    args = sys.argv[1:]
    check, now_flag, photos = "--check" in args, "--now" in args, "--photos" in args
    b = settings()
    page_id = os.environ.get(b["page_id_env"], "").strip()
    token = os.environ.get(b["token_env"], "").strip()

    if not check and not photos and not b["live"]:
        log("[BYA] not live yet (config byahe.live=false), skipping")
        return
    if not page_id or not token:
        log("[BYA] no Page ID/token secret yet, skipping")
        return

    tz = ZoneInfo(b["timezone"])
    local = dt.datetime.now(tz)
    hh, mm = map(int, b["post_time"].split(":"))
    due_time = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    start = b.get("start_date")
    if not check and not photos and start and local.date().isoformat() < start:
        log(f"[BYA] starts on {start}")
        return
    if not check and not photos and not now_flag and local < due_time:
        log(f"[BYA] not due yet ({local:%H:%M} < {b['post_time']} {b['timezone']})")
        return

    if check:
        ok, name = page_name(page_id, token)
        print(f"Page: {'OK ' + str(name) if ok else 'FAIL ' + str(name)}")

    creds = google_creds()
    drive = drive_service(creds)
    fid, files = folder_files(drive, b["folder"])
    if not fid:
        log(f"[BYA] Drive folder '{b['folder']}' not found")
        return
    if photos:
        set_page_photos(page_id, token, drive, files)
        return
    queue = load_queue(drive, files)
    if not queue:
        log("[BYA] queue.json missing in the Drive folder")
        return
    sheet = open_sheet(creds)
    ws = state_tab(sheet, b["sheet_tab"])
    done, rows = posted(ws)
    today = local.date().isoformat()
    todays = [r for r in rows if len(r) > 5 and r[5] and
              dt.datetime.fromisoformat(r[5]).astimezone(tz).date().isoformat() == today]
    nxt = next((q for q in queue if q["file"] not in done), None)

    if check:
        missing = [q["file"] for q in queue if q["file"] not in files]
        covers = sum(1 for q in queue if q["file"][:-4] + "_THUMB.jpg" in files)
        print(f"Covers (thumbnails) in Drive: {covers}/{len(queue)}")
        print(f"Drive folder: {len(files)} files, queue {len(queue)} items, missing videos: {len(missing)}")
        for m in missing[:10]:
            print("  missing:", m)
        print(f"Posted so far: {len(done)}; next: {nxt['file'] if nxt else 'none (all done)'}")
        print(f"Live: {b['live']}; posts daily at {b['post_time']} {b['timezone']}")
        return

    if not nxt:
        log("[BYA] queue finished, nothing left to post")
        return
    if todays and not now_flag:
        log(f"[BYA] already posted today ({todays[-1][1]})")
        return
    if nxt["file"] not in files:
        log(f"[BYA] video not in Drive yet: {nxt['file']} (still uploading?)")
        return

    path = Path(tempfile.mkdtemp()) / nxt["file"]
    log(f"[BYA] downloading {nxt['file']}")
    download(drive, files[nxt["file"]]["id"], path)
    row = [nxt["n"], nxt["file"], nxt["type"], nxt["title"], "processing",
           dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "", ""]
    ws.append_row([str(x) for x in row], value_input_option="RAW")
    rownum = len(ws.get_all_values())
    try:
        if nxt["type"].lower().startswith("reel"):
            vid, status = post_reel(page_id, token, fit_reel(path), nxt["caption"])
        else:
            vid, status = post_video(page_id, token, path, nxt["title"], nxt["caption"])
        thumb = nxt["file"][:-4] + "_THUMB.jpg"
        if thumb in files:
            tp = path.with_name(thumb)
            download(drive, files[thumb]["id"], tp)
            if set_cover(vid, token, tp):
                status += ", cover set"
        ws.update(f"E{rownum}:H{rownum}", [["posted", row[5], str(vid), status]], value_input_option="RAW")
        log(f"[BYA] posted #{nxt['n']} {nxt['file']} -> {vid} ({status})")
    except Exception as exc:
        ws.update(f"E{rownum}:H{rownum}", [["failed", row[5], "", str(exc)[:300]]], value_input_option="RAW")
        log(f"[BYA] FAILED #{nxt['n']}: {exc}")
        raise


if __name__ == "__main__":
    main()
