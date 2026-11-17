"""Background music.

* procedural – an original synthwave-style beat generated from code for each
  video (tempo, key, progression and pattern vary by seed). Nobody else owns
  it, so it is always safe to use.
* licensed – tracks you add to assets/music/ AND list in assets/music/LICENSES.yaml
  with their licence. Unlisted files are never used.
"""
from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import yaml
from scipy.signal import butter, sosfilt

SR = 48000
PROGRESSIONS = [  # (chord roots in semitones from the key root, chord intervals)
    [(0, (0, 3, 7)), (8, (0, 4, 7)), (3, (0, 4, 7)), (10, (0, 4, 7))],   # i  VI III VII
    [(0, (0, 3, 7)), (5, (0, 3, 7)), (8, (0, 4, 7)), (7, (0, 4, 7))],    # i  iv VI  V
    [(0, (0, 3, 7)), (10, (0, 4, 7)), (8, (0, 4, 7)), (10, (0, 4, 7))],  # i  VII VI VII
]


def hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _adsr(n: int, a: float, d: float, s: float, r: float) -> np.ndarray:
    env = np.full(n, s, np.float32)
    na, nd, nr = int(a * SR), int(d * SR), int(r * SR)
    na = min(na, n)
    env[:na] = np.linspace(0, 1, na, endpoint=False)
    nd = min(nd, n - na)
    env[na:na + nd] = np.linspace(1, s, nd, endpoint=False)
    if nr and n > nr:
        env[-nr:] *= np.linspace(1, 0, nr)
    return env


def _saw(freq: float, n: int, harmonics: int = 14, detune: float = 0.0) -> np.ndarray:
    t = np.arange(n) / SR
    out = np.zeros(n, np.float32)
    f = freq * (2 ** (detune / 1200))
    for k in range(1, harmonics + 1):
        if f * k > SR / 2 - 1000:
            break
        out += (np.sin(2 * np.pi * f * k * t) / k).astype(np.float32)
    return out * 0.6


def _lp(x: np.ndarray, cutoff: float, order: int = 2) -> np.ndarray:
    return sosfilt(butter(order, cutoff, btype="low", fs=SR, output="sos"), x).astype(np.float32)


def _noise(n: int, rng: np.random.Generator) -> np.ndarray:
    return rng.standard_normal(n).astype(np.float32)


def generate_loop(seed: int) -> tuple[np.ndarray, float]:
    """Four bars of music (mono float32) and the BPM used."""
    r = random.Random(seed)
    nrng = np.random.default_rng(seed)
    bpm = r.randint(92, 108)
    beat = 60.0 / bpm
    bars = 4
    n = int(bars * 4 * beat * SR)
    root = r.choice([33, 35, 36, 38, 40])  # A1, B1, C2, D2, E2
    prog = r.choice(PROGRESSIONS)
    kick = np.zeros(n, np.float32)
    drums = np.zeros(n, np.float32)
    bass = np.zeros(n, np.float32)
    pad = np.zeros(n, np.float32)
    arp = np.zeros(n, np.float32)
    kick_env = np.zeros(n, np.float32)
    extra_kick = r.random() < 0.6
    use_arp = r.random() < 0.6

    def at(beat_pos: float) -> int:
        return int(beat_pos * beat * SR)

    # drums
    kl = int(0.32 * SR)
    t = np.arange(kl) / SR
    k_freq = 46 + 110 * np.exp(-t * 32)
    k_wave = np.sin(2 * np.pi * np.cumsum(k_freq) / SR) * np.exp(-t * 9)
    k_wave[: int(0.004 * SR)] += _noise(int(0.004 * SR), nrng) * 0.3
    cl = int(0.18 * SR)
    clap = sosfilt(butter(2, [900, 5000], btype="band", fs=SR, output="sos"), _noise(cl, nrng))
    clap = clap * np.exp(-np.arange(cl) / SR * 26) + np.sin(2 * np.pi * 190 * np.arange(cl) / SR) * \
        np.exp(-np.arange(cl) / SR * 40) * 0.5
    hl = int(0.045 * SR)
    hat = sosfilt(butter(2, 7000, btype="high", fs=SR, output="sos"), _noise(hl, nrng)) * \
        np.exp(-np.arange(hl) / SR * 90)

    for bar in range(bars):
        b0 = bar * 4
        hits = [0, 2] + ([2.5] if extra_kick and bar % 2 == 1 else []) + ([3.5] if bar == bars - 1 else [])
        for h in hits:
            s = at(b0 + h)
            e = min(s + kl, n)
            kick[s:e] += k_wave[: e - s]
            kick_env[s:e] = np.maximum(kick_env[s:e], np.exp(-np.arange(e - s) / SR * 6))
        for h in (1, 3):
            s = at(b0 + h)
            e = min(s + cl, n)
            drums[s:e] += clap[: e - s] * 0.55
        for i in range(8):
            s = at(b0 + i * 0.5)
            e = min(s + hl, n)
            drums[s:e] += hat[: e - s] * (0.22 if i % 2 else 0.12)

        chord_root, intervals = prog[bar % len(prog)]
        bar_len = at(4)
        s = at(b0)
        # pad: sustained chord, two detuned saws per note
        chord = np.zeros(bar_len, np.float32)
        for iv in intervals:
            f = hz(root + 24 + chord_root + iv)
            chord += _saw(f, bar_len, 10, -7) + _saw(f, bar_len, 10, 7)
        pad[s:s + bar_len] += _lp(chord, 1500) * _adsr(bar_len, 0.25, 0.4, 0.8, 0.3) * 0.12
        # bass: driving eighths
        for i in range(8):
            ns = at(b0 + i * 0.5)
            nl = int(0.5 * beat * SR * 0.85)
            octave = 12 if i in (3, 7) else 0
            note = _saw(hz(root + chord_root + octave), nl, 8)
            bass[ns:ns + nl] += _lp(note, 650) * _adsr(nl, 0.004, 0.12, 0.55, 0.03)[: nl] * 0.5
        # arp: sixteenth notes through the chord
        if use_arp:
            seq = [0, 1, 2, 1] if r.random() < 0.5 else [0, 2, 1, 2]
            for i in range(16):
                ns = at(b0 + i * 0.25)
                nl = int(0.25 * beat * SR * 0.7)
                f = hz(root + 36 + chord_root + intervals[seq[i % 4]])
                tt = np.arange(nl) / SR
                tone = np.sign(np.sin(2 * np.pi * f * tt)) * 0.3 + np.sin(2 * np.pi * f * tt) * 0.7
                arp[ns:ns + nl] += _lp(tone.astype(np.float32), 2600) * np.exp(-tt * 18) * 0.08

    pump = 1.0 - 0.45 * kick_env
    mix = kick * 0.9 + drums + (bass + pad + arp) * pump
    mix = np.tanh(mix * 1.2) / np.tanh(1.2)
    mix /= np.abs(mix).max() + 1e-9
    return (mix * 0.9).astype(np.float32), float(bpm)


def procedural_track(seconds: float, seed: int) -> np.ndarray:
    loop, _ = generate_loop(seed)
    n = int(seconds * SR)
    reps = int(np.ceil(n / loop.size))
    track = np.tile(loop, reps)[:n]
    fade_in, fade_out = int(0.25 * SR), int(1.2 * SR)
    track[:fade_in] *= np.linspace(0, 1, fade_in)
    track[-fade_out:] *= np.linspace(1, 0, fade_out)
    return track


def licensed_tracks(music_dir: str | Path) -> list[dict]:
    """Tracks with a licence entry. Each entry: file, title, artist, license, url, attribution."""
    manifest = Path(music_dir) / "LICENSES.yaml"
    if not manifest.exists():
        return []
    entries = (yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}).get("tracks", []) or []
    out = []
    for e in entries:
        f = Path(music_dir) / str(e.get("file", ""))
        if f.exists() and e.get("license") and e.get("allowed_platforms"):
            out.append({**e, "path": str(f)})
    return out
