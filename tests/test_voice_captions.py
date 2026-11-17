import shutil

import numpy as np
import pytest

from shorts.models import Scene, TimedScene, Word
from shorts.timeline import caption_chunks, to_srt
from shorts.voice.normalize import int_to_words, ordinal_words, speakable, year_words
from shorts.voice.timing import speech_bounds, split_sentences, syllables, word_times


@pytest.mark.parametrize("text,expected", [
    ("GTA 6 is 2 days away.", "G T A six is two days away."),
    ("It launches Thursday, November 19, 2026.", "It launches Thursday, November nineteenth, twenty twenty-six."),
    ("Standard Edition is $79.99.", "Standard Edition is seventy-nine ninety-nine."),
    ("Europe: €79.99 for Standard.", "Europe: seventy-nine ninety-nine euros for Standard."),
    ("PS5 or Xbox Series X|S.", "P S five or Xbox Series X and S."),
    ("93 million views in 24 hours", "ninety-three million views in twenty-four hours"),
    ("Grand Theft Auto VI", "Grand Theft Auto six"),
    ("Vice City, 2002.", "Vice City, two thousand two."),
    ("#1 pick, 1st place", "number one pick, first place"),
])
def test_tts_normalisation(text, expected):
    assert speakable(text) == expected


def test_number_words():
    assert int_to_words(475_000_000) == "four hundred seventy-five million"
    assert ordinal_words(22) == "twenty-second" and ordinal_words(30) == "thirtieth"
    assert year_words(1999) == "nineteen ninety-nine" and year_words(2009) == "two thousand nine"


def test_sentence_split_keeps_prices():
    assert split_sentences("It is $79.99. Then $99.99! PC? No.") == ["It is $79.99.", "Then $99.99!", "PC?", "No."]


def test_word_times_are_ordered_and_bounded():
    toks = "Only 2 days until GTA 6, and you need to know this.".split()
    times = word_times(toks, 1.0, 4.0)
    assert times[0][1] == 1.0 and times[-1][2] == pytest.approx(4.0, abs=0.01)
    assert all(a[2] <= b[1] + 1e-6 for a, b in zip(times, times[1:]))
    assert syllables("Leonida") >= 3


def test_speech_bounds_trims_silence():
    sr = 24000
    x = np.zeros(sr * 2, np.float32)
    x[int(0.5 * sr):int(1.5 * sr)] = 0.5 * np.sin(np.linspace(0, 2000, sr))
    a, b = speech_bounds(x, sr)
    assert 0.45 < a / sr < 0.5 and 1.5 <= b / sr < 1.56


def test_caption_chunks_keep_names_together():
    words = [Word(t, i * 0.3, i * 0.3 + 0.25) for i, t in enumerate("left until GTA 6. Xbox Series X|S is".split())]
    ts = TimedScene(scene=Scene("point", " ".join(w.text for w in words)), index=0, start=0, end=3,
                    start_frame=0, end_frame=90, words=words)
    chunks = caption_chunks([ts], max_words=3)
    texts = [" ".join(w.text for w in c["words"]) for c in chunks]
    assert any(t.endswith("GTA 6.") for t in texts), texts
    assert not any(t.endswith("GTA") for t in texts)
    assert sum(len(c["words"]) for c in chunks) == len(words)
    srt = to_srt(chunks)
    assert srt.startswith("1\n00:00:00,000 --> ")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_flite_test_voice_produces_audio():
    from shorts.voice.engines import FliteEngine
    if not FliteEngine.available():
        pytest.skip("this FFmpeg has no flite")
    samples, sr = FliteEngine().synth("GTA 6 is 2 days away.")
    assert sr == 24000 and samples.size > sr and np.abs(samples).max() > 0.05
