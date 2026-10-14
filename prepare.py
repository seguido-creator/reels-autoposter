"""Prepare stage (runs twice a day): turns queued clips into finished, enhanced reels ahead of time.

For each Page it keeps `ready_buffer_per_page` reels READY. Each finished reel is saved to your
Drive folder "Reels Autoposter - Renders" and gets a preview link in the Sheet, so you can
watch it on your phone and type OK or SKIP in the "approve" column.

  python prepare.py            # all pages
  python prepare.py PH         # one page
"""
import shutil
import sys
import tempfile
from pathlib import Path

from common import (delete_render, download, drive_service, google_creds, load_config, log,
                    open_sheet, parse_time, read_rows, render_folder_id, update_row,
                    upload_render, utcnow)
import transform

MAX_ATTEMPTS_EXTRA = 4  # broken/unsuitable clips we tolerate per run before giving up
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".3gp", ".mpeg", ".mpg"}
RETRYABLE = ("mime type", "mimetype", "503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED",
             "high demand", "overloaded")


def is_retryable(note):
    """FAILED rows caused by temporary/tooling errors get another chance."""
    return any(t.lower() in (note or "").lower() for t in RETRYABLE)


def housekeeping(ws, rows, drive, cfg):
    """Apply SKIPs and expire unapproved low-value renders so Drive doesn't fill up."""
    now = utcnow()
    for r, row in rows:
        approve = row["approve"].upper()
        if row["status"] in ("READY", "NEEDS_OK") and approve == "SKIP":
            delete_render(drive, row["render_id"])
            update_row(ws, r, {"status": "SKIPPED", "render_id": "", "preview": ""})
            row.update(status="SKIPPED")
        elif row["status"] == "NEEDS_OK" and approve != "OK":
            ready = parse_time(row["ready_at_utc"])
            if ready and (now - ready).days >= cfg["expire_needs_ok_days"]:
                delete_render(drive, row["render_id"])
                update_row(ws, r, {"status": "EXPIRED", "render_id": "", "preview": ""})
                row.update(status="EXPIRED")


def prepare_page(page, cfg, drive, sheet, folder_id):
    import os
    if not os.environ.get(page["page_id_env"]) or not os.environ.get(page["token_env"]):
        log(f"[{page['key']}] no Facebook secrets yet, skipping")
        return
    ws = sheet.worksheet(page["sheet_tab"])
    rows = read_rows(ws)
    housekeeping(ws, rows, drive, cfg)

    ready = sum(1 for _, row in rows if row["status"] == "READY")
    need = cfg["ready_buffer_per_page"] - ready
    log(f"[{page['key']}] {ready} READY, preparing {max(need, 0)} more")
    if need <= 0:
        return

    queue = [(r, row) for r, row in rows
             if row["file_id"] and row["approve"].upper() != "SKIP"
             and (not row["status"] or (row["status"] == "FAILED" and is_retryable(row["note"])))]
    made, attempts = 0, 0
    for r, row in queue:
        if made >= need or attempts >= need + MAX_ATTEMPTS_EXTRA:
            break
        attempts += 1
        work = Path(tempfile.mkdtemp(prefix="prep_"))
        try:
            log(f"[{page['key']}] row {r}: {row['file_name']}")
            ext = Path(row["file_name"]).suffix.lower()
            src = work / ("src" + (ext if ext in VIDEO_EXT else ".mp4"))
            download(drive, row["file_id"], src)
            duration, _ = transform.probe(src)
            if duration < cfg["min_source_seconds"]:
                update_row(ws, r, {"status": "SKIPPED", "note": f"too short ({duration:.1f}s)"})
                continue

            script = transform.write_script(src, page, duration)
            out = work / "reel.mp4"
            transform.render(src, script, page, work, out)

            name = f"{page['key']}_row{r}_{Path(row['file_name']).stem[:40]}.mp4"
            render_id, link = upload_render(drive, out, name, folder_id)
            low = script["value_score"] < cfg["min_value_score"]
            caption = script["caption"] + ("\n\n" + " ".join(script["hashtags"])
                                           if script["hashtags"] else "")
            update_row(ws, r, {
                "status": "NEEDS_OK" if low else "READY",
                "preview": link, "hook": script["hook"],
                "voiceover": f"{script['intro_vo']} || {script['insight_vo']}",
                "caption": caption, "value_score": script["value_score"],
                "ready_at_utc": utcnow().isoformat(timespec="seconds"),
                "render_id": render_id,
                "note": "low value score - posts only if you type OK" if low else ""})
            if not low:
                made += 1
            log(f"[{page['key']}] row {r} -> {'NEEDS_OK' if low else 'READY'} "
                f"(value {script['value_score']})")
        except transform.Unsuitable as exc:
            update_row(ws, r, {"status": "UNSUITABLE", "note": str(exc)})
            log(f"[{page['key']}] row {r} unsuitable: {exc}")
        except Exception as exc:
            update_row(ws, r, {"status": "FAILED", "note": str(exc)[:450]})
            log(f"[{page['key']}] row {r} FAILED: {exc}")
        finally:
            shutil.rmtree(work, ignore_errors=True)


def main():
    import os
    if not os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip():
        log("Setup not finished (Google secrets missing) - nothing to do yet")
        return
    only = sys.argv[1].upper() if len(sys.argv) > 1 else ""
    cfg = load_config()
    creds = google_creds()
    drive, sheet = drive_service(creds), open_sheet(creds)
    folder_id = render_folder_id(drive)
    for page in cfg["pages"]:
        if only and page["key"].upper() != only:
            continue
        try:
            prepare_page(page, cfg, drive, sheet, folder_id)
        except Exception as exc:
            log(f"[{page['key']}] error: {exc}")


if __name__ == "__main__":
    main()
