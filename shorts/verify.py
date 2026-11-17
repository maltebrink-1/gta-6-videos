"""Fact-grounding verifier.

A script only passes if every factual statement can be traced to a fact in
data/facts.yaml, rumours are labelled as rumours, reported claims are
attributed, myths are framed as false, and nothing is stale or expired.
"""
from __future__ import annotations

import datetime as dt
import re

from .facts import numbers_in
from .models import Fact, Issue, Script

HEDGE_WORDS = ("rumor", "rumour", "reportedly", "unconfirmed", "not confirmed", "insider", "leak",
               "allegedly", "supposedly", "hasn't confirmed", "has not confirmed", "not official")
ATTRIBUTION_WORDS = ("according to", "says", "said", "reportedly", "reports", "reported", "widely",
                     "described", "seen as", "claims", "per rockstar", "rockstar's own")
MYTH_WORDS = ("myth", "false", "fake", "not true", "debunked", "wrong", "nope", "busted")

DEFAULT_BANNED = ("free download", "download free", "leaked gameplay", "leaked footage", "100% confirmed",
                  "guaranteed", "official channel", "we are rockstar", "mod menu", "crack", "torrent")
PROFANITY = ("fuck", "shit", "bitch", "cunt", "nigg", "fag", "retard", "kill yourself")

# Product names that contain digits but are not claims.
_NAME_PATTERNS = [r"\bGTA\s*(?:6|VI|5|V)\b", r"\bGrand Theft Auto\s*(?:VI|6|V|5)\b", r"\bPS5\b",
                  r"\bPlayStation\s*5\b", r"\bXbox Series X\|?S?\b", r"#\w+"]
_CLAIM_HINTS = re.compile(r"\d|\$|€|£|\b(?:january|february|march|april|may|june|july|august|september|"
                          r"october|november|december|confirmed|announced|revealed|official)\b", re.I)
_SMALL = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
          "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
          "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
         "ninety": 90}
_SPELLED_RE = re.compile(r"\b(" + "|".join(list(_TENS)) + r")(?:-(one|two|three|four|five|six|seven|eight|nine))?\b"
                         r"|\b(" + "|".join(_SMALL) + r")\b", re.I)
_UNITS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}


# Numbers that describe the video itself ("3 things", "in 30 seconds", "#1"), not the game.
_STRUCTURAL_PATTERNS = [
    r"\b(?:\d+|two|three|four|five)\s+(?:things|facts|reasons|details|secrets|questions|myths|numbers|tips)\b",
    r"\bin\s+(?:15|20|30|45|60)\s+seconds\b", r"\b\d+\s+in\s+(?:15|20|30|45|60)\b", r"#\d+\b",
    r"\bnumber\s+\d+\b", r"\b\d+\s+seconds\b",
]


def strip_names(text: str) -> str:
    for pat in _NAME_PATTERNS + _STRUCTURAL_PATTERNS:
        text = re.sub(pat, " ", text, flags=re.I)
    return text


def spelled_numbers(text: str) -> set[str]:
    """'six regions', 'ninety-three' -> {'6', '93'}. 'one' is ignored (too often a pronoun)."""
    out: set[str] = set()
    for m in _SPELLED_RE.finditer(text):
        if m.group(1):
            value = _TENS[m.group(1).lower()] + (_UNITS[m.group(2).lower()] if m.group(2) else 0)
        else:
            value = _SMALL[m.group(3).lower()]
        out.add(str(value))
    return out


def all_numbers(text: str) -> set[str]:
    cleaned = strip_names(text)
    return numbers_in(cleaned) | spelled_numbers(cleaned)


def _contains_any(text: str, words) -> bool:
    low = f" {text.lower()} "
    return any(w in low for w in words)


def scene_badge(fact_ids: list[str], pool: dict[str, Fact]) -> str:
    statuses = {pool[f].status for f in fact_ids if f in pool}
    if "rumor" in statuses:
        return "RUMOR"
    if "debunked" in statuses:
        return "MYTH"
    if "reported" in statuses:
        return "REPORTED"
    if "confirmed" in statuses:
        return "CONFIRMED"
    return ""


def assign_badges(script: Script, pool: dict[str, Fact]) -> Script:
    """Badges are derived from the cited facts – the writer can't choose them.
    Hooks only show a badge when it's a warning (RUMOR/MYTH) to keep frame one clean."""
    for scene in script.scenes:
        if scene.kind == "cta":
            scene.badge = ""
            continue
        badge = scene_badge(scene.fact_ids, pool)
        if scene.kind == "hook" and badge in ("CONFIRMED", "REPORTED"):
            badge = ""
        scene.badge = badge
    return script


def verify_script(script: Script, pool: dict[str, Fact], all_facts: dict[str, Fact], today: dt.date,
                  min_words: int = 45, max_words: int = 150, banned: tuple[str, ...] = ()) -> list[Issue]:
    issues: list[Issue] = []
    err = lambda code, msg: issues.append(Issue("error", code, msg))  # noqa: E731
    warn = lambda code, msg: issues.append(Issue("warning", code, msg))  # noqa: E731

    banned_all = tuple(b.lower() for b in (DEFAULT_BANNED + tuple(banned)))
    scenes = script.scenes

    # ── Structure ────────────────────────────────────────────────────────────
    if not script.title.strip():
        err("no_title", "title is empty")
    if len(script.title) > 100:
        err("title_too_long", f"title is {len(script.title)} chars (YouTube max 100)")
    if not 3 <= len(scenes) <= 9:
        err("scene_count", f"{len(scenes)} scenes; need 3–9")
    words = script.word_count()
    if words < min_words:
        err("too_short", f"{words} words; need at least {min_words} (~20 s)")
    if words > max_words:
        err("too_long", f"{words} words; max {max_words} (~60 s)")
    if scenes:
        hook = scenes[0]
        if hook.kind != "hook":
            err("no_hook", "first scene must be the hook")
        if len(hook.narration.split()) > 16:
            err("slow_hook", f"hook is {len(hook.narration.split())} words; keep it under 17 so it lands in ~2 s")
        if not hook.on_screen and not hook.big:
            err("hook_no_text", "hook needs on-screen text from frame one")
        if scenes[-1].kind != "cta":
            warn("no_cta", "last scene is usually a call to action")

    full_text = " ".join([script.title] + [f"{s.narration} {s.on_screen} {s.big}" for s in scenes]).lower()
    for phrase in banned_all:
        if phrase in full_text:
            err("banned_phrase", f"contains banned phrase '{phrase}'")
    for word in PROFANITY:
        if word in full_text:
            err("profanity", f"contains '{word}'")
    non_ascii = sum(1 for ch in script.narration if ord(ch) > 127 and ch not in "’‘“”—–…€£é")
    if non_ascii > 3:
        err("not_english", "narration contains non-English characters")

    # ── Per-scene grounding ─────────────────────────────────────────────────
    n_points = sum(1 for s in scenes if s.kind in ("point", "rumor", "myth", "number"))
    structural = {str(i) for i in range(1, max(n_points, 3) + 1)}
    debunked_used = False
    for i, s in enumerate(scenes, start=1):
        label = f"scene {i} ({s.kind})"
        big = "" if s.big.lstrip("#") in structural else s.big   # "#3" / "3" list markers aren't claims
        text = f"{s.narration} {s.on_screen} {big}"
        cited: list[Fact] = []
        for fid in s.fact_ids:
            if fid in pool:
                cited.append(pool[fid])
            elif fid in all_facts:
                f = all_facts[fid]
                why = "expired" if f.is_expired(today) else "stale (needs re-verification)"
                err("stale_fact", f"{label}: fact '{fid}' is {why}")
            else:
                err("unknown_fact", f"{label}: cites unknown fact '{fid}'")

        if not s.fact_ids:
            if _CLAIM_HINTS.search(strip_names(text)) and s.kind != "cta":
                err("uncited_claim", f"{label}: states a number/date/claim but cites no fact: '{s.narration[:70]}'")
            continue

        allowed: set[str] = set(structural)
        for f in cited:
            allowed |= all_numbers(f"{f.claim} {f.short}")
            if f.rebuttal and f.rebuttal in pool:
                allowed |= all_numbers(pool[f.rebuttal].claim)
        unknown = sorted(n for n in all_numbers(text) if n not in allowed)
        if unknown:
            err("unsupported_number", f"{label}: number(s) {unknown} not found in cited facts {s.fact_ids}")

        statuses = {f.status for f in cited}
        if "rumor" in statuses:
            if not _contains_any(s.narration, HEDGE_WORDS):
                err("unlabelled_rumor", f"{label}: cites a rumour but the narration doesn't say it's unconfirmed")
            if s.badge and s.badge != "RUMOR":
                err("wrong_badge", f"{label}: rumour scene must carry the RUMOR badge")
        if "reported" in statuses and not _contains_any(s.narration, ATTRIBUTION_WORDS + HEDGE_WORDS):
            err("unattributed", f"{label}: cites a 'reported' fact without attribution ('according to…')")
        if "debunked" in statuses:
            debunked_used = True
            if script.format != "myth_buster":
                err("myth_outside_format", f"{label}: debunked claims can only appear in myth_buster videos")
            if not _contains_any(text, MYTH_WORDS):
                err("myth_not_framed", f"{label}: debunked claim must be framed as false/myth")

    if debunked_used:
        rebuttals = {pool[f].rebuttal for s in scenes for f in s.fact_ids
                     if f in pool and pool[f].status == "debunked"}
        cited_ids = set(script.fact_ids)
        for r in rebuttals:
            if r not in cited_ids:
                err("no_rebuttal", f"myth is never corrected: cite the rebuttal fact '{r}'")

    # ── Title must only use confirmed numbers ───────────────────────────────
    confirmed_numbers: set[str] = set(structural)
    for fid in script.fact_ids:
        if fid in pool and pool[fid].status == "confirmed":
            confirmed_numbers |= all_numbers(f"{pool[fid].claim} {pool[fid].short}")
    bad_title = sorted(n for n in all_numbers(script.title) if n not in confirmed_numbers)
    if bad_title:
        err("title_unconfirmed_number", f"title uses number(s) {bad_title} that aren't confirmed facts")
    rumor_shorts = [pool[f].short.lower() for f in script.fact_ids if f in pool and pool[f].status == "rumor"]
    if any(r and r.rstrip("?") in script.title.lower() for r in rumor_shorts):
        err("rumor_in_title", "title presents a rumour")
    return issues


def passed(issues: list[Issue]) -> bool:
    return not any(i.level == "error" for i in issues)
