"""Free text-to-speech engines.

* Kokoro (kokoro-onnx, Apache-2.0 model) – natural, expressive, runs on the
  free GitHub Actions CPU. This is the production voice.
* Flite (built into Ubuntu's FFmpeg) – robotic, but needs no download. Used
  only for tests and as an emergency fallback; the QC report flags it.

Both return mono float32 samples in [-1, 1] and a sample rate.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

from ..config import Paths
from .normalize import speakable

KOKORO_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
KOKORO_VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"


class TTSEngine:
    name = "base"
    production_quality = False

    def synth(self, text: str) -> tuple[np.ndarray, int]:
        raise NotImplementedError


def _read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr, n, ch, width = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    if width != 2:
        raise ValueError("expected 16-bit WAV")
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, sr


class FliteEngine(TTSEngine):
    name = "flite"

    def __init__(self, voice: str = "slt", speed: float = 1.1, sample_rate: int = 24000):
        self.voice, self.speed, self.sr = voice, speed, sample_rate

    @staticmethod
    def available() -> bool:
        if not shutil.which("ffmpeg"):
            return False
        probe = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
        return " flite " in probe.stdout

    def synth(self, text: str) -> tuple[np.ndarray, int]:
        with tempfile.TemporaryDirectory() as tmp:
            txt = Path(tmp) / "t.txt"
            out = Path(tmp) / "o.wav"
            txt.write_text(speakable(text).replace("'", "’"), encoding="utf-8")
            # Pitch lifted ~6% and tempo raised for a livelier test voice.
            af = f"asetrate=16000*1.06,aresample=16000,atempo={self.speed / 1.06:.3f},aresample={self.sr}"
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                   "-i", f"flite=textfile={txt}:voice={self.voice}", "-af", af, "-ac", "1", "-c:a", "pcm_s16le",
                   str(out)]
            subprocess.run(cmd, check=True)
            return _read_wav(out)


class KokoroEngine(TTSEngine):
    name = "kokoro"
    production_quality = True

    def __init__(self, voice: str = "af_bella", speed: float = 1.1, model_dir: str | Path | None = None):
        from kokoro_onnx import Kokoro  # imported lazily: optional dependency

        model_dir = Path(model_dir or os.environ.get("KOKORO_DIR") or Paths().models)
        model = model_dir / "kokoro-v1.0.onnx"
        voices = model_dir / "voices-v1.0.bin"
        if not model.exists() or not voices.exists():
            raise FileNotFoundError(f"Kokoro model files not found in {model_dir}. "
                                    f"Run: python -m shorts setup-voice")
        self.kokoro = Kokoro(str(model), str(voices))
        self.speed = speed
        self.voice = self._voice(voice)

    def _voice(self, spec: str):
        """'af_bella' or a blend like 'af_bella:60,af_heart:40' (an original mix, not a clone)."""
        if "," not in spec and ":" not in spec:
            return spec
        parts = [p.split(":") for p in spec.split(",")]
        total = sum(float(w) for _, w in parts)
        style = None
        for name, weight in parts:
            vec = self.kokoro.get_voice_style(name.strip()) * (float(weight) / total)
            style = vec if style is None else style + vec
        return style

    @staticmethod
    def available(model_dir: str | Path | None = None) -> bool:
        try:
            import kokoro_onnx  # noqa: F401
        except ImportError:
            return False
        d = Path(model_dir or os.environ.get("KOKORO_DIR") or Paths().models)
        return (d / "kokoro-v1.0.onnx").exists() and (d / "voices-v1.0.bin").exists()

    def synth(self, text: str) -> tuple[np.ndarray, int]:
        samples, sr = self.kokoro.create(speakable(text), voice=self.voice, speed=self.speed, lang="en-us")
        return np.asarray(samples, dtype=np.float32), int(sr)


def select_engine(settings: dict, override: str | None = None) -> TTSEngine:
    v = settings["voice"]
    choice = override or v.get("engine", "auto")
    if choice in ("auto", "kokoro") and KokoroEngine.available():
        return KokoroEngine(v.get("kokoro_voice", "af_bella"), float(v.get("speed", 1.1)))
    if choice == "kokoro":
        raise RuntimeError("Kokoro requested but not installed – run: python -m shorts setup-voice")
    if FliteEngine.available():
        return FliteEngine(v.get("flite_voice", "slt"), float(v.get("speed", 1.1)))
    raise RuntimeError("No TTS engine available (install kokoro-onnx or an FFmpeg build with libflite)")


def download_kokoro(model_dir: str | Path | None = None) -> Path:
    """Fetch the Kokoro model files (~340 MB, cached by the workflow)."""
    import requests

    d = Path(model_dir or os.environ.get("KOKORO_DIR") or Paths().models)
    d.mkdir(parents=True, exist_ok=True)
    for url in (KOKORO_MODEL_URL, KOKORO_VOICES_URL):
        target = d / url.rsplit("/", 1)[1]
        if target.exists() and target.stat().st_size > 1_000_000:
            continue
        tmp = target.with_suffix(".part")
        with requests.get(url, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        tmp.replace(target)
    return d
