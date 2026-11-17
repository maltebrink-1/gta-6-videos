"""End-to-end video creation: topic -> script -> checks -> voice -> render -> audio -> QC -> registry."""
from __future__ import annotations

import json
import logging
import random
import re
import shutil
import time
from pathlib import Path

import cv2
import numpy as np

from .audio.mix import build_stems, master
from .config import Paths, now_iso, today
from .facts import load_facts, usable_facts, validate_facts
from .models import Script
from .publish.metadata import build_metadata
from .qc import run_qc
from .registry import Registry
from .render.compositor import Compositor, concat, mux, render_scenes
from .render.styles import Style, pick_style
from .timeline import build_timeline, to_srt
from .topics import choose_plan
from .usage import Usage
from .voice.engines import select_engine
from .writer import write_script

log = logging.getLogger(__name__)


class DailyCapReached(RuntimeError):
    pass


def tidy_script(script: Script) -> Script:
    """Small consistency fixes applied to every writer's output."""
    for s in script.scenes:
        s.narration = re.sub(r"\bGTA VI\b", "GTA 6", s.narration).strip()
        s.narration = re.sub(r"\s+", " ", s.narration)
        s.on_screen = s.on_screen.strip()
    return script


def contact_sheet(comp: Compositor, path: Path) -> Path:
    picks = [0] + [min(ts.start_frame + 15, ts.end_frame - 1) for ts in comp.tl.scenes[1:]]
    picks = picks[:6]
    thumbs = [cv2.resize(comp.frame(f), (270, 480), interpolation=cv2.INTER_AREA) for f in picks]
    sheet = np.concatenate(thumbs, axis=1)
    cv2.imwrite(str(path), cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
    return path


def create_video(settings: dict, paths: Paths | None = None, tts: str | None = None, fmt: str | None = None,
                 seed: str | None = None, register: bool = True, keep_work: bool = False,
                 style_spec: str | None = None) -> dict:
    paths = paths or Paths()
    started = time.time()
    day = today()
    facts = load_facts(paths.facts)
    errors = [i for i in validate_facts(facts, day) if i.level == "error"]
    if errors:
        raise ValueError("facts.yaml has errors:\n" + "\n".join(map(str, errors)))
    pool = usable_facts(facts, day)
    registry = Registry(paths.registry)
    usage = Usage(paths.usage)
    o = settings["originality"]
    history = registry.history(o["history_window"])

    made_today = registry.created_on(day.isoformat())
    if register and len(made_today) >= settings["schedule"]["max_videos_per_day"]:
        raise DailyCapReached(f"already made {len(made_today)} videos today (cap "
                              f"{settings['schedule']['max_videos_per_day']})")
    video_id = f"{day.isoformat()}-{len(made_today) + 1:02d}"
    while registry.get(video_id):
        video_id += "b"
    rng = random.Random(seed or f"{video_id}-{now_iso()}")

    plan = choose_plan(pool, history, day, rng, forced_format=fmt, format_cooldown=o["format_cooldown"])
    script, script_issues, trail = write_script(plan, pool, facts, video_id, settings, history, day, usage, rng)
    tidy_script(script)
    log.info("script by %s: %s", script.provider, script.title)

    recent_styles = [h["style"] for h in history if h.get("style")]
    rumor_heavy = any(s.badge in ("RUMOR", "MYTH") for s in script.scenes)
    style = pick_style(rng, recent_styles, settings["captions"].get("style", "auto"), rumor_heavy)
    if style_spec:  # e.g. "vice_sunset/synth_grid/pop/flash" (palette/background/captions/transition)
        parts = style_spec.split("/")
        style = Style(parts[0], parts[1] if len(parts) > 1 else style.background,
                      parts[2] if len(parts) > 2 else style.captions, parts[3] if len(parts) > 3 else style.transition,
                      style.seed)
    engine = select_engine(settings, tts)

    out_dir = paths.out / video_id
    work = out_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    v = settings["video"]
    tl = build_timeline(script, engine, v["fps"], scene_gap=float(settings["voice"].get("gap_between_scenes", 0.12)),
                        words_per_chunk=int(settings["captions"].get("max_words_per_chunk", 3)))
    comp = Compositor(tl, style, pool, settings["channel"]["name"])
    cv2.imwrite(str(out_dir / "preview.jpg"), cv2.cvtColor(comp.frame(0), cv2.COLOR_RGB2BGR),
                [cv2.IMWRITE_JPEG_QUALITY, 90])
    contact_sheet(comp, out_dir / "contact_sheet.jpg")

    scene_files = render_scenes(comp, work, crf=int(v["crf"]), preset=v["preset"])
    silent = concat(scene_files, work / "video_noaudio.mp4")
    seed_int = rng.randrange(1 << 30)
    settings = {**settings, "_music_dir": str(paths.music)}
    stems = build_stems(tl.scenes, tl.duration, settings, seed_int, work)
    master(stems, work / "audio.m4a", float(settings["qc"]["target_lufs"]), total_seconds=tl.duration)
    final = mux(silent, work / "audio.m4a", out_dir / "video.mp4")

    (out_dir / "captions.srt").write_text(to_srt(tl.chunks), encoding="utf-8")
    meta = build_metadata(script, pool, settings)
    (out_dir / "script.json").write_text(json.dumps(script.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    qc = run_qc(final, tl, script_issues, engine.production_quality, settings)
    (out_dir / "qc.json").write_text(json.dumps(qc, indent=2), encoding="utf-8")

    elapsed = round(time.time() - started, 1)
    record = {
        "id": video_id, "created_at": now_iso(), "status": "awaiting_review" if qc["passed"] else "qc_failed",
        "format": script.format, "title": script.title, "hook": script.scenes[0].narration,
        "hook_pattern": script.hook_pattern, "narration": script.narration, "fact_ids": script.fact_ids,
        "provider": script.provider, "voice": engine.name, "style": style.to_dict(), "music": stems["music"],
        "duration": qc["duration"], "qc": {"passed": qc["passed"], "errors": qc["errors"],
                                            "warnings": qc["warnings"]},
        "render_seconds": elapsed, "writer_log": trail, "youtube": {}, "tiktok": {},
    }
    (out_dir / "record.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    if register:
        registry.add(record)
        registry.set_status(video_id, record["status"], note=f"QC {'passed' if qc['passed'] else 'failed'}")
        registry.save()
        usage.add("videos_created")
        usage.add("render_seconds", elapsed)
        usage.save()
    if not keep_work:
        shutil.rmtree(work, ignore_errors=True)
    return {"record": record, "dir": str(out_dir), "qc": qc, "metadata": meta, "script": script}
