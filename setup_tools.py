"""One-off setup tasks, run from GitHub Actions ("Setup tools" workflow).

  python setup_tools.py check        # tests every connection (creates the empty render folder)
  python setup_tools.py build        # indexes the Drive folder into the Sheet (first time)
  python setup_tools.py rebuild      # wipes the queue tabs and re-indexes (DANGER: loses post history)
  python setup_tools.py add-new      # appends only videos not yet in any tab (safe, keeps history)
"""
import os
import random
import sys

from common import (COL, HEADER, drive_service, env, google_creds, load_config, log, new_row,
                    open_sheet, render_folder_id)

FOLDER_MIME = "application/vnd.google-apps.folder"


def list_videos(drive, root_id):
    """Walk the folder tree and return [(file_id, name, folder_path)] for every video."""
    videos, stack = [], [(root_id, "")]
    while stack:
        folder_id, path = stack.pop()
        token = None
        while True:
            resp = drive.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken, files(id, name, mimeType)",
                pageSize=1000, pageToken=token,
                supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
            for f in resp.get("files", []):
                if f["mimeType"] == FOLDER_MIME:
                    stack.append((f["id"], f"{path}/{f['name']}"))
                elif f["mimeType"].startswith("video/"):
                    videos.append((f["id"], f["name"], path or "/"))
            token = resp.get("nextPageToken")
            if not token:
                break
        log(f"Scanned {path or '/'} - {len(videos)} videos so far")
    return videos


def write_tab(sheet, title, rows):
    try:
        ws = sheet.worksheet(title)
        ws.clear()
    except Exception:
        ws = sheet.add_worksheet(title=title, rows=10, cols=len(HEADER))
    ws.resize(rows=len(rows) + 1, cols=len(HEADER))
    ws.update(values=[HEADER], range_name="A1")
    chunk = 5000
    for i in range(0, len(rows), chunk):
        part = rows[i:i + chunk]
        ws.update(values=[new_row(file_id=r[0], file_name=r[1], folder=r[2]) for r in part],
                  range_name=f"A{i + 2}")
        log(f"  {title}: wrote {i + len(part)}/{len(rows)} rows")
    ws.freeze(rows=1)
    add_approve_dropdown(sheet, ws, len(rows) + 1)


def add_approve_dropdown(sheet, ws, last_row):
    """OK / SKIP dropdown in the approve column (still accepts typing)."""
    col = COL["approve"] - 1
    sheet.batch_update({"requests": [{"setDataValidation": {
        "range": {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": last_row,
                  "startColumnIndex": col, "endColumnIndex": col + 1},
        "rule": {"condition": {"type": "ONE_OF_LIST",
                               "values": [{"userEnteredValue": "OK"}, {"userEnteredValue": "SKIP"}]},
                 "showCustomUi": True, "strict": False}}}]})


def existing_ids(sheet, cfg):
    ids, posted = set(), 0
    for p in cfg["pages"]:
        try:
            ws = sheet.worksheet(p["sheet_tab"])
        except Exception:
            continue
        ids.update(ws.col_values(COL["file_id"])[1:])
        posted += sum(1 for s in ws.col_values(COL["status"])[1:] if s == "POSTED")
        if ws.col_values(1)[:1] and ws.col_values(1)[0] != HEADER[0]:
            sys.exit(f"Tab {p['sheet_tab']} uses an old column layout. Run 'rebuild'.")
    return ids, posted


def build(mode):
    cfg = load_config()
    creds = google_creds()
    drive, sheet = drive_service(creds), open_sheet(creds)
    known, posted = existing_ids(sheet, cfg)

    if mode == "build" and known:
        sys.exit("Queue tabs already contain videos. Use 'add-new' to append new videos, "
                 "or 'rebuild' to wipe and start over.")
    if mode == "rebuild" and posted:
        log(f"WARNING: wiping {posted} POSTED rows of history")

    videos = list_videos(drive, env("LIBRARY_FOLDER_ID"))
    log(f"Found {len(videos)} videos in Drive")
    if mode == "add-new":
        videos = [v for v in videos if v[0] not in known]
        log(f"{len(videos)} are new")
    if not videos:
        return

    random.Random(42).shuffle(videos)
    pages = cfg["pages"]
    pools = {p["sheet_tab"]: [] for p in pages}
    unused = 0
    for v in videos:  # each Page only gets clips from its own niche folders
        path = v[2].upper()
        for p in pages:
            if any(f.upper() in path for f in p.get("source_folders", [])):
                pools[p["sheet_tab"]].append(v)
                break
        else:
            unused += 1
    for tab, rows in pools.items():
        log(f"  {tab}: {len(rows)} niche videos")
    log(f"  {unused} videos are outside the chosen niches (left unused)")

    if mode == "add-new":
        for tab, rows in pools.items():
            ws = sheet.worksheet(tab)
            ws.append_rows([new_row(file_id=r[0], file_name=r[1], folder=r[2]) for r in rows],
                           value_input_option="RAW")
            add_approve_dropdown(sheet, ws, ws.row_count)
            log(f"  {tab}: appended {len(rows)}")
    else:
        for tab, rows in pools.items():
            write_tab(sheet, tab, rows)
        try:  # remove the default empty tab if present
            default = sheet.worksheet("Sheet1")
            if len(sheet.worksheets()) > 1:
                sheet.del_worksheet(default)
        except Exception:
            pass
    log("Done.")


def check():
    import requests
    cfg = load_config()
    ok = True

    def result(name, good, detail=""):
        nonlocal ok
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  {name}  {detail}")

    try:
        creds = google_creds()
        result("Google login", True)
    except Exception as e:
        result("Google login", False, str(e)); sys.exit(1)

    drive = drive_service(creds)
    try:
        folder = drive.files().get(fileId=env("LIBRARY_FOLDER_ID"), fields="name",
                                   supportsAllDrives=True).execute()
        resp = drive.files().list(q=f"'{env('LIBRARY_FOLDER_ID')}' in parents and trashed=false",
                                  fields="files(id,name,mimeType)", pageSize=20,
                                  supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        result("Drive folder", True, f"'{folder['name']}' - first page has {len(resp['files'])} items")
        vid = next((f for f in resp["files"] if f["mimeType"].startswith("video/")), None)
        if vid:
            req = drive.files().get_media(fileId=vid["id"], supportsAllDrives=True)
            req.headers["Range"] = "bytes=0-1023"
            req.execute()
            result("Drive video download", True, vid["name"])
        else:
            print("INFO  No video in the top level (probably in subfolders) - download test skipped")
    except Exception as e:
        result("Drive folder/download", False, str(e)[:300])

    try:
        render_folder_id(drive)
        result("Drive render folder (write access)", True)
    except Exception as e:
        result("Drive render folder (write access)", False,
               "re-create the refresh token with all 3 scopes. " + str(e)[:200])

    try:
        sheet = open_sheet(creds)
        result("Google Sheet", True, f"'{sheet.title}' tabs: {[w.title for w in sheet.worksheets()]}")
    except Exception as e:
        result("Google Sheet", False, str(e)[:300])

    if os.environ.get("GEMINI_API_KEY"):
        try:
            from google import genai
            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
            import transform
            for m in transform.script_models():
                try:
                    r = transform.with_retry(lambda: client.models.generate_content(
                        model=m, contents="Reply with the word OK"), tries=2)
                    print(f"INFO  Gemini model {m}: available")
                except Exception as e:
                    print(f"INFO  Gemini model {m}: {str(e)[:90]}")
            r, used = transform.generate(client, "Reply with the word OK")
            result("Gemini", True, f"model {used}: {r.text.strip()[:20]}")
        except Exception as e:
            result("Gemini", False, str(e)[:300])
        try:
            import tempfile, transform
            out = os.path.join(tempfile.mkdtemp(), "t.wav")
            secs = transform.speak("Testing the voice. Mabuhay!", cfg["pages"][-1], out)
            result("Gemini voice (TTS)", True, f"{secs:.1f}s of audio")
        except Exception as e:
            result("Gemini voice (TTS)", False, str(e)[:300])
    else:
        result("Gemini", False, "GEMINI_API_KEY secret missing")

    for p in cfg["pages"]:
        pid, tok = os.environ.get(p["page_id_env"], ""), os.environ.get(p["token_env"], "")
        if not pid or not tok:
            print(f"SKIP  Facebook {p['key']}  (secrets not added yet)")
            continue
        r = requests.get(f"https://graph.facebook.com/{cfg['graph_api_version']}/{pid}",
                         params={"fields": "name", "access_token": tok}, timeout=30)
        result(f"Facebook {p['key']}", r.ok, r.json().get("name", r.text[:200]))

    print("\nALL GOOD" if ok else "\nFix the FAIL lines above (see README troubleshooting).")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        check()
    elif cmd in ("build", "rebuild", "add-new"):
        build(cmd)
    else:
        sys.exit(__doc__)
