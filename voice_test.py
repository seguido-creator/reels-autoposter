"""Free voice test: renders the same narration with Kokoro-82M (Apache 2.0, runs on CPU) in several voices
and uploads the samples to the Drive Renders folder for review. Nothing is published."""
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


def main():
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
