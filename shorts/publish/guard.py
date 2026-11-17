"""The single gate every upload must pass. Defaults block everything."""
from __future__ import annotations

from ..config import get
from ..usage import Usage


def can_publish(record: dict, settings: dict, platform: str, approved: bool, usage: Usage | None = None,
                uploads_today: int = 0) -> tuple[bool, str]:
    stage = int(settings.get("stage", 2))
    if stage < 3:
        return False, f"stage is {stage}: publishing starts at stage 3 (config/settings.yaml)"
    if not get(settings, "publishing.enabled", False):
        return False, "publishing.enabled is false"
    if not get(settings, f"publishing.{platform}.enabled", False):
        return False, f"publishing.{platform}.enabled is false"
    if not record.get("qc", {}).get("passed"):
        return False, "video did not pass quality control"
    if record.get("voice") != "kokoro":
        return False, f"voice '{record.get('voice')}' is a test voice; only Kokoro videos can be published"
    if record.get("status") in ("rejected", "published"):
        return False, f"video is already {record['status']}"
    needs_approval = stage == 3 or get(settings, "publishing.require_approval", True)
    if needs_approval and not approved:
        return False, "waiting for your approval (add the 'approved' label to the review issue)"
    cap = int(get(settings, "schedule.max_videos_per_day", 2))
    if uploads_today >= cap:
        return False, f"daily upload cap reached ({cap})"
    if usage and platform == "youtube" and not usage.allows(settings, "youtube_uploads", "youtube_uploads_per_day"):
        return False, "YouTube upload quota for today is used up"
    return True, "ok"
