"""Plain data structures shared by every stage of the pipeline."""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from typing import Any

STATUSES = ("confirmed", "reported", "rumor", "debunked")


@dataclass
class Source:
    name: str
    url: str
    official: bool = False


@dataclass
class Fact:
    id: str
    claim: str
    status: str
    short: str = ""
    topics: list[str] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    verified_on: dt.date | None = None
    review_after_days: int = 30
    valid_until: dt.date | None = None
    rebuttal: str | None = None
    derived: bool = False  # computed at runtime (e.g. countdown days), never stored

    def is_stale(self, today: dt.date) -> bool:
        if self.derived:
            return False
        if self.verified_on is None:
            return True
        return (today - self.verified_on).days > self.review_after_days

    def is_expired(self, today: dt.date) -> bool:
        return self.valid_until is not None and today > self.valid_until

    def usable(self, today: dt.date) -> bool:
        return not self.is_stale(today) and not self.is_expired(today)

    def to_prompt(self) -> dict[str, Any]:
        return {"id": self.id, "status": self.status, "claim": self.claim, "short": self.short,
                **({"rebuttal": self.rebuttal} if self.rebuttal else {})}


@dataclass
class Scene:
    kind: str                    # hook | point | rumor | myth | number | cta
    narration: str               # what the voice says (and the captions show)
    on_screen: str = ""          # big headline text for this scene
    fact_ids: list[str] = field(default_factory=list)
    badge: str = ""              # CONFIRMED | REPORTED | RUMOR | MYTH | "" (auto-filled)
    big: str = ""                # optional hero number/word, e.g. "2" or "#1"

    @classmethod
    def from_dict(cls, d: dict) -> "Scene":
        return cls(kind=str(d.get("kind", "point")), narration=str(d.get("narration", "")).strip(),
                   on_screen=str(d.get("on_screen", "")).strip(), fact_ids=list(d.get("fact_ids") or []),
                   badge=str(d.get("badge", "") or ""), big=str(d.get("big", "") or ""))


@dataclass
class Script:
    id: str
    format: str
    title: str
    scenes: list[Scene]
    hook_pattern: str = ""       # template id of the hook (used for cooldowns)
    description: str = ""
    hashtags: list[str] = field(default_factory=list)
    provider: str = "template"

    @property
    def narration(self) -> str:
        return " ".join(s.narration for s in self.scenes)

    @property
    def fact_ids(self) -> list[str]:
        seen: list[str] = []
        for s in self.scenes:
            for f in s.fact_ids:
                if f not in seen:
                    seen.append(f)
        return seen

    def word_count(self) -> int:
        return len(self.narration.split())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Script":
        return cls(id=d["id"], format=d.get("format", "custom"), title=d.get("title", ""),
                   scenes=[Scene.from_dict(s) for s in d.get("scenes", [])],
                   hook_pattern=d.get("hook_pattern", ""), description=d.get("description", ""),
                   hashtags=list(d.get("hashtags") or []), provider=d.get("provider", "template"))


@dataclass
class Issue:
    level: str      # error | warning
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level.upper()}] {self.code}: {self.message}"


@dataclass
class Word:
    text: str          # as displayed in captions
    start: float
    end: float


@dataclass
class TimedScene:
    scene: Scene
    index: int
    start: float
    end: float
    start_frame: int
    end_frame: int
    words: list[Word] = field(default_factory=list)
    audio_offset: float = 0.0    # where this scene's narration starts on the master timeline

    @property
    def duration(self) -> float:
        return self.end - self.start
