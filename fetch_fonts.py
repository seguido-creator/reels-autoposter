"""Downloads the open-licence (SIL OFL) fonts used on the image cards into ./fonts.

Fonts come from the Fontsource npm packages (as WOFF2) and are converted to TTF for Pillow.
Runs at the start of the "Image posts" workflow; skips fonts that are already there.
"""
import io
import tarfile
import urllib.request
from pathlib import Path

from fontTools.ttLib import TTFont

DEST = Path(__file__).resolve().parent / "fonts"
# output file -> (fontsource package, weight)
FONTS = {
    "Anton.ttf": ("anton", 400),
    "BebasNeue.ttf": ("bebas-neue", 400),
    "Oswald.ttf": ("oswald", 400),
    "Oswald-Medium.ttf": ("oswald", 500),
    "Playfair.ttf": ("playfair-display", 400),
    "Playfair-Bold.ttf": ("playfair-display", 700),
    "Baloo-SemiBold.ttf": ("baloo-2", 600),
    "Baloo-ExtraBold.ttf": ("baloo-2", 800),
    "Poppins-Regular.ttf": ("poppins", 400),
    "Poppins-Medium.ttf": ("poppins", 500),
    "Poppins-Bold.ttf": ("poppins", 700),
}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "reels-autoposter"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def woff2(pkg, weight):
    name = f"{pkg}-latin-{weight}-normal.woff2"
    try:
        return get(f"https://cdn.jsdelivr.net/npm/@fontsource/{pkg}@5/files/{name}")
    except Exception:
        meta = get(f"https://registry.npmjs.org/@fontsource/{pkg}/latest")
        import json
        tgz = get(json.loads(meta)["dist"]["tarball"])
        with tarfile.open(fileobj=io.BytesIO(tgz)) as tf:
            return tf.extractfile(f"package/files/{name}").read()


def main():
    DEST.mkdir(exist_ok=True)
    for out, (pkg, weight) in FONTS.items():
        path = DEST / out
        if path.exists():
            continue
        font = TTFont(io.BytesIO(woff2(pkg, weight)))
        font.flavor = None
        font.save(str(path))
        print(f"font ready: {out}")


if __name__ == "__main__":
    main()
