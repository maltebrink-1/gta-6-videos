"""data/videos.json – the record of every video the system has made."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Paths, now_iso

# Lifecycle: created -> qc_failed | awaiting_review -> approved | rejected -> published
STATUSES = ("created", "qc_failed", "awaiting_review", "approved", "rejected", "published", "publish_failed")


class Registry:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else Paths().registry
        self.videos: list[dict[str, Any]] = []
        if self.path.exists():
            self.videos = json.loads(self.path.read_text(encoding="utf-8")).get("videos", [])

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"videos": self.videos}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def get(self, video_id: str) -> dict[str, Any] | None:
        return next((v for v in self.videos if v["id"] == video_id), None)

    def add(self, record: dict[str, Any]) -> None:
        if self.get(record["id"]):
            raise ValueError(f"video {record['id']} already registered")
        record.setdefault("created_at", now_iso())
        record.setdefault("events", [])
        self.videos.append(record)

    def set_status(self, video_id: str, status: str, note: str = "", **fields: Any) -> dict[str, Any]:
        if status not in STATUSES:
            raise ValueError(f"unknown status {status}")
        rec = self.get(video_id)
        if rec is None:
            raise KeyError(video_id)
        rec["status"] = status
        rec.update(fields)
        rec.setdefault("events", []).append({"at": now_iso(), "status": status, "note": note})
        return rec

    def history(self, window: int = 60) -> list[dict[str, Any]]:
        """Recent scripts for originality checks (excludes rejected/failed ones)."""
        usable = [v for v in self.videos if v.get("status") not in ("qc_failed", "rejected")]
        return usable[-window:]

    def published(self) -> list[dict[str, Any]]:
        return [v for v in self.videos if v.get("status") == "published"]

    def created_on(self, date_iso: str) -> list[dict[str, Any]]:
        return [v for v in self.videos if str(v.get("created_at", "")).startswith(date_iso)]
