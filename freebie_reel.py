"""Launch Reel for a free download (lead magnet), e.g. the Pera Decoded "IPON" budget template.

The script is written by hand (no AI text), shows real screenshots of the freebie, and tells people to
message a keyword to the Page; the Page's keyword auto-reply (Business Suite > Inbox > Automations) sends
the link. Turn that auto-reply ON before posting.

  python freebie_reel.py --name ipon --mode preview   # render + save to Drive (Renders folder), no post
  python freebie_reel.py --name ipon --mode post      # render + publish on the Page + log + keep a copy
"""
import argparse
import json
from pathlib import Path

from common import load_config, log, utcnow

FREEBIES = {
    "ipon": {
        "page": "FIN",
        # the exact Google Sheet people receive (shared "anyone with the link"); screenshots are made from it
        "sheet_xlsx": "https://docs.google.com/spreadsheets/d/10AJbmQSUSvQiC4zQ5pG1ePnq1DShi2M43lzNJf77W6Q/export?format=xlsx",
        "hook": "Libreng OFW Budget Template",
        "outro": "I-message ang 'IPON' sa Pera Decoded",
        "scenes": [
            {"vo": "Kabayan, bagong sweldo na naman, pero bakit parang kulang pa rin bago matapos ang buwan?",
             "key": "kulang", "search": "empty wallet money",
             "alt": ["counting money", "wallet", "peso bills"]},
            {"vo": "Kaya gumawa kami ng libreng OFW Monthly Budget template sa Google Sheets.",
             "key": "libreng", "image": "full"},
            {"vo": "Ilagay mo lang ang kita mo, ang plano mong gastos, at kung magkano talaga ang nagastos mo.",
             "key": "kita", "image": "table"},
            {"vo": "Kusa nitong kino-compute kung magkano ang natitira, ang ipon rate mo, at kung saan ka lumampas.",
             "key": "natitira", "image": "summary"},
            {"vo": "Para makuha, i-message lang ang salitang IPON sa Pera Decoded. Libre ito, at hinding-hindi "
                   "namin hihingin ang password o OTP mo.",
             "key": "IPON", "search": "typing message smartphone",
             "alt": ["texting on phone", "smartphone hands", "phone"]},
        ],
        "caption": ("Libreng OFW Monthly Budget template para sa'yo, kabayan!\n"
                    "I-message lang ang IPON sa Pera Decoded at ipapadala namin ang link (Google Sheets).\n"
                    "Libre ito. Hindi kami kailanman hihingi ng pera, password o OTP.\n"
                    "Ikaw, magkano ang target mong ipon ngayong buwan?"),
        "hashtags": ["#OFW", "#Ipon", "#Budget", "#PeraDecoded"],
        "title": "Libreng OFW Monthly Budget template (message IPON)",
    },
}


def make_shots(xlsx_url, outdir):
    """Screenshots of the real freebie: the Sheet is exported, printed to an image with LibreOffice, and cut
    at its dark section bars. Returns {"full": path, "table": path, "summary": path}."""
    import subprocess
    import requests
    from PIL import Image, ImageOps
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    r = requests.get(xlsx_url, timeout=60)
    r.raise_for_status()
    (outdir / "f.xlsx").write_bytes(r.content)
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(outdir / "f.xlsx")],
                   check=True, capture_output=True, timeout=180)
    subprocess.run(["pdftoppm", "-r", "220", "-png", "-f", "1", "-l", "1", str(outdir / "f.pdf"), str(outdir / "p")],
                   check=True, timeout=120)
    im = Image.open(next(outdir.glob("p*.png"))).convert("RGB")
    w, h = im.size
    px = im.load()

    def dark(y):
        hits = sum(1 for x in range(0, w, 8) if sum(px[x, y]) < 200)
        return hits > (w // 8) * 0.45

    bars, y = [], 0
    while y < h:
        if dark(y):
            y0 = y
            while y < h and dark(y):
                y += 1
            if y - y0 > 15:
                bars.append((y0, y))
        y += 1
    if len(bars) < 4:
        raise RuntimeError(f"could not find the sheet sections ({len(bars)} bars)")
    title, sec1, sec2, sec3 = bars[:4]

    def last_ink(start):
        """End of the content block that starts at y=start (stops at the first tall white gap)."""
        gap, last = 0, start
        for yy in range(start, h):
            ink = any(sum(px[x, yy]) < 600 for x in range(0, w, 6))
            gap = 0 if ink else gap + 1
            last = yy if ink else last
            if gap > 60:
                break
        return last

    cols = [x for x in range(w) if any(sum(px[x, yy]) < 600 for yy in range(sec2[1] + 4, sec3[0] - 4, 3))]
    x0, x1 = max(min(cols) - 10, 0), min(max(cols) + 10, w)
    end = last_ink(sec3[1])
    out = {}
    for key, (a, b) in {"full": (title[0], end), "table": (sec2[0], sec3[0] - 10),
                        "summary": (sec3[0], end)}.items():
        c = ImageOps.expand(im.crop((x0, max(a - 10, 0), x1, min(b + 10, h))), border=40, fill="white")
        c.thumbnail((1600, 1600))
        path = outdir / f"{key}.jpg"
        c.save(path, quality=92)
        out[key] = str(path)
    return out


def build(name, out_mp4):
    import explainer
    cfg = load_config()
    f = FREEBIES[name]
    page = next(p for p in cfg["pages"] + cfg.get("image_pages", []) if p["key"] == f["page"])
    script = {"hook": f["hook"], "scenes": [dict(s) for s in f["scenes"]], "total": 0, "_outro": f["outro"]}
    shots = make_shots(f["sheet_xlsx"], Path("/tmp") / f"freebie_{name}_shots")
    clips = []
    for sc in script["scenes"]:
        if sc.get("image"):
            clips.append({"id": f"st{len(clips)}", "image_url": "still", "image_path": shots[sc["image"]],
                          "tags": "freebie"})
        else:
            hit = None
            for q in [sc["search"]] + sc.get("alt", []):
                try:
                    hit = explainer.find_clips(page, [dict(sc, search=q)], set())[0]
                    break
                except RuntimeError:
                    continue
            clips.append(hit or {"id": f"st{len(clips)}", "image_url": "still", "image_path": shots["full"],
                                 "tags": "freebie"})
    secs = explainer.render(page, script, clips, out_mp4)
    message = f["caption"] + "\n\n" + " ".join(f["hashtags"])
    log(f"[{page['key']}] freebie reel '{name}' {secs:.1f}s")
    return cfg, page, message, f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="ipon")
    ap.add_argument("--mode", choices=["preview", "post"], default="preview")
    args = ap.parse_args()
    out = Path(f"/tmp/freebie_{args.name}.mp4")
    cfg, page, message, f = build(args.name, out)
    from common import drive_service, google_creds, render_folder_id, upload_render
    drive = drive_service(google_creds())
    if args.mode == "preview":
        _, link = upload_render(drive, out, f"preview_freebie_{args.name}_{utcnow():%Y%m%d_%H%M}.mp4",
                                render_folder_id(drive))
        Path(f"/tmp/freebie_{args.name}.txt").write_text(message, encoding="utf-8")
        _, tlink = upload_render(drive, Path(f"/tmp/freebie_{args.name}.txt"),
                                 f"preview_freebie_{args.name}_{utcnow():%Y%m%d_%H%M}_caption.txt",
                                 render_folder_id(drive), mime="text/plain")
        log(f"[{page['key']}] freebie preview: {link} | caption: {tlink}")
        print(message)
        return
    import os
    from autopost import publish_reel
    import images
    page_id = os.environ.get(page["page_id_env"], "").strip()
    token = os.environ.get(page["token_env"], "").strip()
    vid, state = publish_reel(page_id, token, out, message, cfg["graph_api_version"])
    card = {"headline": f["title"], "topic": f"freebie {args.name}", "type": "freebie", "caption": message,
            "hashtags": f["hashtags"]}
    note = f"freebie {args.name}; reel {state}" + images.save_published(page, out, card, message, vid, "freebie")
    from common import open_sheet
    ws = images.log_sheet(open_sheet(google_creds()))
    ws.append_row([page["key"], f"freebie {args.name} {utcnow():%Y-%m-%d %H:%M}", utcnow().isoformat(timespec="seconds"),
                   "freebie", f"freebie {args.name}", f["title"], vid, note], value_input_option="RAW")
    log(f"[{page['key']}] freebie reel posted {vid} ({state})")


if __name__ == "__main__":
    main()
