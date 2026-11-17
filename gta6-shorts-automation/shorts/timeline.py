"""Turn a script into a frame-accurate timeline: voice audio placed per
sentence, word timings for captions, and scene boundaries on whole frames."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .models import Script, TimedScene, Word
from .voice.engines import TTSEngine
from .voice.timing import speech_bounds, split_sentences, word_times


@dataclass
class Timeline:
    scenes: list[TimedScene]
    fps: int
    total_frames: int
    engine: str
    chunks: list[dict] = field(default_factory=list)   # caption chunks

    @property
    def duration(self) -> float:
        return self.total_frames / self.fps


def build_timeline(script: Script, engine: TTSEngine, fps: int = 30, sentence_gap: float = 0.08,
                   scene_gap: float = 0.12, tail: float = 0.9, words_per_chunk: int = 3) -> Timeline:
    t = 0.0
    timed: list[TimedScene] = []
    for idx, scene in enumerate(script.scenes):
        ts = TimedScene(scene=scene, index=idx, start=t, end=t, start_frame=0, end_frame=0)
        ts.audio = []  # type: ignore[attr-defined]
        sentences = split_sentences(scene.narration) or [scene.narration]
        for si, sentence in enumerate(sentences):
            samples, sr = engine.synth(sentence)
            a, b = speech_bounds(samples, sr)
            clip = samples[a:b] if b > a else samples
            dur = clip.size / sr
            ts.audio.append((t, clip, sr))  # type: ignore[attr-defined]
            for text, ws, we in word_times(sentence.split(), t, t + dur):
                ts.words.append(Word(text, ws, we))
            t += dur + (sentence_gap if si < len(sentences) - 1 else 0.0)
        ts.end = t
        t += scene_gap
        timed.append(ts)
    total = timed[-1].end + tail if timed else 0.0
    total_frames = int(round(total * fps))
    # Visual boundaries: each scene runs until the next scene's voice starts (cut on the word).
    for i, ts in enumerate(timed):
        ts.start_frame = 0 if i == 0 else int(round(ts.start * fps))
        ts.end_frame = int(round(timed[i + 1].start * fps)) if i + 1 < len(timed) else total_frames
        ts.start = ts.start_frame / fps
        ts.end = ts.end_frame / fps
    tl = Timeline(timed, fps, total_frames, engine.name)
    tl.chunks = caption_chunks(timed, words_per_chunk)
    return tl


_GLUE_AFTER = {"gta", "grand", "theft", "auto", "xbox", "series", "playstation", "vice", "mount", "port",
               "number", "leonida", "trailer", "the", "a", "an", "of", "jan", "feb", "mar", "apr", "jun", "jul",
               "aug", "sep", "sept", "oct", "nov", "dec", "january", "february", "march", "april", "may", "june",
               "july", "august", "september", "october", "november", "december"}


def _glued(word: str, nxt: str | None) -> bool:
    """True if `word` and `nxt` must stay in the same caption ("GTA 6", "November 19", "Xbox Series")."""
    if nxt is None or word.endswith((".", "!", "?", ",", ":", ";")):
        return False
    return word.lower().strip("'\"") in _GLUE_AFTER


def caption_chunks(timed: list[TimedScene], max_words: int = 3, max_chars: int = 18) -> list[dict]:
    """Group words into short caption chunks; each stays up until the next one starts."""
    chunks: list[dict] = []
    for ts in timed:
        cur: list[Word] = []
        for i, w in enumerate(ts.words):
            cur.append(w)
            nxt = ts.words[i + 1].text if i + 1 < len(ts.words) else None
            text_len = sum(len(x.text) for x in cur) + len(cur) - 1
            full = len(cur) >= max_words or text_len >= max_chars
            if _glued(w.text, nxt) and len(cur) <= max_words + 1 and text_len < max_chars + 10:
                continue
            if full or w.text.endswith((".", "!", "?", ",", ":")):
                chunks.append({"scene": ts.index, "words": cur})
                cur = []
        if cur:
            chunks.append({"scene": ts.index, "words": cur})
    for i, c in enumerate(chunks):
        c["start"] = c["words"][0].start
        nxt = chunks[i + 1]["words"][0].start if i + 1 < len(chunks) else None
        scene_end = timed[c["scene"]].end
        c["end"] = min(nxt, scene_end) if nxt is not None else scene_end
        if c["end"] - c["words"][-1].end > 0.6:      # don't linger through long pauses
            c["end"] = c["words"][-1].end + 0.35
    return chunks


def to_srt(chunks: list[dict]) -> str:
    def stamp(sec: float) -> str:
        ms = int(round(sec * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    lines = []
    for i, c in enumerate(chunks, 1):
        text = " ".join(w.text for w in c["words"])
        lines.append(f"{i}\n{stamp(c['start'])} --> {stamp(c['end'])}\n{text}\n")
    return "\n".join(lines)


def audio_seconds(tl: Timeline) -> float:
    return float(sum(clip.size / sr for ts in tl.scenes for _, clip, sr in ts.audio))  # type: ignore[attr-defined]


def is_silent(samples: np.ndarray) -> bool:
    return samples.size == 0 or float(np.abs(samples).max()) < 1e-4
