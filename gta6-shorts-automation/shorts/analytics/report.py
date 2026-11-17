"""Daily performance report (markdown) – saved to data/reports/ and posted as a GitHub issue."""
from __future__ import annotations

from ..config import Paths, today
from ..dashboard import build_data
from ..facts import load_facts, validate_facts


def _fmt(n) -> str:
    return "–" if n is None else f"{int(n):,}"


def daily_report(settings: dict, paths: Paths | None = None, public_repo: bool = True) -> str:
    paths = paths or Paths()
    data = build_data(settings, paths, public_repo)
    day = today()
    t = data["totals"]
    d = data["daily"]
    last1 = d[-2] if len(d) >= 2 else (d[-1] if d else {})   # yesterday = last complete day
    last7 = d[-7:]
    sums = lambda rows, k: sum(r.get(k, 0) for r in rows)  # noqa: E731
    lines = [f"# Daily report – {day.isoformat()}", "",
             f"**Stage {data['stage']}** · publishing {'ON' if data['publishing_enabled'] else 'off'} · "
             f"YouTube: {data['platforms']['youtube']['note']} · TikTok: {data['platforms']['tiktok']['note']}", "",
             "## Pipeline",
             f"- Videos created (all time): **{t['created']}** · published: **{t['published']}**",
             f"- Waiting for your review: **{data['pipeline']['awaiting_review']}** "
             f"(issues labelled `video-review`)",
             f"- Failed quality checks in the last 7 days: {data['pipeline']['qc_failed_7d']}", "",
             "## Audience", "| | Yesterday | Last 7 days | Last 30 days |", "|---|---:|---:|---:|"]
    for label, key in (("Views", "views"), ("Likes", "likes"), ("Comments", "comments"), ("Subscribers +/-", "subs")):
        lines.append(f"| {label} | {_fmt(last1.get(key))} | {_fmt(sums(last7, key))} | {_fmt(sums(d, key))} |")
    lines += ["", f"Subscribers now: **{_fmt(t['subscribers'])}** · TikTok followers: "
                  f"**{_fmt(t['tiktok_followers'])}**", "", "## Best videos"]
    if data["top_videos"]:
        for i, v in enumerate(data["top_videos"][:5], 1):
            title = f"[{v['title']}]({v['url']})" if v.get("url") else v["title"]
            lines.append(f"{i}. {title} – {_fmt(v['views'])} views · {_fmt(v['likes'])} likes · "
                         f"{_fmt(v['comments'])} comments")
    else:
        lines.append("_Nothing published yet._")
    lines += ["", "## Free-tier usage", "| Meter | Used | Limit | Status |", "|---|---:|---:|---|"]
    for m in data["usage"]:
        icon = {"ok": "🟢", "warn": "🟠", "over": "🔴"}[m["status"]]
        lines.append(f"| {m['name']} | {_fmt(m['used'])} | {_fmt(m['limit'])} | {icon} {m['percent']}% |")
    attention = []
    for issue in validate_facts(load_facts(paths.facts), day):
        if issue.code == "stale":
            attention.append(f"- Re-verify fact: {issue.message}")
    if data["pipeline"]["qc_failed_7d"]:
        attention.append("- Some videos failed QC – open their run logs to see which check failed.")
    lines += ["", "## Needs attention"] + (attention or ["- Nothing. 👍"])
    return "\n".join(lines) + "\n"


def save_report(text: str, paths: Paths | None = None) -> str:
    paths = paths or Paths()
    paths.reports.mkdir(parents=True, exist_ok=True)
    f = paths.reports / f"{today().isoformat()}.md"
    f.write_text(text, encoding="utf-8")
    return str(f)
