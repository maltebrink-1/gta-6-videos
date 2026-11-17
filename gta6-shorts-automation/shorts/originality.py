"""Anti-repetition checks so the channel doesn't look mass-produced.

YouTube's "inauthentic content" policy targets videos that look template-made
or feel repetitive when watched in a row, so every new script is compared
with recent ones (wording, hook, format, facts and visual style).
"""
from __future__ import annotations

import re

from .models import Issue, Script

_WORD = re.compile(r"[a-z0-9']+")


def shingles(text: str, n: int = 3) -> set[tuple[str, ...]]:
    words = _WORD.findall(text.lower())
    if len(words) < n:
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity(text_a: str, text_b: str) -> float:
    return jaccard(shingles(text_a), shingles(text_b))


def check_originality(script: Script, history: list[dict], max_similarity: float = 0.35,
                      hook_cooldown: int = 20, format_cooldown: int = 2) -> list[Issue]:
    """history: newest-last list of registry records ({'narration','hook','hook_pattern','format','style'})."""
    issues: list[Issue] = []
    text = script.narration
    hook = script.scenes[0].narration if script.scenes else ""

    worst, worst_id = 0.0, None
    for rec in history:
        sim = similarity(text, rec.get("narration", ""))
        if sim > worst:
            worst, worst_id = sim, rec.get("id")
    if worst > max_similarity:
        issues.append(Issue("error", "too_similar",
                            f"script overlaps {worst:.0%} with {worst_id} (max {max_similarity:.0%})"))

    recent = history[-hook_cooldown:] if hook_cooldown else []
    for rec in recent:
        if script.hook_pattern and script.hook_pattern == rec.get("hook_pattern"):
            issues.append(Issue("error", "hook_reused",
                                f"hook pattern '{script.hook_pattern}' was used by {rec.get('id')} recently"))
            break
        if similarity(hook, rec.get("hook", "")) > 0.5:
            issues.append(Issue("error", "hook_similar", f"hook is too close to {rec.get('id')}'s hook"))
            break

    if format_cooldown and len(history) >= format_cooldown:
        last = [rec.get("format") for rec in history[-format_cooldown:]]
        if all(f == script.format for f in last):
            issues.append(Issue("warning", "format_streak",
                                f"format '{script.format}' used {format_cooldown}× in a row"))
    return issues
