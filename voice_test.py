"""Free voice test: renders the same narration with Kokoro-82M (Apache 2.0, runs on CPU) in several voices
and uploads the samples to the Drive Renders folder for review. Nothing is published."""
import os
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro import KPipeline

from common import drive_service, google_creds, log, render_folder_id, upload_render, utcnow

TEXT = ("When the Great Pyramid was finished, around 2560 BC, woolly mammoths were still alive. "
        "Not in Egypt, but on a remote Arctic island, where the last of them would survive for centuries more. "
        "And by the time Cleopatra was born, the pyramid was already more than two thousand years old.")
VOICES = [("a", "am_michael"), ("a", "am_fenrir"), ("a", "am_onyx"), ("a", "af_heart"), ("b", "bm_george"), ("b", "bm_fable")]


def narrate(lines, voice, speed):
    """Renders each narration line separately (line_01.wav, line_02.wav, ...) and saves them to Drive."""
    out = Path("narration")
    out.mkdir(exist_ok=True)
    drive = drive_service(google_creds())
    folder = render_folder_id(drive)
    stamp = f"{utcnow():%Y%m%d_%H%M}"
    pipe = KPipeline(lang_code=voice[0])
    for i, text in enumerate(lines, 1):
        audio = np.concatenate([np.asarray(a) for _, _, a in pipe(text, voice=voice, speed=speed)])
        wav = out / f"line_{i:02d}.wav"
        sf.write(wav, audio, 24000)
        mp3 = wav.with_suffix(".mp3")  # small copy for quick review on a phone
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-b:a", "64k", str(mp3)], check=True)
        _, link = upload_render(drive, wav, f"narration_{stamp}_{voice}_line_{i:02d}.wav", folder, mime="audio/wav")
        upload_render(drive, mp3, f"narration_{stamp}_{voice}_line_{i:02d}.mp3", folder, mime="audio/mpeg")
        log(f"narration line {i}: {len(audio) / 24000:.2f}s {link}")


def gemini_samples(text, voices, style):
    """Same text in several Gemini TTS voices (e.g. VOICE=gemini:Laomedeia,Gacrux) -> MP3s in the Drive Renders folder."""
    import transform
    drive = drive_service(google_creds())
    folder = render_folder_id(drive)
    stamp = f"{utcnow():%Y%m%d_%H%M}"
    out = Path("voice_samples")
    out.mkdir(exist_ok=True)
    for v in voices:
        wav = out / f"{v}.wav"
        secs = transform.speak(text, {"voice": v, "voice_style": style or "natural and expressive"}, wav)
        mp3 = wav.with_suffix(".mp3")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-b:a", "128k", str(mp3)], check=True)
        _, link = upload_render(drive, mp3, f"voice_test_gemini_{v}_{stamp}.mp3", folder, mime="audio/mpeg")
        log(f"voice test {v}: {secs:.1f}s {link}")


def main():
    lines = [x.strip() for x in os.environ.get("LINES", "").split("|") if x.strip()]
    voice = os.environ.get("VOICE") or ""
    if voice.startswith("gemini:"):
        return gemini_samples(" ".join(lines) or TEXT, [v.strip() for v in voice[7:].split(",") if v.strip()],
                              os.environ.get("STYLE", ""))
    if lines:
        return narrate(lines, os.environ.get("VOICE") or "am_michael", float(os.environ.get("SPEED") or 1.0))
    out = Path("voice_samples")
    out.mkdir(exist_ok=True)
    drive = drive_service(google_creds())
    folder = render_folder_id(drive)
    stamp = f"{utcnow():%Y%m%d_%H%M}"
    links = []
    pipes = {}
    for lang, voice in VOICES:
        pipe = pipes.setdefault(lang, KPipeline(lang_code=lang))
        audio = np.concatenate([np.asarray(a) for _, _, a in pipe(TEXT, voice=voice, speed=0.95)])
        wav = out / f"{voice}.wav"
        sf.write(wav, audio, 24000)
        mp3 = wav.with_suffix(".mp3")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-b:a", "160k", str(mp3)], check=True)
        _, link = upload_render(drive, mp3, f"voice_test_kokoro_{voice}_{stamp}.mp3", folder, mime="audio/mpeg")
        links.append(f"{voice}: {link}")
        log(f"voice test {voice}: {len(audio) / 24000:.1f}s {link}")
    print("\n".join(links))


if __name__ == "__main__":
    main()
