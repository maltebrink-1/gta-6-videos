"""Markdown for the GitHub review issue that is opened for every new video."""
from __future__ import annotations

import json
from pathlib import Path

from .facts import load_facts, usable_facts
from .config import Paths, today

ICON = {True: "✅", False: "❌"}
BADGE_ICON = {"CONFIRMED": "🟢 CONFIRMED", "REPORTED": "🔵 REPORTED", "RUMOR": "🟠 RUMOR", "MYTH": "🔴 MYTH", "": ""}


def review_body(video_dir: str | Path, run_url: str = "", asset_base: str = "", stage: int = 2,
                run_id: str = "") -> str:
    d = Path(video_dir)
    record = json.loads((d / "record.json").read_text(encoding="utf-8"))
    qc = json.loads((d / "qc.json").read_text(encoding="utf-8"))
    meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
    script = json.loads((d / "script.json").read_text(encoding="utf-8"))
    paths = Paths()
    pool = usable_facts(load_facts(paths.facts), today())
    vid = record["id"]
    lines = [f"## {record['title']}", ""]
    if asset_base:
        lines += [f"![preview]({asset_base}/{vid}-contact.jpg)", "",
                  f"▶️ **[Watch the video]({asset_base}/{vid}.mp4)** (tap to play/download)", ""]
    if run_url:
        lines += [f"Files (video, captions, QC report) are also in the [workflow run]({run_url}) under Artifacts.", ""]
    lines += [f"**Format:** {record['format']} · **Length:** {qc['duration']}s · **Writer:** {record['provider']} · "
              f"**Voice:** {record['voice']} · **Style:** {record['style']['palette']} / "
              f"{record['style']['background']} · **Music:** {record['music'].get('mode')}", "",
              f"### Quality checks: {'PASSED' if qc['passed'] else 'FAILED'} "
              f"({qc['errors']} errors, {qc['warnings']} warnings)", ""]
    for c in qc["checks"]:
        icon = ICON[c["ok"]] if c["ok"] or c["level"] == "error" else "⚠️"
        lines.append(f"- {icon} **{c['name']}** – {c['detail']}")
    lines += ["", "### Script & fact check", "| # | Narration | On screen | Badge | Facts |", "|---|---|---|---|---|"]
    for i, s in enumerate(script["scenes"], 1):
        facts = ", ".join(f"`{f}`" for f in s["fact_ids"]) or "–"
        lines.append(f"| {i} | {s['narration'].replace('|', '/')} | {s['on_screen'].replace('|', '/')} | "
                     f"{BADGE_ICON.get(s['badge'], s['badge'])} | {facts} |")
    lines += ["", "<details><summary>Facts used and their sources</summary>", ""]
    for fid in dict.fromkeys(f for s in script["scenes"] for f in s["fact_ids"]):
        f = pool.get(fid)
        if f:
            srcs = "; ".join(f"[{s.name}]({s.url})" for s in f.sources)
            lines.append(f"- `{fid}` ({f.status}, verified {f.verified_on}): {f.claim} – {srcs}")
    lines += ["", "</details>", "", "<details><summary>Upload title & description</summary>", "",
              f"**Title:** {meta['title']}", "", "```", meta["description"], "```", "",
              f"**Tags:** {', '.join(meta['tags'])}", "", "</details>", "", "### What now?"]
    if stage >= 3:
        lines += ["- Add the label **`approved`** → it uploads (privacy from settings.yaml).",
                  "- Add **`rejected`** → it's discarded. A comment explaining why helps tune future videos."]
    else:
        lines += ["- **Stage 2 (testing): nothing is published.** Review it and leave a comment with feedback.",
                  "- Add **`rejected`** if it should never be published, close the issue when you're done."]
    lines += ["", f"<!-- video-id: {vid} -->", f"<!-- run-id: {run_id} -->"]
    return "\n".join(lines) + "\n"
