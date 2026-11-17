"""Daily statistics snapshot (data/stats/YYYY-MM-DD.json)."""
from __future__ import annotations

import datetime as dt
import json
import logging

from ..config import Paths, now_iso, today
from ..registry import Registry
from ..usage import Usage

log = logging.getLogger(__name__)


def collect(paths: Paths | None = None) -> dict:
    paths = paths or Paths()
    registry = Registry(paths.registry)
    usage = Usage(paths.usage)
    snap: dict = {"date": today().isoformat(), "collected_at": now_iso(),
                  "youtube": {"connected": False}, "tiktok": {"connected": False}}
    try:
        from ..publish.youtube import YouTubeClient, YouTubeNotConfigured
        try:
            yt = YouTubeClient(usage=usage)
            ids = [v["youtube"]["id"] for v in registry.videos if v.get("youtube", {}).get("id")]
            end = today() - dt.timedelta(days=1)
            start = end - dt.timedelta(days=29)
            snap["youtube"] = {"connected": True, "channel": yt.channel_stats(),
                               "videos": yt.video_stats(ids) if ids else {}}
            try:
                snap["youtube"]["daily"] = yt.daily_analytics(start.isoformat(), end.isoformat())
            except Exception as exc:  # Analytics API not enabled / not authorised yet
                snap["youtube"]["daily_error"] = str(exc)[:200]
        except YouTubeNotConfigured as exc:
            snap["youtube"]["reason"] = str(exc)
    except Exception as exc:
        snap["youtube"] = {"connected": False, "error": str(exc)[:300]}
        log.warning("YouTube stats failed: %s", exc)
    try:
        from ..publish.tiktok import TikTokClient, TikTokNotConfigured
        try:
            snap["tiktok"] = {"connected": True, "user": TikTokClient().stats()}
        except TikTokNotConfigured as exc:
            snap["tiktok"]["reason"] = str(exc)
    except Exception as exc:
        snap["tiktok"] = {"connected": False, "error": str(exc)[:300]}
    paths.stats.mkdir(parents=True, exist_ok=True)
    (paths.stats / f"{snap['date']}.json").write_text(json.dumps(snap, indent=2), encoding="utf-8")
    usage.save()
    return snap


def load_snapshots(paths: Paths | None = None, days: int = 120) -> list[dict]:
    paths = paths or Paths()
    files = sorted(paths.stats.glob("*.json"))[-days:]
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]
