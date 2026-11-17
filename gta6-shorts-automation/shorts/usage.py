"""Free-tier usage monitor (data/usage.json).

Counts what the pipeline spends each day so it can slow down *before* a free
limit is hit, and so the dashboard can show how close you are.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .config import Paths, get, today

# YouTube Data API v3 costs (units in the shared 10,000/day bucket). Uploads have their
# own bucket of 100 calls/day since the June 2026 change, tracked as "youtube_uploads".
YOUTUBE_COSTS = {"videos.list": 1, "channels.list": 1, "playlistItems.list": 1, "videos.update": 50,
                 "captions.insert": 400, "search.list": 0}


class Usage:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else Paths().usage
        self.data: dict = {"days": {}, "months": {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            self.data.setdefault("days", {})
            self.data.setdefault("months", {})

    def _day(self, day: dt.date | None = None) -> dict:
        key = (day or today()).isoformat()
        return self.data["days"].setdefault(key, {})

    def add(self, metric: str, amount: float = 1, sub: str | None = None, day: dt.date | None = None) -> None:
        bucket = self._day(day)
        if sub:
            bucket.setdefault(metric, {})
            bucket[metric][sub] = bucket[metric].get(sub, 0) + amount
        else:
            bucket[metric] = round(bucket.get(metric, 0) + amount, 3)

    def youtube_call(self, method: str, calls: int = 1) -> None:
        if method == "videos.insert":
            self.add("youtube_uploads", calls)
        else:
            self.add("youtube_units", YOUTUBE_COSTS.get(method, 1) * calls)

    def set_month(self, metric: str, value: float, month: str | None = None) -> None:
        key = month or today().strftime("%Y-%m")
        self.data["months"].setdefault(key, {})[metric] = value

    def day_total(self, metric: str, day: dt.date | None = None) -> float:
        value = self.data["days"].get((day or today()).isoformat(), {}).get(metric, 0)
        return sum(value.values()) if isinstance(value, dict) else value

    def month_value(self, metric: str, month: str | None = None) -> float:
        return self.data["months"].get(month or today().strftime("%Y-%m"), {}).get(metric, 0)

    def prune(self, keep_days: int = 90) -> None:
        cutoff = (today() - dt.timedelta(days=keep_days)).isoformat()
        self.data["days"] = {k: v for k, v in self.data["days"].items() if k >= cutoff}

    def save(self) -> None:
        self.prune()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def meters(self, settings: dict, public_repo: bool = True) -> list[dict]:
        """Rows for the dashboard / report: name, used, limit, percent, status."""
        rows = [
            ("YouTube uploads today", self.day_total("youtube_uploads"), get(settings, "limits.youtube_uploads_per_day")),
            ("YouTube API units today", self.day_total("youtube_units"), get(settings, "limits.youtube_units_per_day")),
            ("AI writer requests today", self.day_total("llm_requests"), get(settings, "limits.llm_requests_per_day")),
        ]
        if not public_repo:
            rows.append(("Actions minutes this month", self.month_value("actions_minutes"),
                         get(settings, "limits.actions_minutes_per_month")))
        warn = float(get(settings, "limits.warn_at_percent", 70))
        out = []
        for name, used, limit in rows:
            pct = (100.0 * used / limit) if limit else 0.0
            status = "ok" if pct < warn else ("warn" if pct < 100 else "over")
            out.append({"name": name, "used": used, "limit": limit, "percent": round(pct, 1), "status": status})
        return out

    def allows(self, settings: dict, metric: str, limit_key: str, needed: float = 1) -> bool:
        limit = get(settings, f"limits.{limit_key}")
        return limit is None or self.day_total(metric) + needed <= limit
