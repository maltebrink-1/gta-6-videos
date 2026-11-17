"""Settings loading and project paths."""
from __future__ import annotations

import copy
import datetime as dt
import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


class Paths:
    """All file locations in one place (relative to the repo root)."""

    def __init__(self, root: Path = ROOT):
        self.root = root
        self.config = root / "config"
        self.settings = self.config / "settings.yaml"
        self.sources = self.config / "sources.yaml"
        self.data = root / "data"
        self.facts = self.data / "facts.yaml"
        self.fact_candidates = self.data / "fact_candidates.json"
        self.registry = self.data / "videos.json"
        self.usage = self.data / "usage.json"
        self.stats = self.data / "stats"
        self.reports = self.data / "reports"
        self.assets = root / "assets"
        self.fonts = self.assets / "fonts"
        self.music = self.assets / "music"
        self.site = root / "site"
        self.out = Path(os.environ.get("SHORTS_OUT", root / "out"))
        self.models = Path(os.environ.get("SHORTS_MODELS", Path.home() / ".cache" / "gta6-shorts" / "models"))


DEFAULTS: dict[str, Any] = {
    "stage": 2,
    "channel": {"name": "Leonida Daily", "handle": "@yourchannel", "disclaimer": ""},
    "schedule": {"videos_per_run": 1, "max_videos_per_day": 2},
    "video": {"width": 1080, "height": 1920, "fps": 30, "min_seconds": 20, "max_seconds": 60,
              "crf": 19, "preset": "veryfast"},
    "voice": {"engine": "auto", "kokoro_voice": "af_bella", "speed": 1.1, "flite_voice": "slt",
              "gap_between_scenes": 0.12},
    "captions": {"max_words_per_chunk": 3, "style": "auto"},
    "music": {"mode": "procedural", "volume_db": -15},
    "writer": {"providers": ["template"], "temperature": 0.9, "claude_model": "",
               "groq_model": "llama-3.3-70b-versatile", "gemini_model": "gemini-2.5-flash",
               "max_attempts_per_provider": 2},
    "research": {"news_lookback_hours": 36, "require_human_approval_for_new_facts": True,
                 "auto_approve_official_sources": False},
    "originality": {"max_similarity": 0.35, "history_window": 60, "hook_cooldown": 20, "format_cooldown": 2},
    "qc": {"target_lufs": -14, "lufs_tolerance": 2.0, "max_true_peak_db": -1.0,
           "max_silence_seconds": 1.2, "max_black_seconds": 0.4},
    "publishing": {"enabled": False, "require_approval": True, "dry_run": True,
                   "youtube": {"enabled": False, "privacy": "private", "category_id": "20",
                               "contains_synthetic_media": False, "made_for_kids": False, "tags": []},
                   "tiktok": {"enabled": False, "mode": "inbox", "is_aigc": True}},
    "limits": {"youtube_uploads_per_day": 100, "youtube_units_per_day": 10000, "llm_requests_per_day": 40,
               "actions_minutes_per_month": 2000, "warn_at_percent": 70},
}


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_settings(path: str | Path | None = None) -> dict:
    p = Path(path) if path else Paths().settings
    data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    return deep_merge(DEFAULTS, data or {})


def get(settings: dict, dotted: str, default: Any = None) -> Any:
    node: Any = settings
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def secret(name: str) -> str | None:
    """Read a secret from the environment (GitHub Actions passes repo secrets this way)."""
    value = os.environ.get(name, "").strip()
    return value or None


def today() -> dt.date:
    """The pipeline's notion of 'today'. Override with SHORTS_TODAY=YYYY-MM-DD for tests/replays."""
    forced = os.environ.get("SHORTS_TODAY")
    if forced:
        return dt.date.fromisoformat(forced)
    return dt.datetime.now(dt.timezone.utc).date()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
