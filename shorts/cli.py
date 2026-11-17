"""Command line: `python -m shorts <command>` (the GitHub workflows call these)."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from .config import Paths, load_settings, today


def _gh_output(**values: str) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            for k, v in values.items():
                fh.write(f"{k}={v}\n")


def cmd_create(a, settings, paths) -> int:
    from .pipeline import DailyCapReached, create_video
    if a.provider:
        settings["writer"]["providers"] = a.provider.split(",")
    made, failed = [], []
    for i in range(a.count or settings["schedule"]["videos_per_run"]):
        try:
            res = create_video(settings, paths, tts=a.tts, fmt=a.format, seed=a.seed and f"{a.seed}-{i}",
                               register=not a.no_register, keep_work=a.keep_work, style_spec=a.style)
        except DailyCapReached as exc:
            print(f"Stopping: {exc}")
            break
        rec = res["record"]
        (made if rec["qc"]["passed"] else failed).append(rec["id"])
        print(json.dumps({"id": rec["id"], "title": rec["title"], "format": rec["format"], "status": rec["status"],
                          "duration": rec["duration"], "writer": rec["provider"], "voice": rec["voice"],
                          "dir": res["dir"]}, ensure_ascii=False))
        for c in res["qc"]["checks"]:
            if not c["ok"]:
                print(f"  {c['level'].upper()}: {c['name']} – {c['detail']}")
    _gh_output(videos=",".join(made + failed), passed=",".join(made), failed=",".join(failed))
    return 0   # a video failing QC is a normal outcome (it gets a 'qc-failed' review issue), not a crash


def cmd_review_body(a, settings, paths) -> int:
    from .review import review_body
    print(review_body(paths.out / a.video_id, a.run_url or "", a.asset_base or "", int(settings["stage"]),
                      a.run_id or ""))
    return 0


def cmd_publish(a, settings, paths) -> int:
    from .publish import publish_video
    res = publish_video(a.video_id, a.platform, a.approved, settings, paths)
    print(json.dumps(res, ensure_ascii=False))
    _gh_output(published="true" if res.get("ok") and not res.get("dry_run") else "false",
               reason=str(res.get("reason", "")).replace("\n", " "))
    return 0


def cmd_mark(a, settings, paths) -> int:
    from .registry import Registry
    reg = Registry(paths.registry)
    if not reg.get(a.video_id):
        print(f"unknown video {a.video_id}")
        return 1
    reg.set_status(a.video_id, a.status, note=a.note or "")
    reg.save()
    print(f"{a.video_id} -> {a.status}")
    return 0


def cmd_stats(a, settings, paths) -> int:
    from .analytics.collect import collect
    snap = collect(paths)
    print(json.dumps({"youtube": snap["youtube"].get("connected"), "tiktok": snap["tiktok"].get("connected")}))
    return 0


def cmd_report(a, settings, paths) -> int:
    from .analytics.report import daily_report, save_report
    text = daily_report(settings, paths, public_repo=not a.private_repo)
    if a.save:
        print(f"saved {save_report(text, paths)}", file=sys.stderr)
    print(text)
    return 0


def cmd_dashboard(a, settings, paths) -> int:
    from .dashboard import build_data, demo_data, write_site
    data = demo_data(settings) if a.demo else build_data(settings, paths, public_repo=not a.private_repo)
    out = write_site(data, a.out or paths.site, paths)
    print(f"dashboard written to {out}")
    return 0


def cmd_facts(a, settings, paths) -> int:
    from .facts import load_facts, usable_facts, validate_facts
    facts = load_facts(paths.facts)
    issues = validate_facts(facts, today())
    pool = usable_facts(facts, today())
    print(f"{len(facts)} facts, {len(pool)} usable today ({today()})")
    for i in issues:
        print(i)
    return 1 if any(i.level == "error" for i in issues) else 0


def cmd_discover(a, settings, paths) -> int:
    from .research import discover, review_issue_body
    new = discover(settings, paths)
    print(f"{len(new)} new candidate(s)", file=sys.stderr)
    if new and a.body_file:
        Path(a.body_file).write_text(review_issue_body(new), encoding="utf-8")
    _gh_output(new_candidates=str(len(new)))
    return 0


def cmd_apply_facts(a, settings, paths) -> int:
    from .research import apply_review
    added = apply_review(Path(a.issue_body).read_text(encoding="utf-8"), paths)
    print(f"added {len(added)} fact(s): {', '.join(added)}")
    _gh_output(added=",".join(added))
    return 0


def cmd_setup_voice(a, settings, paths) -> int:
    from .voice.engines import download_kokoro
    print(f"Kokoro model ready in {download_kokoro(a.dir)}")
    return 0


def cmd_usage(a, settings, paths) -> int:
    from .usage import Usage
    for m in Usage(paths.usage).meters(settings, public_repo=not a.private_repo):
        print(f"{m['status']:>4}  {m['name']}: {m['used']} / {m['limit']} ({m['percent']}%)")
    return 0


def cmd_styles(a, settings, paths) -> int:
    """Render the first frame of one script in several styles (quick visual check, no video)."""
    import random

    import cv2
    import numpy as np

    from .facts import load_facts, usable_facts
    from .render.compositor import Compositor
    from .render.styles import Style
    from .timeline import build_timeline
    from .topics import choose_plan
    from .voice.engines import FliteEngine
    from .writer import write_script
    settings["writer"]["providers"] = ["template"]
    facts = load_facts(paths.facts)
    pool = usable_facts(facts, today())
    plan = choose_plan(pool, [], today(), random.Random(1), forced_format=a.format)
    script, _, _ = write_script(plan, pool, facts, "styles", settings, [], today())
    tl = build_timeline(script, FliteEngine())
    combos = [("vice_sunset", "synth_grid", "pop"), ("night_neon", "aurora", "box"), ("ocean_drive", "skyline", "clean"),
              ("heatwave", "stripes", "pop"), ("everglade", "synth_grid", "box")]
    tiles = []
    for i, (pal, bg, cap) in enumerate(combos):
        comp = Compositor(tl, Style(pal, bg, cap, "flash", 100 + i), pool, settings["channel"]["name"],
                          headline_mode="card" if i % 2 == 0 else "bare")
        f = min(tl.scenes[1].start_frame + 20, tl.total_frames - 1)
        tiles.append(cv2.resize(comp.frame(f), (360, 640), interpolation=cv2.INTER_AREA))
    cv2.imwrite(a.out, cv2.cvtColor(np.concatenate(tiles, axis=1), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(f"wrote {a.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m shorts", description="GTA 6 Shorts automation")
    p.add_argument("--settings", help="path to settings.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="make new video(s): script → checks → voice → render → QC")
    c.add_argument("--count", type=int)
    c.add_argument("--format", help="force a format (countdown, top3, region_spotlight, ...)")
    c.add_argument("--tts", choices=["auto", "kokoro", "flite"])
    c.add_argument("--provider", help="override writer providers, e.g. template or groq,template")
    c.add_argument("--seed")
    c.add_argument("--no-register", action="store_true", help="don't record it in data/videos.json")
    c.add_argument("--keep-work", action="store_true")
    c.add_argument("--style", help="palette/background/captions/transition, e.g. vice_sunset/synth_grid/pop/flash")
    c.set_defaults(fn=cmd_create)

    c = sub.add_parser("review-body", help="markdown for a video's review issue")
    c.add_argument("--video-id", required=True)
    c.add_argument("--run-url")
    c.add_argument("--asset-base")
    c.add_argument("--run-id")
    c.set_defaults(fn=cmd_review_body)

    c = sub.add_parser("publish", help="upload a video (only if every gate allows it)")
    c.add_argument("--video-id", required=True)
    c.add_argument("--platform", choices=["youtube", "tiktok"], default="youtube")
    c.add_argument("--approved", action="store_true")
    c.set_defaults(fn=cmd_publish)

    c = sub.add_parser("mark", help="set a video's status (approved/rejected)")
    c.add_argument("--video-id", required=True)
    c.add_argument("--status", required=True, choices=["approved", "rejected", "awaiting_review"])
    c.add_argument("--note")
    c.set_defaults(fn=cmd_mark)

    sub.add_parser("stats", help="collect YouTube/TikTok statistics").set_defaults(fn=cmd_stats)
    c = sub.add_parser("report", help="daily performance report")
    c.add_argument("--save", action="store_true")
    c.add_argument("--private-repo", action="store_true")
    c.set_defaults(fn=cmd_report)
    c = sub.add_parser("dashboard", help="build the dashboard data")
    c.add_argument("--demo", action="store_true")
    c.add_argument("--out")
    c.add_argument("--private-repo", action="store_true")
    c.set_defaults(fn=cmd_dashboard)
    sub.add_parser("facts", help="validate data/facts.yaml").set_defaults(fn=cmd_facts)
    c = sub.add_parser("discover", help="find new GTA 6 headlines for fact review")
    c.add_argument("--body-file")
    c.set_defaults(fn=cmd_discover)
    c = sub.add_parser("apply-facts", help="apply ticked items from a fact-review issue")
    c.add_argument("--issue-body", required=True)
    c.set_defaults(fn=cmd_apply_facts)
    c = sub.add_parser("setup-voice", help="download the Kokoro voice model")
    c.add_argument("--dir")
    c.set_defaults(fn=cmd_setup_voice)
    c = sub.add_parser("usage", help="free-tier usage meters")
    c.add_argument("--private-repo", action="store_true")
    c.set_defaults(fn=cmd_usage)
    c = sub.add_parser("styles", help="preview frame in several visual styles")
    c.add_argument("--out", default="styles.jpg")
    c.add_argument("--format", default="countdown")
    c.set_defaults(fn=cmd_styles)

    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    settings = load_settings(a.settings)
    return a.fn(a, settings, Paths())


if __name__ == "__main__":
    sys.exit(main())
