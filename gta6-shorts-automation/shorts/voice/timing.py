"""Word timings for captions.

Each sentence is synthesised separately, so its exact start/end on the
timeline is known. Inside a sentence, words are placed proportionally to
how long they take to say (syllables of the *spoken* form) plus pauses at
punctuation. Errors therefore never accumulate past one sentence.
"""
from __future__ import annotations

import re

import numpy as np

from .normalize import speak_tokens

_VOWELS = re.compile(r"[aeiouy]+")


def syllables(word: str) -> int:
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    if len(w) == 1:  # spelled letters: "G T A"
        return 3 if w == "w" else 1
    count = len(_VOWELS.findall(w))
    if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and count > 1:
        count -= 1
    return max(count, 1)


def spoken_weight(spoken: str) -> float:
    return sum(syllables(part) for part in re.split(r"[\s-]+", spoken)) or 1.0


def pause_weight(token: str) -> float:
    if token.endswith(("...", "…")):
        return 2.0
    if token.endswith((".", "!", "?")):
        return 1.6
    if token.endswith((":", ";")):
        return 1.2
    if token.endswith(","):
        return 0.8
    return 0.0


def split_sentences(text: str) -> list[str]:
    """Split on . ! ? followed by space + capital/digit/$, keeping decimals like 79.99 intact."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9$€£#\"“])", text.strip())
    return [p.strip() for p in parts if p.strip()]


def speech_bounds(samples: np.ndarray, sr: int, threshold_db: float = -38.0, pad: float = 0.02) -> tuple[int, int]:
    """First/last sample above the threshold (with a little padding)."""
    if samples.size == 0:
        return 0, 0
    win = max(int(sr * 0.01), 1)
    n = samples.size // win
    if n == 0:
        return 0, samples.size
    frames = samples[: n * win].reshape(n, win)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-12)
    peak = rms.max() if rms.size else 0.0
    if peak <= 0:
        return 0, samples.size
    level = 20 * np.log10(rms / peak + 1e-12)
    active = np.where(level > threshold_db)[0]
    if active.size == 0:
        return 0, samples.size
    start = max(int(active[0] * win - pad * sr), 0)
    end = min(int((active[-1] + 1) * win + pad * sr), samples.size)
    return start, end


def word_times(tokens: list[str], start: float, end: float) -> list[tuple[str, float, float]]:
    """Distribute display tokens across [start, end] seconds."""
    if not tokens:
        return []
    spoken = speak_tokens(tokens)
    speech = [spoken_weight(s) for s in spoken]
    pauses = [pause_weight(t) for t in tokens]
    pauses[-1] = 0.0
    total = sum(speech) + sum(pauses)
    unit = (end - start) / total if total else 0.0
    out, t = [], start
    for tok, s, p in zip(tokens, speech, pauses):
        w_end = t + s * unit
        out.append((tok, round(t, 3), round(w_end, 3)))
        t = w_end + p * unit
    return out
