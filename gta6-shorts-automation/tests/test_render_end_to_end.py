"""Real end-to-end render with the offline test voice (≈30–60 s). Proves the
whole chain: script -> verification -> voice -> captions -> frames -> FFmpeg -> QC."""
import json
import shutil

import pytest

from shorts.qc import probe
from shorts.registry import Registry

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def test_full_video_render_passes_qc(settings, tmp_paths):
    from shorts.pipeline import create_video
    from shorts.voice.engines import FliteEngine
    if not FliteEngine.available():
        pytest.skip("FFmpeg without flite")
    res = create_video(settings, tmp_paths, tts="flite", fmt="myth_buster", seed="test", register=True)
    qc = res["qc"]
    failed = [c for c in qc["checks"] if not c["ok"] and c["level"] == "error"]
    assert qc["passed"], failed
    out = tmp_paths.out / res["record"]["id"]
    for name in ("video.mp4", "captions.srt", "script.json", "metadata.json", "qc.json", "preview.jpg",
                 "contact_sheet.jpg"):
        assert (out / name).exists(), name
    info = probe(out / "video.mp4")
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1080, 1920)
    assert 20 <= float(info["format"]["duration"]) <= 60
    rec = Registry(tmp_paths.registry).get(res["record"]["id"])
    assert rec["status"] == "awaiting_review" and rec["voice"] == "flite"
    # flite is flagged so it can never be published
    assert any(c["name"] == "voice_quality" and not c["ok"] for c in qc["checks"])
    assert json.loads((out / "metadata.json").read_text())["title"]
    # second video the same day must differ (originality + style rotation)
    res2 = create_video(settings, tmp_paths, tts="flite", seed="test2", register=True)
    assert res2["record"]["narration"] != res["record"]["narration"]
    assert res2["record"]["style"] != res["record"]["style"]
