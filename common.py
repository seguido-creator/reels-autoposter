"""Shared helpers: config, Google auth, Drive and Sheet access, row helpers."""
import datetime as dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Sheet layout. "approve" is first so it's easy to tap on a phone.
HEADER = ["approve", "status", "preview", "hook", "voiceover", "caption", "value_score",
          "file_name", "file_id", "folder", "ready_at_utc", "render_id",
          "slot", "posted_at_utc", "fb_video_id", "note"]
COL = {name: i + 1 for i, name in enumerate(HEADER)}

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",   # read the shared video library
    "https://www.googleapis.com/auth/drive.file",       # create/delete ONLY its own render files
    "https://www.googleapis.com/auth/spreadsheets",
]
RENDER_FOLDER_NAME = "Reels Autoposter - Renders"


def log(msg):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp} UTC] {msg}", flush=True)


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def load_config():
    with open(ROOT / "config.json", encoding="utf-8") as fh:
        return json.load(fh)


def env(name, required=True):
    value = os.environ.get(name, "").strip()
    if required and not value:
        sys.exit(f"Missing required secret/env: {name}")
    return value


def google_creds():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials(
        token=None,
        refresh_token=env("GOOGLE_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=env("GOOGLE_CLIENT_ID"),
        client_secret=env("GOOGLE_CLIENT_SECRET"),
        scopes=GOOGLE_SCOPES,
    )
    creds.refresh(Request())
    return creds


def drive_service(creds):
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def open_sheet(creds):
    import gspread
    return gspread.authorize(creds).open_by_key(env("SHEET_ID"))


# ---------------------------------------------------------------- sheet rows
def read_rows(ws):
    """Return list of (row_number, dict) for all data rows."""
    values = ws.get_all_values()
    rows = []
    for i, raw in enumerate(values[1:], start=2):
        raw = raw + [""] * (len(HEADER) - len(raw))
        rows.append((i, {name: raw[COL[name] - 1].strip() for name in HEADER}))
    return rows


def new_row(**fields):
    return [str(fields.get(name, "")) for name in HEADER]


def update_row(ws, row, values):
    import gspread
    cells = [gspread.Cell(row, COL[name], str(value)) for name, value in values.items()]
    ws.update_cells(cells, value_input_option="RAW")


def parse_time(value):
    try:
        t = dt.datetime.fromisoformat(value)
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- drive files
def download(drive, file_id, dest):
    from googleapiclient.http import MediaIoBaseDownload
    req = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
    with open(dest, "wb") as fh:
        dl = MediaIoBaseDownload(fh, req, chunksize=32 * 1024 * 1024)
        done = False
        while not done:
            _, done = dl.next_chunk()


def render_folder_id(drive):
    q = (f"name='{RENDER_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' "
         "and trashed=false and 'me' in owners")
    found = drive.files().list(q=q, fields="files(id)", pageSize=1).execute().get("files", [])
    if found:
        return found[0]["id"]
    meta = {"name": RENDER_FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"}
    return drive.files().create(body=meta, fields="id").execute()["id"]


def latest_trends(drive):
    """Newest 'trends_*.json' file in Drive (written by the weekly trend scan).
    Returns {page_key: [{"angle", "hook", ...}]} or {} if none / unreadable."""
    import json
    import tempfile
    try:
        q = ("name contains 'trends_' and trashed=false and 'me' in owners and "
             "mimeType != 'application/vnd.google-apps.folder'")
        files = drive.files().list(q=q, orderBy="createdTime desc", pageSize=5,
                                   fields="files(id,name,createdTime)").execute().get("files", [])
        files = [f for f in files if f["name"].endswith(".json")]
        if not files:
            return {}
        tmp = Path(tempfile.mkdtemp()) / "trends.json"
        download(drive, files[0]["id"], tmp)
        data = json.loads(tmp.read_text(encoding="utf-8"))
        pages = data.get("pages", data)
        log(f"Trends loaded from {files[0]['name']}")
        return {k.upper(): [t for t in v if isinstance(t, dict)] for k, v in pages.items()
                if isinstance(v, list)}
    except Exception as exc:
        log(f"Trends not loaded: {exc}")
        return {}


def upload_render(drive, path, name, folder_id, mime="video/mp4"):
    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(str(path), mimetype=mime, resumable=True,
                            chunksize=16 * 1024 * 1024)
    f = drive.files().create(body={"name": name, "parents": [folder_id]}, media_body=media,
                             fields="id, webViewLink").execute()
    return f["id"], f["webViewLink"]


def delete_render(drive, file_id):
    """Removes the app's own temporary render (never touches the source library)."""
    if not file_id:
        return
    try:
        drive.files().delete(fileId=file_id).execute()
    except Exception as exc:
        log(f"Could not delete render {file_id}: {exc}")
