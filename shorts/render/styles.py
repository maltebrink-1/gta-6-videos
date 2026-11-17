"""Visual styles. One is picked per video (seeded), never repeating the previous combo."""
from __future__ import annotations

import random
from dataclasses import dataclass


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


PALETTES: dict[str, dict[str, str]] = {
    "vice_sunset": {"top": "#1d0633", "mid": "#8e1a5e", "bottom": "#ff6b3d", "accent": "#ffd23f",
                    "accent2": "#ff3d9a", "grid": "#ff4fd8", "ink": "#1a0026"},
    "ocean_drive": {"top": "#03132a", "mid": "#064a66", "bottom": "#ff5fb7", "accent": "#2ef2d0",
                    "accent2": "#ff5fb7", "grid": "#2ef2d0", "ink": "#02101f"},
    "night_neon": {"top": "#04010d", "mid": "#1a0a3c", "bottom": "#4a12b0", "accent": "#ff2e93",
                   "accent2": "#49d8ff", "grid": "#49d8ff", "ink": "#06010f"},
    "everglade": {"top": "#020c08", "mid": "#0b3a2b", "bottom": "#1d7a52", "accent": "#d4ff3a",
                  "accent2": "#ffb703", "grid": "#d4ff3a", "ink": "#020c08"},
    "heatwave": {"top": "#140004", "mid": "#5c0a1c", "bottom": "#c2185b", "accent": "#ffc53d",
                 "accent2": "#ff4d6d", "grid": "#ff8a3d", "ink": "#140004"},
}

BADGE_COLORS = {"CONFIRMED": "#16c060", "REPORTED": "#3b82f6", "RUMOR": "#f59e0b", "MYTH": "#ef4444"}
BACKGROUNDS = ("synth_grid", "aurora", "skyline", "stripes")
CAPTION_STYLES = ("pop", "box", "clean")
TRANSITIONS = ("flash", "punch", "glitch", "slide")


@dataclass
class Style:
    palette_name: str
    background: str
    captions: str
    transition: str
    seed: int

    @property
    def palette(self) -> dict[str, tuple[int, int, int]]:
        return {k: hex_rgb(v) for k, v in PALETTES[self.palette_name].items()}

    def key(self) -> str:
        return f"{self.palette_name}/{self.background}/{self.captions}/{self.transition}"

    def to_dict(self) -> dict:
        return {"palette": self.palette_name, "background": self.background, "captions": self.captions,
                "transition": self.transition, "seed": self.seed}


def pick_style(rng: random.Random, recent: list[dict] | None = None, caption_pref: str = "auto",
               rumor_heavy: bool = False) -> Style:
    recent = recent or []
    last = recent[-1] if recent else {}
    palettes = [p for p in PALETTES if p != last.get("palette")]
    if rumor_heavy and "heatwave" in palettes and rng.random() < 0.5:
        palette = "heatwave"
    else:
        palette = rng.choice(palettes)
    backgrounds = [b for b in BACKGROUNDS if b != last.get("background")]
    captions = caption_pref if caption_pref in CAPTION_STYLES else rng.choice(CAPTION_STYLES)
    return Style(palette, rng.choice(backgrounds), captions, rng.choice(TRANSITIONS), rng.randrange(1 << 30))
