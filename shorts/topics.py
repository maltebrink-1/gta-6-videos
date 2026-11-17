"""Choosing what the next video is about (format + facts), with variety built in."""
from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass, field

from .models import Fact

# Each format: what it is (also sent to the LLM writer), base weight, how many facts it uses.
FORMATS: dict[str, dict] = {
    "countdown": {
        "label": "Countdown",
        "brief": "Launch is days away. Hook with the number of days left, then 2–3 confirmed launch facts, "
                 "optionally one clearly-labelled rumour, end with a question.",
        "weight": 3.0,
    },
    "launch_recap": {
        "label": "It's out",
        "brief": "The game is out. Quick recap of the essentials (platforms, price, setting) for people "
                 "deciding whether to jump in. End with a question.",
        "weight": 3.0,
    },
    "confirmed_vs_rumor": {
        "label": "Confirmed vs rumour",
        "brief": "Sort what is official from what is only rumoured. Confirmed items first, then the rumour "
                 "explicitly labelled as unconfirmed, then a verdict.",
        "weight": 2.0,
    },
    "top3": {
        "label": "3 things",
        "brief": "Three surprising facts on one theme, counted down 3-2-1, punchy and fast.",
        "weight": 1.6,
    },
    "region_spotlight": {
        "label": "Region spotlight",
        "brief": "Spotlight one region of Leonida: what it is, the vibe, why it's interesting. "
                 "End by asking viewers what they'll do there first.",
        "weight": 1.4,
    },
    "by_the_numbers": {
        "label": "By the numbers",
        "brief": "GTA VI explained through big numbers. Each scene is one number with context.",
        "weight": 1.3,
    },
    "myth_buster": {
        "label": "Myth buster",
        "brief": "State a popular false claim, call it a myth, then correct it with the confirmed fact.",
        "weight": 1.0,
    },
    "then_vs_now": {
        "label": "Then vs now",
        "brief": "Compare 2002's Vice City with GTA VI's Leonida using only the supplied facts.",
        "weight": 0.9,
    },
    "poll": {
        "label": "Community poll",
        "brief": "Present the six regions quickly and ask viewers to vote in the comments.",
        "weight": 0.8,
    },
}

THEMES = {  # phrased to fit "3 things about {theme}"
    "price": "GTA 6's price",
    "trailers": "GTA 6's trailers",
    "release": "GTA 6's launch",
    "world": "GTA 6's map",
}


@dataclass
class Plan:
    format: str
    fact_ids: list[str]
    theme: str = ""
    notes: dict = field(default_factory=dict)


def _ok(pool: dict[str, Fact], *ids: str) -> bool:
    return all(i in pool for i in ids)


def _ids(pool: dict[str, Fact], status: str | None = None, topic: str | None = None) -> list[str]:
    return [f.id for f in pool.values()
            if (status is None or f.status == status) and (topic is None or topic in f.topics)]


def candidates(pool: dict[str, Fact], rng: random.Random) -> list[Plan]:
    """Every plan that the current fact pool can support."""
    plans: list[Plan] = []
    confirmed = _ids(pool, "confirmed")
    rumors = _ids(pool, "rumor")

    if "days_until_release" in pool:
        extras = [i for i in ("release_time", "platforms", "price_us", "preorder_bonus", "no_disc") if i in pool]
        rng.shuffle(extras)
        ids = ["days_until_release", "release_date"] + extras[:2]
        if rumors:
            ids.append(rng.choice(rumors))
        plans.append(Plan("countdown", ids))
    if "days_since_release" in pool:
        extras = [i for i in ("platforms", "price_us", "setting", "protagonists") if i in pool]
        plans.append(Plan("launch_recap", ["days_since_release", "release_date"] + extras[:3]))

    if rumors and len(confirmed) >= 2:
        rumor = rng.choice(rumors)
        rumor_topics = set(pool[rumor].topics)
        related = [i for i in confirmed if rumor_topics & set(pool[i].topics) and not pool[i].derived]
        others = [i for i in confirmed if i not in related and not pool[i].derived]
        rng.shuffle(related)
        rng.shuffle(others)
        picks = (related + others)[:2]
        plans.append(Plan("confirmed_vs_rumor", picks + [rumor]))

    for theme in THEMES:
        ids = [i for i in _ids(pool, topic=theme) if pool[i].status in ("confirmed", "reported")
               and not pool[i].derived]
        if len(ids) >= 3:
            rng.shuffle(ids)
            plans.append(Plan("top3", ids[:3], theme=theme))

    regions = [i for i in _ids(pool, topic="regions") if i.startswith("region_")]
    if regions:
        region = rng.choice(regions)
        extra = [i for i in ("six_regions", "florida_inspiration", "setting") if i in pool]
        plans.append(Plan("region_spotlight", [region] + extra[:2], theme=region))

    numeric = [f.id for f in pool.values() if f.status in ("confirmed", "reported") and not f.derived
               and any(ch.isdigit() for ch in f.short)]
    if len(numeric) >= 3:
        rng.shuffle(numeric)
        plans.append(Plan("by_the_numbers", numeric[:3]))

    for myth in _ids(pool, "debunked"):
        rebuttal = pool[myth].rebuttal
        if rebuttal and rebuttal in pool:
            plans.append(Plan("myth_buster", [myth, rebuttal]))

    if _ok(pool, "vice_city_2002", "setting"):
        extra = [i for i in ("six_regions", "preorder_bonus", "protagonists") if i in pool]
        plans.append(Plan("then_vs_now", ["vice_city_2002", "setting"] + extra[:2]))

    if _ok(pool, "six_regions"):
        plans.append(Plan("poll", ["six_regions"] + (["setting"] if "setting" in pool else [])))
    return plans


def choose_plan(pool: dict[str, Fact], history: list[dict], today: dt.date, rng: random.Random,
                forced_format: str | None = None, format_cooldown: int = 2) -> Plan:
    plans = candidates(pool, rng)
    if forced_format:
        plans = [p for p in plans if p.format == forced_format]
        if not plans:
            raise ValueError(f"format '{forced_format}' isn't possible with the current facts")
        return plans[0]
    if not plans:
        raise ValueError("no usable facts – check data/facts.yaml (stale or expired facts are skipped)")

    recent_formats = [h.get("format") for h in history[-format_cooldown:]] if format_cooldown else []
    recent_facts = {f for h in history[-5:] for f in h.get("fact_ids", [])}
    scored: list[tuple[float, Plan]] = []
    for p in plans:
        if p.format in recent_formats and len(plans) > 1:
            continue
        spec = FORMATS[p.format]
        novelty = sum(1 for f in p.fact_ids if f not in recent_facts) / max(len(p.fact_ids), 1)
        score = spec["weight"] * (0.4 + novelty)
        if p.format == "countdown" and "days_until_release" in pool:
            days = int(pool["days_until_release"].claim.split(" in ")[1].split()[0]) \
                if " in " in pool["days_until_release"].claim else 1
            score *= 2.0 if days <= 14 else 1.0
        score *= rng.uniform(0.85, 1.15)
        scored.append((score, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]
