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


def heard(wav):
    """What a small Whisper model hears in the take (Tagalog), to catch words said wrong."""
    try:
        from faster_whisper import WhisperModel
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                             capture_output=True, check=True, timeout=120).stdout
        segs, _ = WhisperModel(os.environ.get("ALIGN_MODEL", "small"), device="cpu", compute_type="int8").transcribe(
            np.frombuffer(raw, dtype=np.float32), language="tl", beam_size=5)
        return " ".join(s.text.strip() for s in segs)
    except Exception as exc:
        return f"(no transcript: {str(exc)[:80]})"


def gemini_samples(takes, voices, style):
    """Each take (takes are separated by || in LINES) in each Gemini TTS voice (VOICE=gemini:Laomedeia,Gacrux)
    -> one MP3 per take in the Drive Renders folder, with what Whisper heard in the log."""
    import transform
    drive = drive_service(google_creds())
    folder = render_folder_id(drive)
    stamp = f"{utcnow():%Y%m%d_%H%M}"
    out = Path("voice_samples")
    out.mkdir(exist_ok=True)
    for v in voices:
        for n, text in enumerate(takes, 1):
            tag = f"{v}_take{n}" if len(takes) > 1 else v
            wav = out / f"{tag}.wav"
            secs = transform.speak(text, {"voice": v, "voice_style": style or "natural and expressive"}, wav)
            mp3 = wav.with_suffix(".mp3")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-b:a", "128k", str(mp3)], check=True)
            _, link = upload_render(drive, mp3, f"voice_test_gemini_{tag}_{stamp}.mp3", folder, mime="audio/mpeg")
            log(f"voice test {tag}: {secs:.1f}s {link}")
            log(f"  text:  {text}")
            log(f"  heard: {heard(wav)}")


def main():
    lines = [x.strip() for x in os.environ.get("LINES", "").split("|") if x.strip()]
    voice = os.environ.get("VOICE") or ""
    if voice.startswith("gemini:"):
        takes = [" ".join(x.strip() for x in t.split("|") if x.strip()) for t in os.environ.get("LINES", "").split("||")]
        return gemini_samples([t for t in takes if t] or [TEXT], [v.strip() for v in voice[7:].split(",") if v.strip()],
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
