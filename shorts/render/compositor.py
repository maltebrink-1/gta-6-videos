"""Motion-graphics compositor: draws every frame in numpy and streams it to FFmpeg.

Layout respects the Shorts/TikTok safe zones: nothing important in the top
~150 px (status/search icons), the bottom ~420 px (title, channel, music
ticker) or the right-hand button column.
"""
from __future__ import annotations

import math
import random
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ..models import Fact
from ..timeline import Timeline
from . import text as T
from .backgrounds import make_background
from .styles import BADGE_COLORS, Style, hex_rgb

W, H = 1080, 1920
PROGRESS_Y = 160
TAG_Y = 214
CAPTION_Y = 1300
SOURCE_Y = 1492
CONTENT_MAX_W = 900


def ease_out_cubic(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def ease_out_back(x: float, s: float = 1.9) -> float:
    x = min(max(x, 0.0), 1.0)
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


class Sprite:
    def __init__(self, rgba: np.ndarray):
        self.rgba = rgba
        self.a = rgba[..., 3:4].astype(np.float32) / 255.0
        self.pm = rgba[..., :3].astype(np.float32) * self.a
        self.h, self.w = rgba.shape[:2]
        self._cache: dict[int, Sprite] = {}

    def scaled(self, s: float) -> "Sprite":
        key = int(round(s * 100))
        if key == 100:
            return self
        if key not in self._cache:
            w, h = max(int(self.w * key / 100), 1), max(int(self.h * key / 100), 1)
            self._cache[key] = Sprite(cv2.resize(self.rgba, (w, h), interpolation=cv2.INTER_AREA
                                                 if key < 100 else cv2.INTER_LINEAR))
        return self._cache[key]


def blit(dst: np.ndarray, sp: Sprite, cx: float, cy: float, opacity: float = 1.0) -> None:
    """Alpha-composite a sprite centred at (cx, cy) onto an RGB uint8 frame, in place."""
    if opacity <= 0.01:
        return
    x, y = int(round(cx - sp.w / 2)), int(round(cy - sp.h / 2))
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + sp.w, dst.shape[1]), min(y + sp.h, dst.shape[0])
    if x0 >= x1 or y0 >= y1:
        return
    sx, sy = x0 - x, y0 - y
    a = sp.a[sy:sy + (y1 - y0), sx:sx + (x1 - x0)]
    pm = sp.pm[sy:sy + (y1 - y0), sx:sx + (x1 - x0)]
    region = dst[y0:y1, x0:x1].astype(np.float32)
    if opacity < 0.999:
        a = a * opacity
        pm = pm * opacity
    region = pm + region * (1.0 - a)
    dst[y0:y1, x0:x1] = np.clip(region, 0, 255).astype(np.uint8)


@dataclass
class SceneAssets:
    headline: Sprite | None
    badge: Sprite | None
    big: Sprite | None
    source: Sprite | None
    arrow: Sprite | None


class Compositor:
    def __init__(self, timeline: Timeline, style: Style, pool: dict[str, Fact], channel_name: str,
                 headline_mode: str | None = None):
        self.tl = timeline
        self.style = style
        self.pal = style.palette
        self.fps = timeline.fps
        rng = random.Random(style.seed)
        self.headline_mode = headline_mode or rng.choice(["card", "bare"])
        self.bg = make_background(style.background, W, H, self.pal, style.seed, self.fps)
        self.assets = [self._scene_assets(ts.scene, pool, i == 0) for i, ts in enumerate(timeline.scenes)]
        self.captions = self._caption_sprites()
        self.tag = Sprite(T.pill(channel_name.upper(), self.pal["ink"], (255, 255, 255), size=30))
        self.particles = [dict(x=rng.uniform(0, W), y=rng.uniform(0, H), v=rng.uniform(25, 90),
                               amp=rng.uniform(8, 30), ph=rng.uniform(0, 6.28), r=rng.choice([2, 2, 3, 3, 4, 5]),
                               c=self.pal["accent"] if rng.random() < 0.5 else (255, 255, 255),
                               dim=rng.uniform(0.35, 0.9)) for _ in range(30)]

    # ── asset preparation ────────────────────────────────────────────────────
    def _scene_assets(self, scene, pool: dict[str, Fact], is_hook: bool) -> SceneAssets:
        pal = self.pal
        headline = None
        if scene.on_screen:
            size_max = 132 if is_hook else 116
            max_lines = 3
            if scene.big:                      # leave room for the hero number above
                size_max, max_lines = min(size_max, 104), 2
            lines, f = T.fit(scene.on_screen.upper(), "bold", CONTENT_MAX_W - 90, max_lines, size_max, 56)
            if self.headline_mode == "card":
                block = T.text_block(lines, f, (255, 255, 255), shadow=6, shadow_color=(0, 0, 0))
                headline = Sprite(T.card(block, pal["ink"], alpha=175, radius=40, pad=30, border=pal["accent"]))
            else:
                block = T.text_block(lines, f, (255, 255, 255), stroke=10, stroke_fill=(0, 0, 0), shadow=14,
                                     shadow_color=pal["accent2"])
                headline = Sprite(block)
        badge = None
        if scene.badge:
            badge = Sprite(T.pill(scene.badge, hex_rgb(BADGE_COLORS[scene.badge]), size=44, icon=scene.badge))
        big = None
        if scene.big:
            size = 330 if len(scene.big) <= 3 else 230 if len(scene.big) <= 5 else 170
            f = T.font("bold", size)
            while T.text_width(scene.big, f) > CONTENT_MAX_W - 60 and size > 90:
                size -= 20
                f = T.font("bold", size)
            big = Sprite(T.gradient_text(scene.big, f, pal["accent"], pal["accent2"], stroke=12,
                                         stroke_fill=(10, 0, 20), glow=26, glow_color=pal["accent2"]))
        source = None
        names: list[str] = []
        for fid in scene.fact_ids:
            fact = pool.get(fid)
            if fact and fact.sources:
                name = fact.sources[0].name.split(" (")[0]
                if name not in names:
                    names.append(name)
        if names:
            label = "Source: " + " · ".join(names[:2])
            f = T.font("medium", 34)
            lines = T.wrap(label, f, 820)[:2]
            block = T.text_block(lines, f, (240, 240, 240))
            source = Sprite(T.card(block, (0, 0, 0), alpha=120, radius=22, pad=6))
        arrow = None
        if scene.kind == "cta":
            arrow = Sprite(self._arrow())
        return SceneAssets(headline, badge, big, source, arrow)

    def _arrow(self) -> np.ndarray:
        img = np.zeros((120, 160, 4), np.uint8)
        col = (*self.pal["accent"], 255)
        pts = np.array([[20, 30], [80, 90], [140, 30]], np.int32)
        cv2.polylines(img, [pts], False, (0, 0, 0, 255), 30, cv2.LINE_AA)
        cv2.polylines(img, [pts], False, col, 18, cv2.LINE_AA)
        return img

    def _caption_sprites(self) -> dict[tuple[int, int], Sprite]:
        f = T.font("bold", 86)
        out = {}
        for ci, chunk in enumerate(self.tl.chunks):
            words = [w.text for w in chunk["words"]]
            for wi in range(len(words)):
                img = T.caption_image(words, wi, self.style.captions, f, self.pal["accent"], self.pal["ink"], 840)
                out[(ci, wi)] = Sprite(img)
        return out

    # ── per-frame drawing ────────────────────────────────────────────────────
    def _particles(self, frame: np.ndarray, t: float) -> None:
        for p in self.particles:
            y = (p["y"] - p["v"] * t) % (H + 40) - 20
            x = p["x"] + p["amp"] * math.sin(t * 0.8 + p["ph"])
            c = tuple(int(ch * p["dim"]) for ch in p["c"])
            cv2.circle(frame, (int(x), int(y)), p["r"], c, -1, cv2.LINE_AA)

    def _progress(self, frame: np.ndarray, t: float) -> None:
        n = len(self.tl.scenes)
        gap, x0, x1 = 10, 60, W - 60
        seg = (x1 - x0 - gap * (n - 1)) / n
        for i, ts in enumerate(self.tl.scenes):
            sx = int(x0 + i * (seg + gap))
            ex = int(sx + seg)
            cv2.line(frame, (sx, PROGRESS_Y), (ex, PROGRESS_Y), (70, 70, 80), 8, cv2.LINE_AA)
            if t >= ts.end:
                fill = 1.0
            elif t <= ts.start:
                fill = 0.0
            else:
                fill = (t - ts.start) / max(ts.end - ts.start, 1e-6)
            if fill > 0:
                cv2.line(frame, (sx, PROGRESS_Y), (int(sx + (ex - sx) * fill), PROGRESS_Y),
                         self.pal["accent"], 8, cv2.LINE_AA)

    def _active_caption(self, t: float):
        for ci, c in enumerate(self.tl.chunks):
            if c["start"] <= t < c["end"]:
                active = 0
                for wi, w in enumerate(c["words"]):
                    if w.start <= t:
                        active = wi
                return ci, active, t - c["start"]
        return None

    def frame(self, f: int) -> np.ndarray:
        t = f / self.fps
        si = next(i for i, ts in enumerate(self.tl.scenes) if ts.start_frame <= f < ts.end_frame) \
            if f < self.tl.total_frames else len(self.tl.scenes) - 1
        ts = self.tl.scenes[si]
        lf = f - ts.start_frame
        lt = lf / self.fps
        a = self.assets[si]
        frame = self.bg.frame(t).copy()
        self._particles(frame, t)
        is_hook = si == 0
        trans = self.style.transition
        slide = int(150 * (1 - ease_out_cubic(lf / 8))) if (trans == "slide" and not is_hook and lf < 8) else 0

        # vertical layout: [big number] -> [badge] -> [headline], centred around y≈700
        head_h = a.headline.h if a.headline else 0
        badge_h = (a.badge.h + 18) if a.badge else 0
        big_h = (a.big.h - 90) if a.big else 0          # glow padding overlaps neighbours
        stack = big_h + badge_h + head_h
        top = max(290.0, min(700 - stack / 2, 1150 - stack))   # never run into the captions (~1170+)
        big_cy = top + big_h / 2
        badge_cy = top + big_h + badge_h / 2
        head_cy = top + big_h + badge_h + head_h / 2
        float_y = 6 * math.sin(t * 2.6)

        if a.headline:
            if is_hook:
                s = 1.0 + 0.06 * (1 - ease_out_cubic(lt / 0.6))
                op = 1.0
            else:
                s = 0.62 + 0.38 * ease_out_back(lt / 0.32)
                op = min(lt / 0.10, 1.0)
            blit(frame, a.headline.scaled(s), W / 2, head_cy + float_y + slide, op)
        if a.badge:
            k = 1.0 if is_hook else ease_out_back((lt - 0.06) / 0.30)
            bx = W / 2 - (1 - k) * 700
            blit(frame, a.badge, bx, badge_cy + slide + float_y,
                 1.0 if is_hook else min(max((lt - 0.06) / 0.1, 0), 1))
        if a.big:
            if is_hook:
                s = 1.0 + 0.03 * math.sin(t * 5)
                op = 1.0
            else:
                s = 1.0 + 0.6 * (1 - ease_out_cubic(lt / 0.22)) + 0.02 * math.sin(t * 5)
                op = min(lt / 0.08, 1.0)
            blit(frame, a.big.scaled(s), W / 2, big_cy + slide, op)
        if a.arrow:
            bounce = 18 * abs(math.sin(t * 4.2))
            blit(frame, a.arrow, W / 2, head_cy + head_h / 2 + 110 + bounce, min(lt / 0.2, 1.0))
        if a.source:
            blit(frame, a.source, W / 2, SOURCE_Y, 1.0 if is_hook else min(max((lt - 0.15) / 0.2, 0), 1))

        cap = self._active_caption(t)
        if cap:
            ci, wi, age = cap
            sp = self.captions[(ci, wi)]
            s = 0.86 + 0.14 * ease_out_back(age / 0.10) if age < 0.10 else 1.0
            blit(frame, sp.scaled(s), W / 2, CAPTION_Y)

        blit(frame, self.tag, 60 + self.tag.w / 2, TAG_Y)
        self._progress(frame, t)

        if not is_hook and lf < 8:
            frame = self._transition(frame, trans, lf)
        return frame

    def _transition(self, frame: np.ndarray, kind: str, lf: int) -> np.ndarray:
        if kind == "flash" and lf < 6:
            alpha = 0.55 * (1 - lf / 6)
            return np.clip(frame.astype(np.float32) * (1 - alpha) + 255 * alpha, 0, 255).astype(np.uint8)
        if kind == "punch" and lf < 7:
            s = 1.0 + 0.10 * (1 - ease_out_cubic(lf / 7))
            cw, ch = int(W / s), int(H / s)
            x0, y0 = (W - cw) // 2, (H - ch) // 2
            return cv2.resize(frame[y0:y0 + ch, x0:x0 + cw], (W, H), interpolation=cv2.INTER_LINEAR)
        if kind == "glitch" and lf < 5:
            dx = int(24 * (1 - lf / 5)) + 2
            out = frame.copy()
            out[:, dx:, 0] = frame[:, :-dx, 0]
            out[:, :-dx, 2] = frame[:, dx:, 2]
            rng = random.Random(lf)
            for _ in range(4):
                y = rng.randrange(0, H - 80)
                hgt = rng.randrange(20, 80)
                off = rng.randrange(-40, 40)
                out[y:y + hgt] = np.roll(out[y:y + hgt], off, axis=1)
            return out
        return frame


# ── encoding ────────────────────────────────────────────────────────────────
def _encoder_cmd(path: Path, fps: int, crf: int, preset: str) -> list[str]:
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
            "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-profile:v", "high", "-level:v", "4.2",
            "-g", str(fps * 2), "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-color_range", "tv", "-an", str(path)]


def render_scenes(comp: Compositor, workdir: Path, crf: int = 19, preset: str = "veryfast") -> list[Path]:
    """One encoded file per scene (identical settings), written to a temp name then renamed."""
    files = []
    for ts in comp.tl.scenes:
        final = workdir / f"scene_{ts.index:02d}.mp4"
        tmp = workdir / f"scene_{ts.index:02d}.tmp.mp4"
        proc = subprocess.Popen(_encoder_cmd(tmp, comp.fps, crf, preset), stdin=subprocess.PIPE)
        assert proc.stdin is not None
        try:
            for f in range(ts.start_frame, ts.end_frame):
                proc.stdin.write(comp.frame(f).tobytes())
        finally:
            proc.stdin.close()
            code = proc.wait()
        if code != 0:
            raise RuntimeError(f"ffmpeg failed on scene {ts.index}")
        tmp.replace(final)
        files.append(final)
    return files


def concat(files: list[Path], out: Path) -> Path:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in files), encoding="utf-8")
    tmp = out.with_name(out.stem + ".tmp.mp4")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(tmp)], check=True)
    tmp.replace(out)
    return out


def mux(video: Path, audio: Path, out: Path) -> Path:
    tmp = out.with_name(out.stem + ".tmp.mp4")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-i", str(audio),
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "copy", "-shortest",
                    "-movflags", "+faststart", str(tmp)], check=True)
    tmp.replace(out)
    return out


def save_still(comp: Compositor, frame_index: int, path: Path, quality: int = 92) -> Path:
    img = comp.frame(frame_index)
    cv2.imwrite(str(path), cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, quality])
    return path
