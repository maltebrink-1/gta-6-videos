"""Builds site/data.json for the static dashboard (site/index.html)."""
from __future__ import annotations

import datetime as dt
import json
import random
from collections import defaultdict
from pathlib import Path

from .analytics.collect import load_snapshots
from .config import Paths, get, now_iso, today
from .registry import Registry
from .usage import Usage


def _iso_week(d: dt.date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _weekly(daily: list[dict]) -> list[dict]:
    """Monday–Sunday totals; only complete weeks plus the current week (flagged partial)."""
    weeks: dict[str, dict] = {}
    for row in daily:
        d = dt.date.fromisoformat(row["date"])
        key = _iso_week(d)
        wk = weeks.setdefault(key, {"week": key, "start": (d - dt.timedelta(days=d.weekday())).isoformat(),
                                    "days": 0, "views": 0, "likes": 0, "comments": 0, "subs": 0, "created": 0,
                                    "published": 0})
        wk["days"] += 1
        for k in ("views", "likes", "comments", "subs", "created", "published"):
            wk[k] += row.get(k, 0) or 0
    out = list(weeks.values())
    current = _iso_week(today())
    out = [w for w in out if w["days"] == 7 or w["week"] == current]
    for w in out:
        w["partial"] = w["days"] < 7
    return out[-8:]


def build_data(settings: dict, paths: Paths | None = None, public_repo: bool = True) -> dict:
    paths = paths or Paths()
    reg = Registry(paths.registry)
    usage = Usage(paths.usage)
    snaps = load_snapshots(paths)
    latest = snaps[-1] if snaps else {}
    yt = latest.get("youtube", {})
    vstats = yt.get("videos", {}) if yt.get("connected") else {}

    end = today()
    days = [(end - dt.timedelta(days=i)).isoformat() for i in range(55, -1, -1)]   # 8 weeks for the weekly chart
    daily = {d: {"date": d, "views": 0, "likes": 0, "comments": 0, "subs": 0, "created": 0, "published": 0}
             for d in days}
    for v in reg.videos:
        d = str(v.get("created_at", ""))[:10]
        if d in daily:
            daily[d]["created"] += 1
        p = str(v.get("youtube", {}).get("published_at", ""))[:10]
        if p in daily:
            daily[p]["published"] += 1
    analytics_rows = yt.get("daily") or []
    if analytics_rows:
        for row in analytics_rows:
            d = row.get("day")
            if d in daily:
                daily[d].update(views=int(row.get("views", 0)), likes=int(row.get("likes", 0)),
                                comments=int(row.get("comments", 0)),
                                subs=int(row.get("subscribersGained", 0)) - int(row.get("subscribersLost", 0)))
    else:  # fall back to day-over-day deltas of per-video lifetime stats
        prev_totals = None
        for s in snaps:
            vids = s.get("youtube", {}).get("videos", {}) or {}
            totals = {k: sum(int(x.get(k, 0)) for x in vids.values()) for k in ("views", "likes", "comments")}
            if prev_totals is not None and s["date"] in daily:
                for k in totals:
                    daily[s["date"]][k] = max(totals[k] - prev_totals[k], 0)
            prev_totals = totals

    top = []
    for v in reg.published():
        vid = v.get("youtube", {}).get("id")
        st = vstats.get(vid, {}) if vid else {}
        top.append({"id": v["id"], "title": v.get("title"), "url": v.get("youtube", {}).get("url"),
                    "format": v.get("format"), "published_at": v.get("youtube", {}).get("published_at"),
                    "views": st.get("views", 0), "likes": st.get("likes", 0), "comments": st.get("comments", 0)})
    top.sort(key=lambda x: x["views"], reverse=True)

    week_ago = (end - dt.timedelta(days=7)).isoformat()
    channel = yt.get("channel", {}) if yt.get("connected") else {}
    data = {
        "generated_at": now_iso(), "demo": False,
        "channel": {"name": settings["channel"]["name"], "handle": settings["channel"].get("handle"),
                    "youtube_url": f"https://www.youtube.com/channel/{channel['channel_id']}"
                    if channel.get("channel_id") else None},
        "stage": settings.get("stage"), "publishing_enabled": bool(get(settings, "publishing.enabled")),
        "platforms": {
            "youtube": {"connected": bool(yt.get("connected")),
                        "note": "Connected" if yt.get("connected") else "Not connected yet (Stage 3)"},
            "tiktok": {"connected": bool(latest.get("tiktok", {}).get("connected")),
                       "note": "Connected" if latest.get("tiktok", {}).get("connected")
                       else "Waiting for TikTok API approval"}},
        "totals": {
            "created": len(reg.videos), "published": len(reg.published()),
            "views": sum(x["views"] for x in top), "likes": sum(x["likes"] for x in top),
            "comments": sum(x["comments"] for x in top),
            "subscribers": channel.get("subscribers"),
            "subs_gained_30d": sum(d["subs"] for d in list(daily.values())[-30:]),
            "tiktok_followers": latest.get("tiktok", {}).get("user", {}).get("follower_count"),
        },
        "daily": list(daily.values())[-30:],
        "weekly": _weekly(list(daily.values())),
        "top_videos": top[:10],
        "recent": [{"id": v["id"], "title": v.get("title"), "status": v.get("status"), "format": v.get("format"),
                    "created_at": v.get("created_at"), "duration": v.get("duration"),
                    "qc_passed": v.get("qc", {}).get("passed")} for v in reg.videos[-12:]][::-1],
        "pipeline": {
            "awaiting_review": sum(1 for v in reg.videos if v.get("status") == "awaiting_review"),
            "qc_failed_7d": sum(1 for v in reg.videos if v.get("status") == "qc_failed"
                                and str(v.get("created_at", "")) >= week_ago),
            "rejected": sum(1 for v in reg.videos if v.get("status") == "rejected"),
            "last_created": reg.videos[-1]["created_at"] if reg.videos else None},
        "usage": usage.meters(settings, public_repo=public_repo),
    }
    return data


def demo_data(settings: dict, seed: int = 7) -> dict:
    """Realistic fake numbers so you can see the dashboard before anything is published."""
    rng = random.Random(seed)
    end = today()
    daily, subs_total = [], 0
    formats = ["countdown", "top3", "region_spotlight", "confirmed_vs_rumor", "by_the_numbers", "myth_buster"]
    titles = ["GTA 6 in 2 days: what's actually confirmed", "3 facts about GTA 6's trailers",
              "GTA 6: Port Gellhorn explained", "GTA 6: confirmed vs rumor", "GTA 6 by the numbers",
              "This GTA 6 myth needs to stop", "Meet Grassrivers in GTA 6", "3 things about GTA 6's price you missed",
              "Where are you going first in GTA 6?", "Vice City 2002 vs GTA 6's Leonida"]
    for i in range(55, -1, -1):
        d = end - dt.timedelta(days=i)
        growth = 1 + max(29 - i, -26) * 0.06 + 0.6
        views = int(rng.uniform(600, 1800) * growth * (2.4 if rng.random() < 0.12 else 1))
        subs = int(views * rng.uniform(0.004, 0.011))
        subs_total += subs
        created = rng.choice([1, 1, 2])
        daily.append({"date": d.isoformat(), "views": views, "likes": int(views * rng.uniform(0.035, 0.06)),
                      "comments": int(views * rng.uniform(0.002, 0.006)), "subs": subs, "created": created,
                      "published": created if rng.random() < 0.85 else created - 1})
    top = []
    for i, t in enumerate(titles):
        v = int(rng.uniform(2_000, 48_000) / (1 + i * 0.35))
        top.append({"id": f"demo-{i}", "title": t, "url": None, "format": formats[i % len(formats)],
                    "published_at": (end - dt.timedelta(days=rng.randint(1, 28))).isoformat(),
                    "views": v, "likes": int(v * 0.05), "comments": int(v * 0.004)})
    top.sort(key=lambda x: x["views"], reverse=True)
    statuses = ["published", "published", "awaiting_review", "published", "qc_failed", "published"]
    recent = [{"id": f"{(end - dt.timedelta(days=i // 2)).isoformat()}-0{1 + i % 2}", "title": titles[i % 10],
               "status": statuses[i % len(statuses)], "format": formats[i % len(formats)],
               "created_at": (end - dt.timedelta(days=i // 2)).isoformat() + "T07:31:00+00:00",
               "duration": round(rng.uniform(22, 48), 1), "qc_passed": statuses[i % len(statuses)] != "qc_failed"}
              for i in range(12)]
    return {
        "generated_at": now_iso(), "demo": True,
        "channel": {"name": settings["channel"]["name"], "handle": settings["channel"].get("handle"),
                    "youtube_url": None},
        "stage": 4, "publishing_enabled": True,
        "platforms": {"youtube": {"connected": True, "note": "Demo"}, "tiktok": {"connected": False,
                                                                              "note": "Waiting for API approval"}},
        "totals": {"created": sum(d["created"] for d in daily), "published": sum(d["published"] for d in daily),
                   "views": sum(d["views"] for d in daily), "likes": sum(d["likes"] for d in daily),
                   "comments": sum(d["comments"] for d in daily), "subscribers": subs_total + 37,
                   "subs_gained_30d": sum(d["subs"] for d in daily[-30:]), "tiktok_followers": None},
        "daily": daily[-30:], "weekly": _weekly(daily), "top_videos": top[:10], "recent": recent,
        "pipeline": {"awaiting_review": 1, "qc_failed_7d": 1, "rejected": 0, "last_created": recent[0]["created_at"]},
        "usage": [{"name": "YouTube uploads today", "used": 1, "limit": 100, "percent": 1.0, "status": "ok"},
                  {"name": "YouTube API units today", "used": 23, "limit": 10000, "percent": 0.2, "status": "ok"},
                  {"name": "AI writer requests today", "used": 3, "limit": 40, "percent": 7.5, "status": "ok"}],
    }


def write_site(data: dict, out_dir: str | Path, paths: Paths | None = None) -> Path:
    paths = paths or Paths()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "data.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    src = paths.site / "index.html"
    if out.resolve() != paths.site.resolve():
        (out / "index.html").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return out
