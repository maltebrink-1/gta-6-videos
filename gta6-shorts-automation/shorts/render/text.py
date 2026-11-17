"""Text rendering to RGBA numpy arrays (PIL for glyphs, numpy for compositing)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..config import Paths

FONT_FILES = {"bold": "Poppins-Bold.ttf", "medium": "Poppins-Medium.ttf", "regular": "Poppins-Regular.ttf"}
RGB = tuple[int, int, int]


@lru_cache(maxsize=256)
def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    path = Paths().fonts / FONT_FILES[weight]
    if not path.exists():
        raise FileNotFoundError(f"missing font {path}")
    return ImageFont.truetype(str(path), size)


def text_width(text: str, f: ImageFont.FreeTypeFont) -> float:
    return f.getlength(text)


def wrap(text: str, f: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if text_width(trial, f) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def balance(lines: list[str], f: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Re-split into the same number of lines with the most even widths ("REVIEWS / NOV 18?")."""
    words = " ".join(lines).split()
    n = len(lines)
    if n < 2 or len(words) < n:
        return lines
    best, best_w = lines, max(text_width(ln, f) for ln in lines)
    if n == 2:
        for i in range(1, len(words)):
            cand = [" ".join(words[:i]), " ".join(words[i:])]
            w = max(text_width(c, f) for c in cand)
            if w <= max_width and w < best_w:
                best, best_w = cand, w
    elif n == 3:
        for i in range(1, len(words) - 1):
            for j in range(i + 1, len(words)):
                cand = [" ".join(words[:i]), " ".join(words[i:j]), " ".join(words[j:])]
                w = max(text_width(c, f) for c in cand)
                if w <= max_width and w < best_w:
                    best, best_w = cand, w
    return best


def fit(text: str, weight: str, max_width: int, max_lines: int, max_size: int, min_size: int):
    """Largest font size where the text wraps into <= max_lines lines that each fit (balanced)."""
    for size in range(max_size, min_size - 1, -4):
        f = font(weight, size)
        lines = wrap(text, f, max_width)
        if len(lines) <= max_lines and all(text_width(ln, f) <= max_width for ln in lines):
            return balance(lines, f, max_width), f
    f = font(weight, min_size)
    return balance(wrap(text, f, max_width)[:max_lines], f, max_width), f


def _to_array(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGBA"), dtype=np.uint8).copy()


def text_block(lines: list[str], f: ImageFont.FreeTypeFont, fill: RGB, stroke: int = 0,
               stroke_fill: RGB = (0, 0, 0), shadow: int = 0, shadow_color: RGB = (0, 0, 0),
               line_gap: float = 0.08, glow: int = 0, glow_color: RGB | None = None) -> np.ndarray:
    ascent, descent = f.getmetrics()
    line_h = ascent + descent
    gap = int(line_h * line_gap)
    widths = [int(text_width(ln, f)) for ln in lines]
    pad = stroke + shadow + glow * 2 + 6
    w = max(widths) + pad * 2
    h = line_h * len(lines) + gap * (len(lines) - 1) + pad * 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    def draw_lines(target: Image.Image, color, dx=0, dy=0, sw=0, sf=None):
        d = ImageDraw.Draw(target)
        y = pad + dy
        for ln, lw in zip(lines, widths):
            x = (w - lw) // 2 + dx
            d.text((x, y), ln, font=f, fill=color, stroke_width=sw, stroke_fill=sf)
            y += line_h + gap

    if glow:
        g = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw_lines(g, (*(glow_color or fill), 255), sw=stroke + glow // 2, sf=(*(glow_color or fill), 255))
        g = g.filter(ImageFilter.GaussianBlur(glow))
        img = Image.alpha_composite(img, g)
    if shadow:
        s = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw_lines(s, (*shadow_color, 200), dx=shadow // 2, dy=shadow, sw=stroke, sf=(*shadow_color, 200))
        s = s.filter(ImageFilter.GaussianBlur(max(shadow // 3, 1)))
        img = Image.alpha_composite(img, s)
    top = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw_lines(top, (*fill, 255), sw=stroke, sf=(*stroke_fill, 255) if stroke else None)
    img = Image.alpha_composite(img, top)
    return _to_array(img)


def gradient_text(text: str, f: ImageFont.FreeTypeFont, top: RGB, bottom: RGB, stroke: int = 10,
                  stroke_fill: RGB = (0, 0, 0), glow: int = 24, glow_color: RGB | None = None) -> np.ndarray:
    """Huge hero number/word filled with a vertical gradient, outlined and glowing."""
    bbox = f.getbbox(text, stroke_width=stroke)
    pad = glow * 2 + stroke + 8
    w, h = bbox[2] - bbox[0] + pad * 2, bbox[3] - bbox[1] + pad * 2
    origin = (pad - bbox[0], pad - bbox[1])
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text(origin, text, font=f, fill=255)
    outline = Image.new("L", (w, h), 0)
    ImageDraw.Draw(outline).text(origin, text, font=f, fill=255, stroke_width=stroke, stroke_fill=255)
    grad = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    colors = (np.array(top, np.float32) * (1 - grad) + np.array(bottom, np.float32) * grad)
    colors = np.broadcast_to(colors, (h, w, 3))
    out = np.zeros((h, w, 4), np.float32)
    if glow:
        gmask = np.asarray(outline.filter(ImageFilter.GaussianBlur(glow)), np.float32) / 255.0
        gc = np.array(glow_color or top, np.float32)
        out[..., :3] = gc
        out[..., 3] = gmask * 0.85
    o = np.asarray(outline, np.float32)[..., None] / 255.0
    out[..., :3] = out[..., :3] * (1 - o) + np.array(stroke_fill, np.float32) * o
    out[..., 3:] = np.maximum(out[..., 3:], o)
    m = np.asarray(mask, np.float32)[..., None] / 255.0
    out[..., :3] = out[..., :3] * (1 - m) + colors * m
    out[..., 3:] = np.maximum(out[..., 3:], m)
    out[..., 3] *= 255
    return np.clip(out, 0, 255).astype(np.uint8)


def _icon(draw: ImageDraw.ImageDraw, kind: str, cx: int, cy: int, r: int, color) -> None:
    w = max(r // 3, 3)
    if kind == "CONFIRMED":
        draw.line([(cx - r * 0.55, cy), (cx - r * 0.12, cy + r * 0.45), (cx + r * 0.6, cy - r * 0.5)],
                  fill=color, width=w, joint="curve")
    elif kind == "MYTH":
        draw.line([(cx - r * 0.45, cy - r * 0.45), (cx + r * 0.45, cy + r * 0.45)], fill=color, width=w)
        draw.line([(cx - r * 0.45, cy + r * 0.45), (cx + r * 0.45, cy - r * 0.45)], fill=color, width=w)
    elif kind == "RUMOR":
        f = font("bold", int(r * 1.7))
        draw.text((cx, cy + r * 0.05), "?", font=f, fill=color, anchor="mm")
    else:  # REPORTED: "i"
        f = font("bold", int(r * 1.6))
        draw.text((cx, cy + r * 0.05), "i", font=f, fill=color, anchor="mm")


def pill(label: str, bg: RGB, fg: RGB = (255, 255, 255), size: int = 46, icon: str | None = None) -> np.ndarray:
    f = font("bold", size)
    tw = int(text_width(label, f))
    h = int(size * 1.75)
    r_icon = int(h * 0.32)
    icon_w = (r_icon * 2 + int(size * 0.45)) if icon else 0
    pad_x = int(size * 0.7)
    w = tw + pad_x * 2 + icon_w
    scale = 2  # supersample for smooth edges
    img = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w * scale - 1, h * scale - 1], radius=h * scale // 2, fill=(*bg, 255))
    if icon:
        cx, cy = pad_x * scale + r_icon * scale, h * scale // 2
        d.ellipse([cx - r_icon * scale, cy - r_icon * scale, cx + r_icon * scale, cy + r_icon * scale],
                  fill=(255, 255, 255, 255))
        _icon(d, icon, cx, cy, int(r_icon * scale * 0.85), (*bg, 255))
    img = img.resize((w, h), Image.LANCZOS)
    d = ImageDraw.Draw(img)
    asc, desc = f.getmetrics()
    d.text((pad_x + icon_w, (h - (asc + desc)) // 2 + 1), label, font=f, fill=(*fg, 255))
    return _to_array(img)


def card(content: np.ndarray, bg: RGB, alpha: int = 150, radius: int = 36, pad: int = 34,
         border: RGB | None = None, border_w: int = 4) -> np.ndarray:
    """Rounded translucent panel behind content (content is centred)."""
    h, w = content.shape[:2]
    W, H = w + pad * 2, h + pad * 2
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=radius, fill=(*bg, alpha),
                        outline=(*border, 230) if border else None, width=border_w if border else 0)
    base = _to_array(img)
    return alpha_over_rgba(base, content, pad, pad)


def alpha_over_rgba(dst: np.ndarray, src: np.ndarray, x: int, y: int) -> np.ndarray:
    """Composite RGBA onto RGBA (both uint8), returns new array."""
    out = dst.astype(np.float32)
    h, w = src.shape[:2]
    region = out[y:y + h, x:x + w]
    s = src.astype(np.float32)
    sa = s[..., 3:4] / 255.0
    da = region[..., 3:4] / 255.0
    oa = sa + da * (1 - sa)
    rgb = (s[..., :3] * sa + region[..., :3] * da * (1 - sa)) / np.maximum(oa, 1e-6)
    region[..., :3] = rgb
    region[..., 3:4] = oa * 255
    out[y:y + h, x:x + w] = region
    return np.clip(out, 0, 255).astype(np.uint8)


def caption_image(words: list[str], active: int, style: str, f: ImageFont.FreeTypeFont, accent: RGB,
                  ink: RGB, max_width: int) -> np.ndarray:
    """One caption chunk with word `active` highlighted. Styles: pop | box | clean."""
    words = [w.upper() for w in words]
    space = text_width(" ", f) * (1.9 if style == "box" else 1.1)
    widths = [text_width(w, f) for w in words]
    # wrap into at most 2 lines
    lines: list[list[int]] = [[]]
    cur = 0.0
    for i, wd in enumerate(widths):
        need = wd if not lines[-1] else cur + space + wd
        if lines[-1] and need > max_width:
            lines.append([i])
            cur = wd
        else:
            lines[-1].append(i)
            cur = need
    asc, desc = f.getmetrics()
    line_h = int((asc + desc) * 1.02)
    stroke = max(int(f.size * 0.11), 6)
    pad = stroke + 24
    line_w = [sum(widths[i] for i in ln) + space * (len(ln) - 1) for ln in lines]
    W = int(max(line_w)) + pad * 2
    H = line_h * len(lines) + pad * 2
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d, ds = ImageDraw.Draw(img), ImageDraw.Draw(shadow)
    for li, ln in enumerate(lines):
        x = (W - line_w[li]) / 2
        y = pad + li * line_h
        for i in ln:
            is_active = i == active
            if style == "box" and is_active:
                d.rounded_rectangle([x - 12, y + 6, x + widths[i] + 12, y + line_h - 2], radius=18,
                                    fill=(*accent, 255))
            color = (255, 255, 255)
            if is_active and style == "pop":
                color = accent
            if is_active and style == "box":
                color = ink
            ds.text((x + 4, y + 8), words[i], font=f, fill=(0, 0, 0, 170), stroke_width=stroke,
                    stroke_fill=(0, 0, 0, 170))
            sw = 0 if (style == "box" and is_active) else stroke
            d.text((x, y), words[i], font=f, fill=(*color, 255), stroke_width=sw, stroke_fill=(0, 0, 0, 255))
            if style == "clean" and is_active:
                d.rounded_rectangle([x, y + line_h - 6, x + widths[i], y + line_h + 4], radius=5,
                                    fill=(*accent, 255))
            x += widths[i] + space
    shadow = shadow.filter(ImageFilter.GaussianBlur(6))
    return _to_array(Image.alpha_composite(shadow, img))


def load_rgba(path: str | Path) -> np.ndarray:
    return _to_array(Image.open(path))
