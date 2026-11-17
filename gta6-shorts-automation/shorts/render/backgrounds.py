"""Original animated backgrounds, generated from code (no stock or game footage).

Each background precomputes what it can, so producing a frame is cheap.
`frame(t)` returns an (H, W, 3) uint8 array that callers must not modify.
"""
from __future__ import annotations

import math
import random

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

RGB = tuple[int, int, int]


def gradient(h: int, w: int, stops: list[tuple[float, RGB]]) -> np.ndarray:
    ys = np.linspace(0, 1, h, dtype=np.float32)
    pos = np.array([s[0] for s in stops], np.float32)
    cols = np.array([s[1] for s in stops], np.float32)
    col = np.stack([np.interp(ys, pos, cols[:, c]) for c in range(3)], axis=1)
    return np.broadcast_to(col[:, None, :], (h, w, 3)).copy()


def mix(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))  # type: ignore[return-value]


def readability_profile(h: int) -> np.ndarray:
    """Per-row brightness multiplier: darker behind the headline and caption zones."""
    y = np.arange(h, dtype=np.float32) / h
    dark = 0.30 * np.exp(-((y - 0.33) / 0.13) ** 2) + 0.38 * np.exp(-((y - 0.67) / 0.09) ** 2)
    return (1.0 - dark).astype(np.float32)


def vignette(h: int, w: int, strength: float = 0.45) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 * 0.6 + ((yy - h / 2) / (h / 2)) ** 2 * 0.5)
    return np.clip(1.0 - strength * np.clip(d - 0.35, 0, None) ** 1.5, 0.35, 1.0).astype(np.float32)


def _stars(img: np.ndarray, rng: random.Random, n: int, y_max: int) -> None:
    h, w = img.shape[:2]
    for _ in range(n):
        x, y = rng.randrange(w), rng.randrange(max(y_max, 1))
        b = rng.uniform(0.35, 1.0)
        r = 1 if rng.random() < 0.8 else 2
        cv2.circle(img, (x, y), r, (255 * b, 255 * b, 255 * b), -1, cv2.LINE_AA)


def palm(draw: ImageDraw.ImageDraw, base: tuple[int, int], height: int, lean: float, color, rng: random.Random):
    """A palm tree silhouette: curved trunk + drooping fronds."""
    bx, by = base
    pts_l, pts_r = [], []
    top = (bx + lean * height, by - height)
    for i in range(21):
        t = i / 20
        x = bx + lean * height * (t ** 1.6)
        y = by - height * t
        half = max(height * 0.035 * (1 - t * 0.55), 4)
        pts_l.append((x - half, y))
        pts_r.append((x + half, y))
    draw.polygon(pts_l + pts_r[::-1], fill=color)
    n = 8
    for k in range(n):
        ang = -math.pi + k * (math.pi / (n - 1)) + rng.uniform(-0.15, 0.15)
        length = height * rng.uniform(0.38, 0.5)
        droop = height * rng.uniform(0.12, 0.22)
        spine = []
        for i in range(16):
            t = i / 15
            x = top[0] + math.cos(ang) * length * t
            y = top[1] + math.sin(ang) * length * t * 0.55 + droop * t * t
            spine.append((x, y))
        upper, lower = [], []
        for i, (x, y) in enumerate(spine):
            t = i / 15
            wdt = height * 0.045 * math.sin(math.pi * min(t * 1.15, 1.0)) + 1
            upper.append((x, y - wdt))
            lower.append((x, y + wdt))
        draw.polygon(upper + lower[::-1], fill=color)
    draw.ellipse([top[0] - height * 0.03, top[1] - height * 0.03, top[0] + height * 0.03,
                  top[1] + height * 0.03], fill=color)


class Background:
    def frame(self, t: float) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError


class SynthGrid(Background):
    """Retro sunset: striped sun, palms, perspective grid rolling toward the viewer."""

    def __init__(self, w: int, h: int, pal: dict[str, RGB], rng: random.Random, fps: int = 30, loop: int = 24):
        self.loop = loop
        self.fps = fps
        horizon = int(h * 0.58)
        sky = gradient(horizon, w, [(0, pal["top"]), (0.55, pal["mid"]), (1, pal["bottom"])])
        _stars(sky, rng, 140, int(horizon * 0.5))
        sky_img = Image.fromarray(np.clip(sky, 0, 255).astype(np.uint8))
        # sun with glow and cut stripes
        r = int(w * 0.30)
        cx, cy = w // 2, horizon - int(r * 0.35)
        glow = Image.new("L", (w, horizon), 0)
        ImageDraw.Draw(glow).ellipse([cx - r * 1.35, cy - r * 1.35, cx + r * 1.35, cy + r * 1.35], fill=150)
        glow = glow.filter(ImageFilter.GaussianBlur(70))
        sky_img = Image.composite(Image.new("RGB", (w, horizon), mix(pal["accent2"], pal["accent"], 0.4)),
                                  sky_img, glow)
        sun_mask = Image.new("L", (w, horizon), 0)
        sd = ImageDraw.Draw(sun_mask)
        sd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
        for i in range(7):
            yy = cy + int(r * (0.05 + i * 0.15))
            sd.rectangle([0, yy, w, yy + 4 + i * 4], fill=0)
        sun_grad = gradient(horizon, w, [(0, pal["accent"]), ((cy - r) / horizon, pal["accent"]),
                                         ((cy + r) / horizon, pal["accent2"]), (1, pal["accent2"])])
        sky_img = Image.composite(Image.fromarray(np.clip(sun_grad, 0, 255).astype(np.uint8)), sky_img, sun_mask)
        sky = np.asarray(sky_img, np.float32)

        ground_base = gradient(h - horizon, w, [(0, mix(pal["ink"], pal["mid"], 0.35)), (1, (0, 0, 0))])
        prof = readability_profile(h)[:, None, None]
        vig = vignette(h, w)[..., None]
        # palms layer (full frame, static)
        palms = Image.new("L", (w, h), 0)
        pd = ImageDraw.Draw(palms)
        palm(pd, (int(w * 0.06), horizon + 140), int(h * 0.36), 0.22, 255, rng)
        palm(pd, (int(w * 0.95), horizon + 180), int(h * 0.31), -0.25, 255, rng)
        if rng.random() < 0.6:
            palm(pd, (int(w * 0.83), horizon + 60), int(h * 0.22), -0.12, 255, rng)
        palm_mask = np.asarray(palms.filter(ImageFilter.GaussianBlur(1)), np.float32)[..., None] / 255.0
        ink = np.array(pal["ink"], np.float32) * 0.6
        grid_col = np.array(pal["grid"], np.float32)

        self.frames: list[np.ndarray] = []
        for k in range(loop):
            off = k / loop
            ground = ground_base.copy()
            lines = np.zeros((h - horizon, w), np.float32)
            gh = h - horizon
            K = gh * 0.9
            for i in range(26):
                d = 1 + i - off
                if d <= 0.15:
                    continue
                y = int(K / d)
                if 0 <= y < gh:
                    cv2.line(lines, (0, y), (w, y), 1.0, max(1, int(4 / d ** 0.5)), cv2.LINE_AA)
            for j in range(-14, 15):
                cv2.line(lines, (w // 2, 0), (w // 2 + j * 190, gh), 1.0, 2, cv2.LINE_AA)
            fade = np.linspace(0.15, 1.0, gh, dtype=np.float32)[:, None]
            glow_l = cv2.GaussianBlur(lines, (0, 0), 6) * 1.6
            ground += (np.clip(lines + glow_l, 0, 1.6) * fade)[..., None] * grid_col * 0.8
            cv2.line(ground, (0, 0), (w, 0), tuple(float(c) for c in pal["accent2"]), 3, cv2.LINE_AA)
            full = np.concatenate([sky, ground], axis=0)
            full = full * (1 - palm_mask) + ink * palm_mask
            full = full * prof * vig
            self.frames.append(np.clip(full, 0, 255).astype(np.uint8))

    def frame(self, t: float) -> np.ndarray:
        return self.frames[int(t * self.fps) % self.loop]


class Aurora(Background):
    """Slow drifting neon blobs, rendered at quarter size and upscaled."""

    def __init__(self, w: int, h: int, pal: dict[str, RGB], rng: random.Random, scale: int = 4):
        self.w, self.h, self.s = w, h, scale
        sw, sh = w // scale, h // scale
        self.base = gradient(sh, sw, [(0, pal["top"]), (0.6, pal["ink"]), (1, (0, 0, 0))])
        self.mult = (readability_profile(sh)[:, None] * vignette(sh, sw, 0.55))[..., None]
        self.blobs = []
        for col in (pal["mid"], pal["bottom"], pal["accent2"], pal["accent"], pal["mid"]):
            r = int(sw * rng.uniform(0.35, 0.6))
            yy, xx = np.mgrid[-r:r, -r:r].astype(np.float32)
            d2 = (xx ** 2 + yy ** 2) / float(r * r)
            g = np.exp(-d2 * 2.2) * np.clip(1.0 - d2, 0, 1) ** 2   # smooth falloff that reaches 0 at r
            self.blobs.append(dict(
                img=g[..., None] * np.array(col, np.float32) * rng.uniform(0.75, 1.15), r=r,
                cx=rng.uniform(0.15, 0.85) * sw, cy=rng.uniform(0.1, 0.9) * sh,
                ax=rng.uniform(0.12, 0.3) * sw, ay=rng.uniform(0.08, 0.2) * sh,
                fx=rng.uniform(0.05, 0.13), fy=rng.uniform(0.04, 0.11), ph=rng.uniform(0, 6.28)))
        self.out = np.empty((h, w, 3), np.uint8)

    def frame(self, t: float) -> np.ndarray:
        canvas = self.base.copy()
        sh, sw = canvas.shape[:2]
        for b in self.blobs:
            x = int(b["cx"] + b["ax"] * math.sin(t * b["fx"] * 6.28 + b["ph"]))
            y = int(b["cy"] + b["ay"] * math.cos(t * b["fy"] * 6.28 + b["ph"] * 1.3))
            r = b["r"]
            x0, y0, x1, y1 = x - r, y - r, x + r, y + r
            cx0, cy0, cx1, cy1 = max(x0, 0), max(y0, 0), min(x1, sw), min(y1, sh)
            if cx0 >= cx1 or cy0 >= cy1:
                continue
            canvas[cy0:cy1, cx0:cx1] += b["img"][cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0]
        canvas = np.clip(canvas * self.mult, 0, 255).astype(np.uint8)
        cv2.resize(canvas, (self.w, self.h), dst=self.out, interpolation=cv2.INTER_CUBIC)
        return self.out


class Skyline(Background):
    """Night city silhouettes with lit windows, two parallax layers scrolling sideways."""

    def __init__(self, w: int, h: int, pal: dict[str, RGB], rng: random.Random, fps: int = 30):
        self.w, self.h = w, h
        prof = readability_profile(h)[:, None, None]
        sky = gradient(h, w, [(0, pal["top"]), (0.55, pal["mid"]), (0.8, pal["bottom"]), (1, pal["ink"])])
        _stars(sky, rng, 110, int(h * 0.35))
        moon = np.zeros((h, w), np.float32)
        cv2.circle(moon, (int(w * 0.72), int(h * 0.2)), 95, 1.0, -1, cv2.LINE_AA)
        moon = cv2.GaussianBlur(moon, (0, 0), 3) + cv2.GaussianBlur(moon, (0, 0), 60) * 0.6
        sky += moon[..., None] * np.array(mix(pal["accent"], (255, 255, 255), 0.5), np.float32)
        self.sky = np.clip(sky * prof * vignette(h, w, 0.35)[..., None], 0, 255).astype(np.uint8)
        self.layers = []
        for depth, (hmin, hmax, speed, shade, lit) in enumerate(
                [(0.18, 0.34, 14.0, 0.55, 0.05), (0.22, 0.48, 32.0, 0.0, 0.16)]):
            lw = w * 2
            col = np.array(mix(pal["ink"], pal["mid"], shade), np.float32)
            layer = np.zeros((h, lw, 3), np.float32)
            mask = np.zeros((h, lw), np.uint8)
            x = 0
            while x < lw:
                bw = rng.randint(70, 190)
                bh = int(h * rng.uniform(hmin, hmax))
                y0 = h - bh
                mask[y0:h, x:x + bw] = 1
                layer[y0:h, x:x + bw] = col
                win = mix(pal["accent"], (255, 240, 200), 0.6) if rng.random() < 0.7 else pal["accent2"]
                for wy in range(y0 + 22, h - 30, 34):
                    for wx in range(x + 14, x + bw - 18, 26):
                        if rng.random() < lit:
                            layer[wy:wy + 14, wx:wx + 10] = win
                if depth == 1 and rng.random() < 0.18:
                    sign = pal["accent2"] if rng.random() < 0.5 else pal["accent"]
                    layer[y0 - 26:y0 - 6, x + 10:x + bw - 10] = sign
                    mask[y0 - 26:y0 - 6, x + 10:x + bw - 10] = 1
                if rng.random() < 0.25:
                    ax = x + bw // 2
                    mask[y0 - 60:y0, ax:ax + 3] = 1
                    layer[y0 - 60:y0, ax:ax + 3] = col
                x += bw + rng.randint(0, 12)
            layer = layer * prof
            rows = np.where(mask.any(axis=1))[0]
            y0 = int(rows[0]) if rows.size else h
            self.layers.append((np.clip(layer[y0:], 0, 255).astype(np.uint8), mask[y0:].astype(bool), speed, y0))
        self.out = np.empty((h, w, 3), np.uint8)

    def frame(self, t: float) -> np.ndarray:
        np.copyto(self.out, self.sky)
        for layer, mask, speed, y0 in self.layers:
            off = int(t * speed) % self.w
            np.copyto(self.out[y0:], layer[:, off:off + self.w], where=mask[:, off:off + self.w, None])
        return self.out


class Stripes(Background):
    """80s diagonal stripes sliding past a soft glow."""

    def __init__(self, w: int, h: int, pal: dict[str, RGB], rng: random.Random, fps: int = 30, loop: int = 30):
        self.fps, self.loop = fps, loop
        base = gradient(h, w, [(0, pal["top"]), (0.5, pal["ink"]), (1, (0, 0, 0))])
        glow = np.zeros((h, w), np.float32)
        cv2.circle(glow, (w // 2, int(h * 0.45)), int(w * 0.55), 1.0, -1)
        glow = cv2.GaussianBlur(glow, (0, 0), 120)
        base += glow[..., None] * np.array(pal["mid"], np.float32) * 0.9
        mult = (readability_profile(h)[:, None] * vignette(h, w))[..., None]
        period = 260
        colors = [np.array(c, np.float32) for c in (pal["accent2"], pal["accent"], pal["bottom"])]
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        diag = (xx + yy * 0.55)
        band_y = (np.abs(yy / h - 0.5) < 0.5).astype(np.float32)
        self.frames = []
        for k in range(loop):
            phase = (diag - k * period / loop) % (period * 3)
            img = base.copy()
            for ci, c in enumerate(colors):
                lo = ci * period
                inside = ((phase >= lo) & (phase < lo + period * 0.38)).astype(np.float32)
                img += (inside * band_y * 0.22)[..., None] * c
            self.frames.append(np.clip(img * mult, 0, 255).astype(np.uint8))

    def frame(self, t: float) -> np.ndarray:
        return self.frames[int(t * self.fps) % self.loop]


def make_background(name: str, w: int, h: int, pal: dict[str, RGB], seed: int, fps: int = 30) -> Background:
    rng = random.Random(seed)
    if name == "synth_grid":
        return SynthGrid(w, h, pal, rng, fps)
    if name == "aurora":
        return Aurora(w, h, pal, rng)
    if name == "skyline":
        return Skyline(w, h, pal, rng, fps)
    if name == "stripes":
        return Stripes(w, h, pal, rng, fps)
    raise ValueError(f"unknown background {name}")
