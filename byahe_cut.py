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
REEL3, LF3 = "046_KZ-K03-R1_v3.mp4", "051_KZ-Nanay-LongForm_v2_v3.mp4"
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

def words(p, model):
    cmd = ["ffmpeg", "-v", "error", "-i", str(p), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
    audio = np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.int16).astype(np.float32) / 32768
    seg, _ = model.transcribe(audio, language="tl", word_timestamps=True)
    return [w for s in seg for w in s.words]

def cut_span(src, dst, a, b, preset):
    """Remove [a, b] with a 0.12 s blend (a short jump cut inside the same shot)."""
    d = dur(src); f = 0.12
    fc = (f"[0:v]trim=0:{a},setpts=PTS-STARTPTS[v0];[0:v]trim={b}:{d},setpts=PTS-STARTPTS[v1];"
          f"[v0][v1]xfade=transition=fade:duration={f}:offset={a-f}[v];"
          f"[0:a]atrim=0:{a},asetpts=PTS-STARTPTS[a0];[0:a]atrim={b}:{d},asetpts=PTS-STARTPTS[a1];"
          f"[a0][a1]acrossfade=d={f}[a]")
    sh("ffmpeg","-v","error","-y","-i",str(src),"-filter_complex",fc,"-map","[v]","-map","[a]","-c:v","libx264","-crf","19",
       "-preset",preset,"-r","30","-c:a","aac","-b:a","192k","-ar","48000","-movflags","+faststart",str(dst))
    log(f"[CUT] {dst.name}: {d:.1f}s -> {dur(dst):.1f}s (removed {a:.2f}-{b:.2f})")

def mestiza():
    """Remove the line 'Kasi mestiza naman na eh' after 'Sanay na' (owner approved 2026-11-14), then point the queue at v3."""
    from faster_whisper import WhisperModel
    m = WhisperModel("small", compute_type="int8")
    drive = drive_service(google_creds()); fid, files = folder_files(drive, FOLDER)
    tmp = Path(tempfile.mkdtemp())
    for src_name, dst_name, preset in ((REEL2, REEL3, "medium"), (LF2, LF3, "veryfast")):
        src = tmp / src_name; download(drive, files[src_name]["id"], src)
        ws = words(src, m)
        hits = [i for i, w in enumerate(ws) if any(k in w.word.lower() for k in ("mest", "mist", "tisa", "tiza"))]
        hits = [i for i in hits if any("sanay" in ws[j].word.lower() for j in range(max(0, i - 6), i))]
        print(src_name, "hits:", [(round(ws[i].start, 1), ws[i].word) for i in hits])
        if len(hits) != 1: sys.exit(f"[CUT] expected one 'mestiza' after 'sanay' in {src_name}, found {len(hits)}")
        i = hits[0]
        k = next((k for k in range(i - 3, i) if k >= 0 and "kasi" in ws[k].word.lower()), i)
        end_i = i
        while end_i + 1 < len(ws) and ws[end_i + 1].start - ws[end_i].end < 0.6 and end_i - i < 4:
            end_i += 1
        a, b = ws[k].start - 0.08, ws[end_i].end + 0.12
        print(f"  cutting {a:.2f}-{b:.2f}:", " ".join(w.word.strip() for w in ws[k:end_i + 1]))
        if b - a > 4: sys.exit("[CUT] span too long, stopping")
        dst = OUT / dst_name; cut_span(src, dst, a, b, preset)
        after = words(dst, m)
        left = [w.word for w in after if any(kk in w.word.lower() for kk in ("mest", "mist", "tisa", "tiza"))]
        print("  after cut, remaining:", left)
        if left: sys.exit("[CUT] the word is still there, nothing uploaded")
        if dst_name not in files:
            iid, _ = upload_render(drive, dst, dst_name, fid); log(f"[CUT] uploaded {dst_name} -> {iid}")

def queue(reel_new=REEL2, lf_new=LF2):
    from googleapiclient.http import MediaFileUpload
    drive = drive_service(google_creds()); fid, files = folder_files(drive, FOLDER)
    if reel_new not in files or lf_new not in files: sys.exit("[CUT] new videos not in Drive")
    tmp = Path(tempfile.mkdtemp()) / "queue.json"; download(drive, files["queue.json"]["id"], tmp)
    q = json.loads(tmp.read_text(encoding="utf-8"))
    for x in q:
        if x["file"] in (REEL, REEL2, REEL3): x.update(file=reel_new, thumb="046_KZ-K03-R1_THUMB.jpg")
        if x["file"] in (LF, LF2, LF3):
            x.update(file=lf_new, thumb="051_KZ-Nanay-LongForm_v2_THUMB.jpg")
            x["caption"] = x["caption"].replace(" 91 na ako, pero kaya pa!", "")
    assert not any("91 na ako" in x["caption"] for x in q)
    tmp.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
    f = drive.files().create(body={"name": "queue.json", "parents": [fid]},
                             media_body=MediaFileUpload(str(tmp), mimetype="application/json"), fields="id").execute()
    log(f"[CUT] new queue.json {f['id']} ({len(q)} items)")

# ---- fact-check patches (2026-11-17): replace the frames of a few on-screen captions in the long-forms ----
LF_PATCHES = {
    "008_OM-Muscat-LongForm_v3_v2.mp4": ["patch_OM2_06_M06_s16.mp4"],
    "019_GE-Nanay-LongForm_v3.mp4": ["patch_GE2_05_G05_s5.mp4"],
    "027_AM-Nanay-LongForm_v3_v2.mp4": ["patch_AM2_02_A02_s9.mp4", "patch_AM2_06_A06_s5.mp4", "patch_AM2_06_A06_s8.mp4"],
    "043_OM-Salalah-LongForm_v3.mp4": ["patch_SL2_04_S04_s8.mp4"],
    "051_KZ-Nanay-LongForm_v2_v3.mp4": ["patch_KZ_04_K04_s14.mp4", "patch_KZ_06_K06_s3.mp4", "patch_KZ_06_K06_s11.mp4"],
}
W_, H_ = 54, 96
def gray_frames(p, w=W_, h=H_):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-vf", f"fps=30,scale={w}:{h},format=gray", "-f", "rawvideo", "-"], capture_output=True)
    f = np.frombuffer(r.stdout, np.uint8); n = len(f) // (w * h)
    return f[:n * w * h].reshape(n, h, w).astype(np.float32)

def match(lf_frames, pf):
    """Best start frame of patch pf inside lf_frames; the caption band (rows 55-86 of 96) is masked out."""
    mask = np.ones((H_, W_), bool); mask[55:87] = False
    L = lf_frames[:, mask]; P = pf[:, mask]; n, m = len(L), len(P)
    acc = np.zeros(n - m + 1, np.float32); js = list(range(0, m, 5))
    for j in js:
        acc += np.abs(L[j:j + n - m + 1] - P[j]).mean(axis=1)
    acc /= len(js)
    i = int(np.argmin(acc)); best = float(acc[i])
    far = np.delete(acc, range(max(0, i - 60), min(len(acc), i + 60)))
    return i, best, float(far.min()) if len(far) else 1e9

def patch_lf():
    drive = drive_service(google_creds()); fid, files = folder_files(drive, FOLDER)
    tmp = Path(tempfile.mkdtemp()); done = {}
    for lf_name, patches in LF_PATCHES.items():
        out_name = lf_name[:-4] + "_fx.mp4"
        if out_name in files: log(f"[FIX] {out_name} already in Drive"); done[lf_name] = out_name; continue
        if lf_name not in files: log(f"[FIX] {lf_name} not in Drive, skipped"); continue
        lf = tmp / lf_name; download(drive, files[lf_name]["id"], lf)
        L = gray_frames(lf); log(f"[FIX] {lf_name}: {len(L)} frames")
        ins, flt, prev = ["-i", str(lf)], [], "[0:v]"
        for k, pn in enumerate(patches, 1):
            pp = tmp / pn; download(drive, files[pn]["id"], pp)
            P = gray_frames(pp); i, best, second = match(L, P)
            t0 = i / 30.0; d = len(P) / 30.0
            log(f"[FIX]   {pn}: at {t0:.2f}s, err {best:.2f} (next {second:.2f})")
            if best > 6 or second < best * 2.5:
                sys.exit(f"[FIX] no clear match for {pn} in {lf_name}; nothing uploaded")
            ins += ["-i", str(pp)]
            flt.append(f"[{k}:v]setpts=PTS-STARTPTS+{t0:.4f}/TB[p{k}];{prev}[p{k}]overlay=0:0:enable='between(t,{t0:.4f},{t0 + d - 0.02:.4f})':eof_action=pass[v{k}]")
            prev = f"[v{k}]"
        out = OUT / out_name
        sh("ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(flt), "-map", prev, "-map", "0:a", "-c:v", "libx264", "-crf", "19",
           "-preset", "veryfast", "-r", "30", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(out))
        log(f"[FIX] {out_name}: {dur(lf):.1f}s -> {dur(out):.1f}s")
        if abs(dur(out) - dur(lf)) > 0.3: sys.exit("[FIX] duration changed, nothing uploaded")
        for k, pn in enumerate(patches, 1):
            P = gray_frames(tmp / pn); O2 = gray_frames(out)
            i, best, _ = match(O2, P)
            full = float(np.abs(O2[i:i + len(P)] - P[:len(O2) - i]).mean())
            log(f"[FIX]   check {pn}: frames now match with full-frame error {full:.2f}")
            if full > 6: sys.exit(f"[FIX] patched frames do not match {pn}; nothing uploaded")
            sh("ffmpeg", "-v", "error", "-y", "-ss", f"{i / 30 + len(P) / 60:.2f}", "-i", str(out), "-frames:v", "1", "-vf", "scale=360:-2", str(OUT / f"check_{out_name[:3]}_{k}.jpg"))
        iid, _ = upload_render(drive, out, out_name, fid); log(f"[FIX] uploaded {out_name} -> {iid}"); done[lf_name] = out_name
        out.unlink(); lf.unlink()
    from googleapiclient.http import MediaFileUpload
    fid, files = folder_files(drive, FOLDER)
    qp = tmp / "queue.json"; download(drive, files["queue.json"]["id"], qp)
    q = json.loads(qp.read_text(encoding="utf-8")); n = 0
    for x in q:
        if x["file"] in done:
            x.setdefault("thumb", x["file"][:-4] + "_THUMB.jpg"); x["file"] = done[x["file"]]; n += 1
    if not n: log("[FIX] queue already up to date"); return
    qp.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
    f = drive.files().create(body={"name": "queue.json", "parents": [fid]},
                             media_body=MediaFileUpload(str(qp), mimetype="application/json"), fields="id").execute()
    log(f"[FIX] new queue.json {f['id']} ({n} long-forms switched)")

# ---- 2026-11-25: the 3D map flights in the long-forms were silent; lay music under every silent span ----
MAP_LF = ["019_GE-Nanay-LongForm_v3_fx.mp4", "027_AM-Nanay-LongForm_v3_v2_fx.mp4",
          "036_IL-Nanay-LongForm_v2.mp4", "051_KZ-Nanay-LongForm_v2_v3_fx.mp4"]
MAP_MUSIC = "map_music.mp3"

def silent_spans(p, limit=240.0):
    r = subprocess.run(["ffmpeg", "-nostdin", "-vn", "-t", str(limit), "-i", str(p), "-af", "silencedetect=n=-55dB:d=2", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    st = [float(x.split(":")[1]) for x in r.split("\n") if "silence_start:" in x for x in [x.split("silence_start")[1]]]
    en = [float(x.split("silence_end:")[1].split("|")[0]) for x in r.split("\n") if "silence_end:" in x]
    return [(a, b) for a, b in zip(st, en) if b - a >= 2.0]

def map_sound(only=None):
    drive = drive_service(google_creds()); fid, files = folder_files(drive, FOLDER)
    tmp = Path(tempfile.mkdtemp()); done = {}
    mus = tmp / MAP_MUSIC; download(drive, files[MAP_MUSIC]["id"], mus)
    for name in MAP_LF:
        if only and not name.startswith(only): continue
        out_name = name[:-4] + "_snd.mp4"
        if out_name in files: log(f"[MAP] {out_name} already in Drive"); done[name] = out_name; continue
        if name not in files: log(f"[MAP] {name} not in Drive, skipped"); continue
        lf = tmp / name; download(drive, files[name]["id"], lf)
        spans = silent_spans(lf); log(f"[MAP] {name}: silent spans {[(round(a,1), round(b,1)) for a, b in spans]}")
        if not spans: log(f"[MAP] {name}: nothing silent, skipped"); lf.unlink(); continue
        flt, labels = [], []
        for k, (a, b) in enumerate(spans):
            d = b - a
            flt.append(f"[1:a]atrim=0:{d:.3f},asetpts=PTS-STARTPTS,volume=0.55,afade=t=in:d=1.0,afade=t=out:st={max(0, d - 1.2):.3f}:d=1.2,"
                       f"aresample=48000,aformat=channel_layouts=stereo,adelay={int(a * 1000)}|{int(a * 1000)}[m{k}]")
            labels.append(f"[m{k}]")
        flt.append(f"[0:a]aresample=48000,aformat=channel_layouts=stereo{''.join(labels)}amix=inputs={len(spans) + 1}:duration=first:normalize=0[a]")
        out = OUT / out_name
        sh("ffmpeg", "-v", "error", "-y", "-i", str(lf), "-stream_loop", "-1", "-i", str(mus), "-filter_complex", ";".join(flt),
           "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out))
        if abs(dur(out) - dur(lf)) > 0.3: sys.exit(f"[MAP] {name}: duration changed, nothing uploaded")
        left = silent_spans(out); log(f"[MAP] {out_name}: silent spans now {left}")
        if left: sys.exit(f"[MAP] {name}: still silent somewhere, nothing uploaded")
        a, b = spans[0]
        sh("ffmpeg", "-v", "error", "-y", "-ss", f"{max(0, a - 2):.2f}", "-t", f"{min(b - a + 4, 20):.2f}", "-i", str(out),
           "-vf", "scale=360:-2", "-c:v", "libx264", "-crf", "30", "-c:a", "aac", str(OUT / f"preview_map_{name[:3]}.mp4"))
        iid, _ = upload_render(drive, out, out_name, fid); log(f"[MAP] uploaded {out_name} -> {iid}"); done[name] = out_name
        out.unlink(); lf.unlink()
    if not done: return
    from googleapiclient.http import MediaFileUpload
    fid, files = folder_files(drive, FOLDER)
    qp = tmp / "queue.json"; download(drive, files["queue.json"]["id"], qp)
    q = json.loads(qp.read_text(encoding="utf-8")); n = 0
    for x in q:
        if x["file"] in done:
            x.setdefault("thumb", x["file"].split("_fx")[0].split(".mp4")[0] + "_THUMB.jpg"); x["file"] = done[x["file"]]; n += 1
    if not n: log("[MAP] queue already up to date"); return
    qp.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
    f = drive.files().create(body={"name": "queue.json", "parents": [fid]},
                             media_body=MediaFileUpload(str(qp), mimetype="application/json"), fields="id").execute()
    log(f"[MAP] new queue.json {f['id']} ({n} long-forms switched)")

def cut_phrase(src_name, dst_name, must, near=None, label="CUT"):
    """Cut one spoken sentence (faster-whisper segment containing `must`) out of a Drive video; returns dst path or exits."""
    from faster_whisper import WhisperModel
    m = WhisperModel("small", compute_type="int8")
    drive = drive_service(google_creds()); fid, files = folder_files(drive, FOLDER)
    if dst_name in files: log(f"[{label}] {dst_name} already in Drive"); return None
    tmp = Path(tempfile.mkdtemp()); src = tmp / src_name; download(drive, files[src_name]["id"], src)
    cmd = ["ffmpeg", "-v", "error", "-i", str(src), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
    audio = np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.int16).astype(np.float32) / 32768
    segs = list(m.transcribe(audio, language="tl", word_timestamps=True)[0])
    hits = [s for s in segs if any(k in s.text.lower() for k in must)]
    for s in hits: print(f"  hit {s.start:.2f}-{s.end:.2f}: {s.text}")
    if len(hits) != 1: sys.exit(f"[{label}] expected one sentence with {must} in {src_name}, found {len(hits)}")
    h = hits[0]; a, b = h.start - 0.1, h.end + 0.15
    if b - a > 9: sys.exit(f"[{label}] span too long ({b-a:.1f}s), stopping")
    dst = OUT / dst_name; cut_span(src, dst, a, b, "veryfast")
    after = m.transcribe(np.frombuffer(subprocess.run(["ffmpeg","-v","error","-ss",str(max(0,a-20)),"-t","40","-i",str(dst),"-ac","1","-ar","16000","-f","s16le","-"],capture_output=True).stdout,np.int16).astype(np.float32)/32768, language="tl")[0]
    left = [s.text for s in after if any(k in s.text.lower() for k in must)]
    print("  after:", [s for s in left])
    if left: sys.exit(f"[{label}] phrase still there, nothing uploaded")
    iid, _ = upload_render(drive, dst, dst_name, fid); log(f"[{label}] uploaded {dst_name} -> {iid}")
    return dst

def requeue(old, new, thumb):
    from googleapiclient.http import MediaFileUpload
    drive = drive_service(google_creds()); fid, files = folder_files(drive, FOLDER)
    if new not in files: sys.exit(f"[CUT] {new} not in Drive")
    tmp = Path(tempfile.mkdtemp()) / "queue.json"; download(drive, files["queue.json"]["id"], tmp)
    q = json.loads(tmp.read_text(encoding="utf-8")); n = 0
    for x in q:
        if x["file"] == old: x["file"] = new; x.setdefault("thumb", thumb); n += 1
    if not n: log(f"[CUT] {old} not in queue (already switched?)"); return
    tmp.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
    f = drive.files().create(body={"name": "queue.json", "parents": [fid]}, media_body=MediaFileUpload(str(tmp), mimetype="application/json"), fields="id").execute()
    log(f"[CUT] new queue.json {f['id']} ({old} -> {new})")

def frames(name, a, b, step=1.0):
    """Upload a contact sheet of name between a and b seconds (for checking on-screen text)."""
    drive = drive_service(google_creds()); fid, files = folder_files(drive, FOLDER)
    tmp = Path(tempfile.mkdtemp()); src = tmp / name; download(drive, files[name]["id"], src)
    n = int((b - a) / step)
    sh("ffmpeg", "-v", "error", "-y", "-ss", str(a), "-t", str(b - a), "-i", str(src), "-vf", f"fps={1/step},scale=180:-2,drawtext=text='%{{pts\\:hms}}':x=4:y=4:fontsize=18:fontcolor=yellow,tile=10x{(n+9)//10}", "-frames:v", "1", str(OUT / "sheet.jpg"))
    out = f"frames_{name[:-4]}_{int(a)}.jpg"
    iid, _ = upload_render(drive, OUT / "sheet.jpg", out, fid, mime="image/jpeg"); log(f"[CUT] {out} -> {iid}")

def cutspan_step(src_name, dst_name, a, b, thumb):
    drive = drive_service(google_creds()); fid, files = folder_files(drive, FOLDER)
    tmp = Path(tempfile.mkdtemp()); src = tmp / src_name; download(drive, files[src_name]["id"], src)
    if b - a > 12: sys.exit("[CUT] span too long")
    dst = OUT / dst_name; cut(src, dst, a, b, "veryfast")
    iid, _ = upload_render(drive, dst, dst_name, fid); log(f"[CUT] uploaded {dst_name} -> {iid}")
    requeue(src_name, dst_name, thumb)

if __name__ == "__main__":
    if sys.argv[1] == "cutspan":
        cutspan_step(sys.argv[2], sys.argv[3], float(sys.argv[4]), float(sys.argv[5]), sys.argv[6])
    elif sys.argv[1] == "frames":
        frames(sys.argv[2], float(sys.argv[3]), float(sys.argv[4]))
    elif sys.argv[1] == "salalah-georgia":
        cut_phrase("043_OM-Salalah-LongForm_v3_fx.mp4", "043_OM-Salalah-LongForm_v3_fx2.mp4", ("georgia", "georgie", "jorja"), label="CUT")
        requeue("043_OM-Salalah-LongForm_v3_fx.mp4", "043_OM-Salalah-LongForm_v3_fx2.mp4", "043_OM-Salalah-LongForm_v3_THUMB.jpg")
    elif sys.argv[1] == "mapsound":
        map_sound(sys.argv[2] if len(sys.argv) > 2 else None)
    elif sys.argv[1] == "patch":
        patch_lf()
    elif sys.argv[1] == "mestiza":
        mestiza(); queue(REEL3, LF3)
    else:
        {"make": make, "queue": queue}[sys.argv[1]]()
