"""Quality control: a video is only queued for review/publishing if every
error-level check passes. Uses ffprobe/ffmpeg measurements, not guesses."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .models import Issue


def probe(path: str | Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def loudness(path: str | Path) -> dict:
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
                           "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                          capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
    if not m:
        return {}
    d = json.loads(m.group(0))
    return {"lufs": float(d["input_i"]), "true_peak": float(d["input_tp"]), "lra": float(d["input_lra"])}


def silences(path: str | Path, min_len: float, noise_db: int = -42) -> list[tuple[float, float]]:
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
                           f"silencedetect=noise={noise_db}dB:d={min_len}", "-f", "null", "-"],
                          capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    return list(zip(starts, ends + [float("inf")] * (len(starts) - len(ends))))


def black_segments(path: str | Path, min_len: float) -> list[tuple[float, float]]:
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vf",
                           f"blackdetect=d={min_len}:pix_th=0.06", "-an", "-f", "null", "-"],
                          capture_output=True, text=True)
    return [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", proc.stderr)]


def run_qc(video: str | Path, timeline, script_issues: list[Issue], engine_production: bool,
           settings: dict) -> dict:
    q, v = settings["qc"], settings["video"]
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str, level: str = "error") -> None:
        checks.append({"name": name, "ok": bool(ok), "level": level, "detail": detail})

    info = probe(video)
    vs = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    aus = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    duration = float(info["format"]["duration"])
    size_mb = int(info["format"]["size"]) / 1e6

    check("video_stream", vs is not None, "has a video stream")
    if vs:
        check("resolution", (vs["width"], vs["height"]) == (v["width"], v["height"]),
              f"{vs['width']}x{vs['height']} (need {v['width']}x{v['height']})")
        num, den = (int(x) for x in vs["r_frame_rate"].split("/"))
        check("frame_rate", abs(num / den - v["fps"]) < 0.01, f"{num / den:.2f} fps")
        check("codec", vs["codec_name"] == "h264" and vs.get("pix_fmt") == "yuv420p",
              f"{vs['codec_name']} {vs.get('pix_fmt')}")
    check("audio_stream", aus is not None, "has an audio stream")
    if aus:
        check("audio_format", aus["codec_name"] == "aac" and int(aus["sample_rate"]) == 48000,
              f"{aus['codec_name']} {aus['sample_rate']} Hz {aus.get('channels')} ch")
    check("duration", v["min_seconds"] <= duration <= v["max_seconds"],
          f"{duration:.1f}s (allowed {v['min_seconds']}–{v['max_seconds']}s)")
    check("shorts_limit", duration <= 180, "YouTube Shorts must be 3 minutes or less")
    check("file_size", size_mb < 250, f"{size_mb:.1f} MB", level="warning")

    loud = loudness(video)
    if loud:
        off = abs(loud["lufs"] - q["target_lufs"])
        check("loudness", off <= q["lufs_tolerance"] + 1.0,
              f"{loud['lufs']:.1f} LUFS (target {q['target_lufs']})",
              level="error" if off > q["lufs_tolerance"] + 1.0 else "warning")
        check("true_peak", loud["true_peak"] <= q["max_true_peak_db"] + 0.5, f"{loud['true_peak']:.1f} dBTP",
              level="warning")
    else:
        check("loudness", False, "could not measure loudness")

    content_end = timeline.scenes[-1].end - 0.8 if timeline.scenes else duration
    long_silences = [(a, b) for a, b in silences(video, q["max_silence_seconds"]) if a < content_end]
    check("no_dead_air", not long_silences,
          "no silence longer than %.1fs" % q["max_silence_seconds"] if not long_silences
          else f"silence at {', '.join(f'{a:.1f}–{min(b, duration):.1f}s' for a, b in long_silences)}")
    blacks = black_segments(video, q["max_black_seconds"])
    check("no_black_frames", not blacks, "no black segments" if not blacks else f"black at {blacks}")

    words_total = sum(len(ts.words) for ts in timeline.scenes)
    words_captioned = sum(len(c["words"]) for c in timeline.chunks)
    check("captions_complete", words_total == words_captioned and words_total > 0,
          f"{words_captioned}/{words_total} words captioned")
    check("captions_in_range", all(c["end"] <= duration + 0.05 for c in timeline.chunks),
          "every caption ends before the video does")
    first_word = timeline.chunks[0]["start"] if timeline.chunks else 99
    check("hook_speed", first_word <= 0.5, f"voice starts at {first_word:.2f}s (hook must land in the first 2s)")
    hook_end = timeline.scenes[0].end if timeline.scenes else 99
    check("hook_length", hook_end <= 4.5, f"hook scene lasts {hook_end:.1f}s", level="warning")
    if aus and vs:
        a_dur = float(aus.get("duration", duration))
        v_dur = float(vs.get("duration", duration))
        check("av_sync_length", abs(a_dur - v_dur) < 0.15, f"audio {a_dur:.2f}s vs video {v_dur:.2f}s")
    check("voice_quality", engine_production,
          "production voice (Kokoro)" if engine_production else "TEST VOICE (Flite) – not for publishing",
          level="error" if settings.get("stage", 2) >= 3 else "warning")
    for issue in script_issues:
        check(f"script:{issue.code}", False, issue.message, level=issue.level)

    errors = [c for c in checks if not c["ok"] and c["level"] == "error"]
    warnings = [c for c in checks if not c["ok"] and c["level"] == "warning"]
    return {"passed": not errors, "errors": len(errors), "warnings": len(warnings), "duration": round(duration, 2),
            "size_mb": round(size_mb, 2), "loudness": loud, "checks": checks}
