"""Tiny synthesised sound effects (original, so no licensing questions)."""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt

SR = 48000


def _env(n: int, attack: float, decay: float) -> np.ndarray:
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    return a * np.exp(-np.maximum(t - attack, 0) / max(decay, 1e-4))


def whoosh(duration: float = 0.38, seed: int = 0) -> np.ndarray:
    """Filtered noise sweep that peaks at the end (placed just before a cut)."""
    rng = np.random.default_rng(seed)
    n = int(duration * SR)
    noise = rng.standard_normal(n).astype(np.float32)
    out = np.zeros(n, np.float32)
    steps = 12
    seg = n // steps
    for i in range(steps):
        lo = 300 + 3500 * (i / steps) ** 1.5
        sos = butter(2, [lo, min(lo * 2.2, SR / 2 - 100)], btype="band", fs=SR, output="sos")
        part = sosfilt(sos, noise[i * seg:(i + 1) * seg + 256])[:seg]
        out[i * seg:(i + 1) * seg] = part
    t = np.linspace(0, 1, n, dtype=np.float32)
    shape = (t ** 2.2) * np.clip((1 - t) * 12, 0, 1)
    out *= shape
    return (out / (np.abs(out).max() + 1e-9) * 0.55).astype(np.float32)


def pop(freq: float = 880.0, duration: float = 0.12) -> np.ndarray:
    n = int(duration * SR)
    t = np.arange(n) / SR
    f = freq * (1 + 0.6 * np.exp(-t * 60))
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.002, 0.035)
    return (tone * 0.5).astype(np.float32)


def alert(duration: float = 0.3) -> np.ndarray:
    """Two quick blips for RUMOR / MYTH badges."""
    a, b = pop(660, 0.12), pop(990, 0.14)
    out = np.zeros(int(duration * SR), np.float32)
    out[: a.size] += a
    off = int(0.11 * SR)
    out[off: off + b.size] += b[: out.size - off]
    return out * 0.8


def riser(duration: float = 0.9, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(duration * SR)
    noise = rng.standard_normal(n).astype(np.float32)
    sos = butter(2, 2500, btype="high", fs=SR, output="sos")
    out = sosfilt(sos, noise) * np.linspace(0, 1, n) ** 3
    return (out / (np.abs(out).max() + 1e-9) * 0.3).astype(np.float32)
