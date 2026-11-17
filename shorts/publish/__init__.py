"""Publishing entry point used by the publish workflow (and Stage 4 automation)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ..config import Paths, get, now_iso, today
from ..registry import Registry
from ..usage import Usage
from .guard import can_publish

log = logging.getLogger(__name__)


def publish_video(video_id: str, platform: str, approved: bool, settings: dict, paths: Paths | None = None) -> dict:
    paths = paths or Paths()
    registry = Registry(paths.registry)
    usage = Usage(paths.usage)
    record = registry.get(video_id)
    if record is None:
        return {"ok": False, "reason": f"unknown video {video_id}"}
    folder = paths.out / video_id
    video = folder / "video.mp4"
    meta_file = folder / "metadata.json"
    if not video.exists() or not meta_file.exists():
        return {"ok": False, "reason": f"video files not found in {folder} (download the run artifact first)"}
    uploads_today = sum(1 for v in registry.videos
                        if str(v.get(platform, {}).get("published_at", "")).startswith(today().isoformat()))
    ok, reason = can_publish(record, settings, platform, approved, usage, uploads_today)
    if not ok:
        return {"ok": False, "reason": reason}
    meta = json.loads(meta_file.read_text(encoding="utf-8"))

    if get(settings, "publishing.dry_run", True):
        msg = f"DRY RUN – would upload {video_id} to {platform} as '{meta['title']}'"
        log.info(msg)
        return {"ok": True, "dry_run": True, "reason": msg}

    if platform == "youtube":
        from .youtube import YouTubeClient
        yt = YouTubeClient(usage=usage)
        cfg = settings["publishing"]["youtube"]
        result = yt.upload(video, meta, privacy=cfg.get("privacy", "private"),
                           synthetic=bool(cfg.get("contains_synthetic_media", False)),
                           made_for_kids=bool(cfg.get("made_for_kids", False)))
        vid = result.get("id")
        record["youtube"] = {"id": vid, "url": f"https://www.youtube.com/shorts/{vid}",
                             "privacy": result.get("status", {}).get("privacyStatus"), "published_at": now_iso()}
    elif platform == "tiktok":
        from .tiktok import TikTokClient
        tt = TikTokClient()
        cfg = settings["publishing"]["tiktok"]
        result = tt.upload(video, meta["title"], mode=cfg.get("mode", "inbox"), is_aigc=bool(cfg.get("is_aigc", True)))
        record["tiktok"] = {"publish_id": result.get("publish_id"), "status": result.get("status"),
                            "published_at": now_iso(), "rotated_refresh_token": bool(tt.new_refresh_token)}
    else:
        return {"ok": False, "reason": f"unknown platform {platform}"}

    registry.set_status(video_id, "published", note=f"{platform} upload")
    registry.save()
    usage.save()
    return {"ok": True, "dry_run": False, "platform": platform, "result": record.get(platform)}
