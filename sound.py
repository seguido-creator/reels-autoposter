"""Free, licence-safe sound design, synthesised on the fly (no downloads, no stock audio):
  - ambient_music(): a soft, slowly moving pad in a random minor key and chord order, so no two Reels share
    the same bed (non-repetitive by construction);
  - sfx(): whoosh (scene changes), paper (cards sliding in) and stamp (the case-file stamp).
All outputs are 48 kHz 16-bit WAV, quiet enough to sit under a voice-over."""
import random
import wave
from pathlib import Path

import numpy as np

SR = 48000
NOTES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
# minor-key progressions (scale degrees as semitone offsets of chord roots, all minor/major triads below)
PROGRESSIONS = [
    [(0, "m"), (8, "M"), (3, "M"), (10, "M")],   # i  VI  III VII
    [(0, "m"), (5, "m"), (8, "M"), (7, "m")],    # i  iv  VI  v
    [(0, "m"), (10, "M"), (8, "M"), (10, "M")],  # i  VII VI  VII
    [(0, "m"), (3, "M"), (5, "m"), (8, "M")],    # i  III iv  VI
    [(0, "m"), (8, "M"), (5, "m"), (7, "m")],    # i  VI  iv  v
]


def _write(path, x):
    x = np.clip(x, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype(np.int16).tobytes())


def _lowpass(x, cutoff):
    """Gentle FFT low-pass (cheap and stable for a few seconds of audio)."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 / (1 + (f / max(cutoff, 1)) ** 4)
    return np.fft.irfft(X, len(x))


def _bandpass(x, lo, hi):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= ((f > lo) & (f < hi)).astype(float)
    return np.fft.irfft(X, len(x))


def _freq(semitone_from_a4):
    return 440.0 * 2 ** (semitone_from_a4 / 12)


def ambient_music(path, seconds, seed=None, level=0.18):
    """Warm minor pad: random key, random progression, slow chord changes with long crossfades,
    gently detuned voices, a soft sub, a little filtered air. Different every call."""
    rng = random.Random(seed)
    n = int(seconds * SR) + SR
    t = np.arange(n) / SR
    key = rng.choice(list(NOTES.values()))            # root pitch class
    prog = rng.choice(PROGRESSIONS)
    chord_len = rng.choice([4.0, 4.8, 5.6])
    out = np.zeros(n)
    nchords = int(np.ceil(seconds / chord_len)) + 1
    fade = 1.2
    for c in range(nchords):
        deg, kind = prog[c % len(prog)]
        root = key + deg - 9 - 12                     # around A2..G#3
        third = 3 if kind == "m" else 4
        voicing = [root, root + 7, root + 12 + third, root + 19]
        if rng.random() < 0.5:
            voicing.append(root + 24 + rng.choice([2, 7, 10]))  # an airy 9th / 5th / 7th on top
        start = c * chord_len
        env = np.clip((t - start + fade) / fade, 0, 1) * np.clip((start + chord_len + fade - t) / fade, 0, 1)
        if not env.any():
            continue
        for v in voicing:
            f0 = _freq(v)
            det = 1 + rng.uniform(-0.0025, 0.0025)
            ph = rng.uniform(0, 2 * np.pi)
            tone = (np.sin(2 * np.pi * f0 * det * t + ph) + 0.35 * np.sin(2 * np.pi * 2 * f0 * t + ph)
                    + 0.12 * np.sin(2 * np.pi * 3 * f0 * det * t))
            out += tone * env / len(voicing)
        sub = np.sin(2 * np.pi * _freq(root - 12) * t) * env * 0.35
        out += sub
    out = _lowpass(out, rng.uniform(900, 1500))
    air = _bandpass(np.random.default_rng(rng.randint(0, 10 ** 6)).normal(0, 1, n), 2500, 7000)
    lfo = 0.5 + 0.5 * np.sin(2 * np.pi * t / rng.uniform(7, 11))
    out += air * 0.02 * lfo
    out *= 0.85 + 0.15 * np.sin(2 * np.pi * t / rng.uniform(9, 14))   # slow swell
    edge = np.clip(t / 1.5, 0, 1) * np.clip((seconds + 0.5 - t) / 2.0, 0, 1)
    out *= edge
    out = out / (np.max(np.abs(out)) + 1e-9) * level
    _write(path, out[: int(seconds * SR)])
    return path


def _whoosh(rng):
    n = int(0.75 * SR)
    t = np.arange(n) / SR
    noise = np.random.default_rng(rng.randint(0, 10 ** 6)).normal(0, 1, n)
    out = np.zeros(n)
    bands = 12
    for b in range(bands):  # moving band-pass built from short band slices: a rising-then-falling sweep
        centre = 300 + 3200 * np.sin(np.pi * (b + 0.5) / bands)
        seg = _bandpass(noise, centre * 0.7, centre * 1.3)
        win = np.exp(-((t - (b + 0.5) / bands * 0.75) ** 2) / (2 * 0.045 ** 2))
        out += seg * win
    out *= np.sin(np.pi * np.clip(t / 0.75, 0, 1)) ** 1.5
    return out / (np.max(np.abs(out)) + 1e-9) * 0.55


def _paper(rng):
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    g = np.random.default_rng(rng.randint(0, 10 ** 6))
    out = np.zeros(n)
    for _ in range(9):  # little crinkles
        at = g.uniform(0.0, 0.33)
        dur = g.uniform(0.01, 0.05)
        burst = g.normal(0, 1, n) * np.exp(-np.clip(t - at, 0, None) / dur) * (t >= at)
        out += burst * g.uniform(0.3, 1.0)
    out = _bandpass(out, 1800, 9000)
    return out / (np.max(np.abs(out)) + 1e-9) * 0.42


def _stamp(rng):
    n = int(0.5 * SR)
    t = np.arange(n) / SR
    thump = np.sin(2 * np.pi * (95 * np.exp(-t * 6)) * t) * np.exp(-t * 14)
    click = _bandpass(np.random.default_rng(rng.randint(0, 10 ** 6)).normal(0, 1, n), 1500, 6000) * np.exp(-t * 90)
    out = thump * 1.0 + click * 0.5
    return out / (np.max(np.abs(out)) + 1e-9) * 0.8


def sfx(folder, seed=None):
    """Writes whoosh.wav, paper.wav and stamp.wav into folder (fresh variations each call)."""
    rng = random.Random(seed)
    folder = Path(folder)
    _write(folder / "whoosh.wav", _whoosh(rng))
    _write(folder / "paper.wav", _paper(rng))
    _write(folder / "stamp.wav", _stamp(rng))
    return folder
