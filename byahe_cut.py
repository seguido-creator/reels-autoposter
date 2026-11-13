"""One-off edit for Byahe ni Nanay: remove the Kok Tobe "Mashallah ... 91 ... 91 years old" scene.

  python byahe_cut.py make    # download 046 + 051, cut the scene, upload *_v2 copies to Drive, write previews
  python byahe_cut.py queue   # (after owner approval) write a new queue.json pointing at the *_v2 files
"""
import json, subprocess, sys, tempfile
from pathlib import Path
import numpy as np
from common import download, drive_service, google_creds, log, upload_render
from byahe import folder_files

FOLDER = "Byahe ni Nanay - Queue"
REEL, LF = "046_KZ-K03-R1.mp4", "051_KZ-Nanay-LongForm_v2.mp4"
REEL2, LF2 = "046_KZ-K03-R1_v2.mp4", "051_KZ-Nanay-LongForm_v2_v2.mp4"
A, B = 7.8, 20.6          # the scene inside the Reel (from the K03 spec: 3 voice shots of 4.8 s, 0.8 s cross-fades)
OUT = Path("out"); OUT.mkdir(exist_ok=True)

def sh(*a): subprocess.run(a, check=True)
def dur(p): return float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",str(p)],capture_output=True,text=True).stdout)
def pcm(p, ss=None, t=None, sr=8000):
    cmd=["ffmpeg","-v","error"]+(["-ss",str(ss)] if ss is not None else [])+(["-t",str(t)] if t else [])+["-i",str(p),"-af","highpass=f=300,lowpass=f=3400","-ac","1","-ar",str(sr),"-f","s16le","-"]
    return np.frombuffer(subprocess.run(cmd,capture_output=True).stdout,np.int16).astype(np.float32)

def find_offset(reel, lf):
    q = pcm(reel, A, B - A); x = pcm(lf); sr = 8000
    n = 1 << int(np.ceil(np.log2(len(x) + len(q))))
    c = np.fft.irfft(np.fft.rfft(x, n) * np.conj(np.fft.rfft(q, n)), n)[:len(x)]
    e = np.sqrt(np.convolve(x * x, np.ones(len(q)), "valid")) * np.linalg.norm(q) + 1e-9
    c = c[:len(e)] / e
    i = int(np.argmax(c)); top = sorted(c)[-1]; second = np.max(np.delete(c, range(max(0, i - sr * 5), i + sr * 5)))
    log(f"[CUT] long-form match at {i/sr:.2f}s, score {top:.3f} (next best {second:.3f})")
    return i / sr, float(top), float(second)

def cut(src, dst, a, b, preset):
    d = dur(src); f = 0.25
    fc = (f"[0:v]trim=0:{a},setpts=PTS-STARTPTS[v0];[0:v]trim={b}:{d},setpts=PTS-STARTPTS[v1];"
          f"[v0][v1]xfade=transition=fade:duration={f}:offset={a-f}[v];"
          f"[0:a]atrim=0:{a},asetpts=PTS-STARTPTS[a0];[0:a]atrim={b}:{d},asetpts=PTS-STARTPTS[a1];"
          f"[a0][a1]acrossfade=d={f}[a]")
    sh("ffmpeg","-v","error","-y","-i",str(src),"-filter_complex",fc,"-map","[v]","-map","[a]","-c:v","libx264","-crf","19",
       "-preset",preset,"-r","30","-c:a","aac","-b:a","192k","-ar","48000","-movflags","+faststart",str(dst))
    log(f"[CUT] {dst.name}: {d:.1f}s -> {dur(dst):.1f}s (removed {a:.2f}-{b:.2f})")

KEYS = ("91", "ninety", "mashallah", "masha", "alhamdulillah", "years old")
def transcript(p, ss, t, label, model):
    cmd = ["ffmpeg", "-v", "error"] + (["-ss", str(ss), "-t", str(t)] if ss is not None else []) + ["-i", str(p), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
    audio = np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.int16).astype(np.float32) / 32768
    seg, _ = model.transcribe(audio, language="tl")
    hits = 0
    for s in seg:
        t0 = (ss or 0) + s.start
        hit = any(k in s.text.lower() for k in KEYS); hits += hit
        print(f"  {label} {t0:7.1f}s {s.text.strip()}{' <<<' if hit else ''}")
    return hits

def clip(p, ss, t):
    o = OUT / f"_clip_{p.stem}_{int(ss)}.wav"; sh("ffmpeg","-v","error","-y","-ss",str(ss),"-t",str(t),"-i",str(p),"-ac","1","-ar","16000",str(o)); return o

def make():
    drive = drive_service(google_creds()); fid, files = folder_files(drive, FOLDER)
    tmp = Path(tempfile.mkdtemp()); r, l = tmp / REEL, tmp / LF
    for n, p in ((REEL, r), (LF, l)):
        download(drive, files[n]["id"], p); log(f"[CUT] downloaded {n} ({dur(p):.1f}s)")
    off, top, second = find_offset(r, l)
    if top < 0.5 or top < second * 1.5:
        sys.exit("[CUT] long-form match not clear enough, stopping")
    r2, l2 = OUT / REEL2, OUT / LF2
    cut(r, r2, A, B, "medium"); cut(l, l2, off, off + (B - A), "veryfast")
    from faster_whisper import WhisperModel
    m = WhisperModel("small", compute_type="int8")
    print("== BEFORE (Reel, the scene)"); before = transcript(r, A, B - A, "reel", m)
    print("== AFTER (Reel, whole)"); after = transcript(r2, None, None, "reel_v2", m)
    print("== AFTER (long-form, 60 s around the cut)"); after_lf = transcript(l2, max(0, off - 30), 60, "lf_v2", m)
    if not before or after or after_lf:
        sys.exit(f"[CUT] check failed (scene hits before={before}, after reel={after}, after lf={after_lf}); nothing uploaded")
    sh("ffmpeg","-v","error","-y","-i",str(r2),"-vf","scale=720:-2","-c:v","libx264","-crf","24","-preset","veryfast","-c:a","aac","-b:a","128k",str(OUT / "preview_046_reel.mp4"))
    sh("ffmpeg","-v","error","-y","-ss",str(max(0, off - 20)),"-t","40","-i",str(l2),"-vf","scale=-2:720","-c:v","libx264","-crf","24","-preset","veryfast","-c:a","aac","-b:a","128k",str(OUT / "preview_051_around_cut.mp4"))
    for n, p in ((REEL2, r2), (LF2, l2)):
        if n in files: log(f"[CUT] {n} already in Drive, not uploading again"); continue
        i, _ = upload_render(drive, p, n, fid); log(f"[CUT] uploaded {n} -> {i}")
    json.dump({"lf_cut_start": off}, open(OUT / "cut.json", "w"))

def queue():
    from googleapiclient.http import MediaFileUpload
    drive = drive_service(google_creds()); fid, files = folder_files(drive, FOLDER)
    if REEL2 not in files or LF2 not in files: sys.exit("[CUT] *_v2 videos not in Drive")
    tmp = Path(tempfile.mkdtemp()) / "queue.json"; download(drive, files["queue.json"]["id"], tmp)
    q = json.loads(tmp.read_text(encoding="utf-8"))
    for x in q:
        if x["file"] == REEL: x.update(file=REEL2, thumb="046_KZ-K03-R1_THUMB.jpg")
        if x["file"] == LF:
            x.update(file=LF2, thumb="051_KZ-Nanay-LongForm_v2_THUMB.jpg")
            x["caption"] = x["caption"].replace(" 91 na ako, pero kaya pa!", "")
    assert not any("91 na ako" in x["caption"] for x in q)
    tmp.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
    f = drive.files().create(body={"name": "queue.json", "parents": [fid]},
                             media_body=MediaFileUpload(str(tmp), mimetype="application/json"), fields="id").execute()
    log(f"[CUT] new queue.json {f['id']} ({len(q)} items)")

if __name__ == "__main__":
    {"make": make, "queue": queue}[sys.argv[1]]()
