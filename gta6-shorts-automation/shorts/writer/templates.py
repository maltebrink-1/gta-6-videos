"""Offline script writer.

Works with no account and no internet. It is the fallback when the LLM
providers are unavailable, so it uses many interchangeable hooks, connectors
and lines to keep consecutive videos from sounding alike.
"""
from __future__ import annotations

import random

from ..models import Fact, Scene, Script
from ..topics import THEMES, Plan

# Narration variants per fact (display text: digits are fine, the voice
# normaliser turns them into words). Facts without an entry use their claim.
FACT_LINES: dict[str, list[str]] = {
    "release_date": ["It launches Thursday, November 19, 2026.",
                     "Mark your calendar: Thursday, November 19, 2026.",
                     "Launch day is locked in for Thursday, November 19, 2026."],
    "release_time": ["Rockstar says it unlocks at midnight local time, in every region.",
                     "And Rockstar says it unlocks at midnight, local time, wherever you are."],
    "platforms": ["You'll need a PS5 or an Xbox Series X|S. A PC version hasn't even been announced.",
                  "Consoles only at launch: PS5 and Xbox Series X|S. PC? Not announced."],
    "price_us": ["Standard Edition is $79.99. Ultimate Edition is $99.99.",
                 "Price check: $79.99 for Standard, $99.99 for Ultimate."],
    "price_eu": ["Over in Europe, it's €79.99 for Standard and €99.99 for Ultimate."],
    "preorder_bonus": ["Buy before November 20 and you get the Vintage Vice City Pack, a throwback to 2002.",
                       "Order before November 20 to grab the Vintage Vice City Pack."],
    "no_disc": ["And heads up: the physical version doesn't include a disc.",
                "Plot twist: the physical box doesn't include a disc."],
    "preorders_opened": ["Pre-orders opened on June 25, 2026."],
    "setting": ["The whole game is set in the state of Leonida, home to Vice City.",
                "Welcome to Leonida, the state that's home to Vice City."],
    "six_regions": ["Rockstar has revealed six regions: Vice City, the Leonida Keys, Grassrivers, "
                    "Port Gellhorn, Ambrosia and Mount Kalaga National Park."],
    "florida_inspiration": ["It's widely seen as Rockstar's take on Florida, with the Keys and the Everglades "
                            "getting their own twists.",
                            "According to most coverage, Leonida is basically Rockstar's Florida."],
    "region_keys": ["The Leonida Keys are a tropical island chain. Think sun, boats and bad decisions."],
    "region_grassrivers": ["Grassrivers is Leonida's swamp and wetland region. Bring bug spray."],
    "region_port_gellhorn": ["Port Gellhorn is a faded vacation town: cheap motels and tired strip malls."],
    "region_ambrosia": ["Ambrosia is Leonida's industrial heartland, built around sugar production."],
    "region_kalaga": ["Mount Kalaga National Park sits on the northern border, with hunting, fishing and "
                      "wild backcountry."],
    "protagonists": ["Two playable leads: Lucia Caminos and Jason Duval.",
                     "You play as Lucia Caminos and Jason Duval."],
    "trailer1_record": ["Trailer 1 pulled more than 93 million YouTube views in 24 hours. "
                        "No non-music video had ever debuted bigger.",
                        "93 million YouTube views in 24 hours. That's Trailer 1, a record for a "
                        "non-music debut."],
    "trailer2_views": ["Rockstar says Trailer 2 hit more than 475 million views across platforms in 24 hours."],
    "extended_look": ["On August 27, 2026, Rockstar dropped An Extended Look: about 20 minutes of gameplay."],
    "delay_history": ["It was delayed twice: from fall 2025 to May 26, 2026, then to November 19, 2026."],
    "delay_reason": ["Rockstar said the extra months were about polish."],
    "vice_city_2002": ["Grand Theft Auto: Vice City first came out in 2002."],
    "review_embargo": ["Insiders report reviews go live November 18, one day before launch. "
                       "Rockstar hasn't confirmed that.",
                       "The rumor: reviews drop November 18. That's from insiders, not Rockstar."],
}

# Past-tense variants used once the game is out (pool contains days_since_release).
POST_LAUNCH_LINES: dict[str, list[str]] = {
    "release_date": ["It launched on Thursday, November 19, 2026.", "It came out on Thursday, November 19, 2026."],
    "release_time": ["Rockstar unlocked it at midnight local time, in every region."],
    "platforms": ["It's on PS5 and Xbox Series X|S. A PC version still hasn't been announced."],
}

CONNECTORS = ["First up.", "Next.", "Also,", "Oh, and", "Here's the thing.", "Plus,", "Big one.",
              "Don't forget.", "Quick one.", "Real talk."]

CTAS: dict[str, list[str]] = {
    "countdown": ["Are you staying up for midnight? Tell me below.",
                  "Day one, or waiting for reviews? Comment now.",
                  "What's the first thing you're doing at launch? Tell me below."],
    "launch_recap": ["Are you playing yet? Tell me below.", "First impressions? Drop them in the comments."],
    "confirmed_vs_rumor": ["Did you believe the rumor? Be honest in the comments.",
                           "Which one did you think was real? Tell me below."],
    "top3": ["Which one surprised you most? Comment below.", "Did you know all three? Be honest.",
             "Which one did you not know? Tell me below."],
    "by_the_numbers": ["Which number shocked you most? Tell me below.", "Did any of these surprise you? Comment now."],
    "region_spotlight": ["What's the first thing you'd do in {region}? Comment now.",
                         "Would you live in {region}? Tell me below."],
    "myth_buster": ["Did you believe that one? Be honest below.", "What myth should I bust next? Comment it."],
    "then_vs_now": ["Old Vice City or new Leonida? Pick one below.",
                    "Did you play the original Vice City? Tell me below."],
    "poll": ["Which one are you exploring first? Vote in the comments."],
}

# Hero numbers for "by the numbers" scenes (must contain only numbers from the fact).
BIG: dict[str, str] = {"trailer1_record": "93M", "trailer2_views": "475M", "price_us": "$79.99",
                       "price_eu": "€79.99", "extended_look": "20 MIN", "six_regions": "6",
                       "release_date": "NOV 19", "preorders_opened": "JUNE 25", "vice_city_2002": "2002"}

# Headline under a hero number (so the number isn't shown twice).
NUMBER_CONTEXT: dict[str, str] = {"trailer1_record": "VIEWS IN A DAY", "trailer2_views": "VIEWS ACROSS PLATFORMS",
                                  "price_us": "STANDARD EDITION", "price_eu": "STANDARD IN EUROPE",
                                  "extended_look": "OF GAMEPLAY SHOWN", "six_regions": "REGIONS IN LEONIDA",
                                  "release_date": "LAUNCH DAY", "preorders_opened": "PRE-ORDERS OPENED",
                                  "vice_city_2002": "THE ORIGINAL VICE CITY"}

# Alternative on-screen text when the hook already used the fact's short text.
SCREEN_ALT: dict[str, str] = {"region_kalaga": "WILD BACKCOUNTRY", "region_keys": "ISLAND LIFE",
                              "region_grassrivers": "SWAMP COUNTRY", "region_port_gellhorn": "CHEAP MOTELS",
                              "region_ambrosia": "INDUSTRIAL HEARTLAND"}

HOOKS: dict[str, list[tuple[str, str, str]]] = {
    # (pattern id, narration, on_screen)  – {days}, {theme}, {region} are filled in
    "countdown": [("cd_days_away", "GTA 6 is {days} days away. Here's what's actually confirmed.", "DAYS LEFT"),
                  ("cd_thats_it", "{days} days. That's all that's left until GTA 6.", "DAYS UNTIL GTA 6"),
                  ("cd_need_to_know", "Only {days} days until GTA 6, and you need to know this.", "DAYS TO GO"),
                  ("cd_clock", "The GTA 6 clock is down to {days} days. Let's go.", "DAYS ON THE CLOCK")],
    "launch_recap": [("lr_finally", "GTA 6 is finally out. Here's the quick rundown.", "IT'S OUT"),
                     ("lr_day", "It's here. GTA 6 is out, so here's what you need.", "GTA 6 IS LIVE")],
    "confirmed_vs_rumor": [("cvr_real_or", "Real or rumor? Let's sort out GTA 6 in 30 seconds.", "REAL OR RUMOR?"),
                           ("cvr_stop", "Stop guessing. Here's what's real about GTA 6, and what isn't.", "FACT CHECK"),
                           ("cvr_heard", "You've heard a lot about GTA 6. Not all of it is true.", "TRUE OR NOT?")],
    "top3": [("t3_things", "3 things about {theme} you need to know.", "THINGS YOU NEED TO KNOW"),
             ("t3_missed", "You probably missed these 3 facts about {theme}.", "FACTS YOU MISSED"),
             ("t3_fast", "{theme_cap}: 3 facts, 30 seconds. Go.", "FACTS IN 30 SECONDS")],
    "region_spotlight": [("rs_welcome", "Welcome to {region}, one of GTA 6's wildest corners.", "{region_up}"),
                         ("rs_visit", "Your first trip in GTA 6 might be to {region}. Here's why.", "{region_up}"),
                         ("rs_know", "Let's talk about {region}, because nobody else is.", "{region_up}")],
    "by_the_numbers": [("btn_numbers", "GTA 6, by the numbers. Ready?", "BY THE NUMBERS"),
                       ("btn_crazy", "These GTA 6 numbers are actually crazy.", "THE NUMBERS")],
    "myth_buster": [("mb_stop", "Stop believing this GTA 6 myth.", "MYTH BUSTED"),
                    ("mb_wrong", "A lot of people still get this GTA 6 thing wrong.", "BIG MYTH")],
    "then_vs_now": [("tvn_then", "Vice City, 2002. Leonida, now. Let's compare.", "THEN VS NOW"),
                    ("tvn_back", "GTA is going back to Vice City, but it's not the Vice City you remember.",
                     "BACK TO VICE")],
    "poll": [("poll_one", "Six regions. One first stop. Which one is yours?", "PICK ONE"),
             ("poll_vote", "Quick vote: where are you going first in GTA 6?", "VOTE NOW")],
}

TITLES: dict[str, list[str]] = {
    "countdown": ["GTA 6 in {days} days: what's actually confirmed", "{days} days until GTA 6, the essentials",
                  "GTA 6 countdown: {days} days left"],
    "launch_recap": ["GTA 6 is out: the essentials in 30 seconds", "GTA 6 is finally here"],
    "confirmed_vs_rumor": ["GTA 6: confirmed vs rumor", "Real or rumor? GTA 6 fact check"],
    "top3": ["3 facts about {theme}", "3 things about {theme} you missed"],
    "region_spotlight": ["GTA 6: {region} explained", "Meet {region} in GTA 6"],
    "by_the_numbers": ["GTA 6 by the numbers", "The craziest GTA 6 numbers"],
    "myth_buster": ["GTA 6 myth busted", "This GTA 6 myth needs to stop"],
    "then_vs_now": ["Vice City 2002 vs GTA 6's Leonida", "GTA 6: then vs now"],
    "poll": ["Where are you going first in GTA 6?", "GTA 6: pick your first region"],
}


_POST_LAUNCH = False


def _line(fact: Fact, rng: random.Random) -> str:
    options = (POST_LAUNCH_LINES.get(fact.id) if _POST_LAUNCH else None) or FACT_LINES.get(fact.id)
    if options:
        return rng.choice(options)
    if fact.status == "rumor":
        return f"Rumor alert, and it's unconfirmed: {fact.claim}"
    return fact.claim


def _region_name(fact: Fact) -> str:
    return fact.short.title().replace("The Leonida Keys", "the Leonida Keys")


_LOWERABLE = {"It", "The", "You", "And", "Over", "Buy", "Order", "Plot", "Two", "Consoles", "Price", "Mark",
              "Launch", "Insiders", "On", "According", "Welcome", "Think", "Pre-orders", "It's"}


def _join(prefix: str, text: str) -> str:
    if prefix.endswith((".", "!", "?")):
        return f"{prefix} {text}"
    first, _, rest = text.partition(" ")
    if first in _LOWERABLE:
        first = first.lower()
    return f"{prefix} {first} {rest}".strip()


def _point(fact: Fact, rng: random.Random, prefix: str = "", kind: str = "point", big: str = "") -> Scene:
    text = _line(fact, rng)
    if prefix:
        text = _join(prefix, text)
    return Scene(kind=kind, narration=text, on_screen=fact.short, fact_ids=[fact.id], big=big)


def write_from_template(plan: Plan, pool: dict[str, Fact], video_id: str, rng: random.Random,
                        avoid_hooks: set[str] | None = None) -> Script:
    global _POST_LAUNCH
    _POST_LAUNCH = "days_since_release" in pool
    avoid_hooks = avoid_hooks or set()
    fmt = plan.format
    facts = [pool[i] for i in plan.fact_ids if i in pool]
    days = ""
    if "days_until_release" in pool:
        days = pool["days_until_release"].short.split()[0]
    region = _region_name(pool[plan.theme]) if plan.theme in pool else ""
    theme = THEMES.get(plan.theme, plan.theme)
    fill = {"days": days, "theme": theme, "theme_cap": theme[:1].upper() + theme[1:], "region": region,
            "region_up": region.upper()}

    hooks = [h for h in HOOKS[fmt] if h[0] not in avoid_hooks] or HOOKS[fmt]
    if fmt == "countdown" and days == "1":
        hooks = [("cd_tomorrow", "GTA 6 drops tomorrow. Here's everything you need.", "DAY LEFT")]
    pattern, hook_text, hook_screen = rng.choice(hooks)
    hook_facts: list[str] = []
    if fmt == "countdown":
        hook_facts = ["days_until_release"]
    elif fmt == "launch_recap":
        hook_facts = ["days_since_release"]
    elif fmt == "poll":
        hook_facts = ["six_regions"]
    elif fmt == "then_vs_now" and "2002" in hook_text:
        hook_facts = ["vice_city_2002"]
    elif fmt == "region_spotlight":
        hook_facts = [plan.theme]
    hook_big = days if fmt == "countdown" else ("3" if fmt == "top3" else "")
    scenes = [Scene(kind="hook", narration=hook_text.format(**fill), on_screen=hook_screen.format(**fill),
                    fact_ids=hook_facts, big=hook_big)]

    body = [f for f in facts if f.id not in hook_facts and not f.derived]
    connectors = CONNECTORS[:]
    rng.shuffle(connectors)

    if fmt in ("countdown", "launch_recap"):
        # release_date is implied by the countdown hook; keep it only if there's room.
        for f in body:
            if f.status == "rumor":
                scenes.append(Scene(kind="rumor", narration=_line(f, rng), on_screen=f.short, fact_ids=[f.id]))
            else:
                scenes.append(_point(f, rng))
    elif fmt == "confirmed_vs_rumor":
        for f in body:
            if f.status == "rumor":
                line = _line(f, rng)
                if "rumor" not in line.lower()[:25]:
                    line = "Now the rumor. " + line
                scenes.append(Scene(kind="rumor", narration=line, on_screen=f.short, fact_ids=[f.id]))
            else:
                scenes.append(_point(f, rng, prefix="Confirmed."))
    elif fmt in ("top3", "by_the_numbers"):
        for n, f in zip((3, 2, 1), body[:3]):
            big = f"#{n}" if fmt == "top3" else BIG.get(f.id, "")
            scene = _point(f, rng, prefix=f"Number {n}." if fmt == "top3" else connectors.pop(),
                           kind="number", big=big)
            if fmt == "by_the_numbers" and big:
                scene.on_screen = NUMBER_CONTEXT.get(f.id, f.short)
            scenes.append(scene)
    elif fmt == "myth_buster":
        myth = next(f for f in body if f.status == "debunked")
        truth = pool[myth.rebuttal]
        scenes.append(Scene(kind="myth", narration=f"The myth: {myth.claim}", on_screen=myth.short,
                            fact_ids=[myth.id]))
        scenes.append(Scene(kind="point", narration="False. " + _line(truth, rng), on_screen=truth.short,
                            fact_ids=[truth.id]))
        if "release_date" in pool:
            scenes.append(_point(pool["release_date"], rng, prefix="So for now:"))
    elif fmt == "region_spotlight":
        main = pool[plan.theme]
        scenes.append(Scene(kind="point", narration=_line(main, rng),
                            on_screen=SCREEN_ALT.get(main.id, main.short), fact_ids=[main.id]))
        for f in body:
            if f.id != main.id:
                scenes.append(_point(f, rng, prefix=connectors.pop()))
    elif fmt == "then_vs_now":
        for f in body:
            scenes.append(_point(f, rng))
    elif fmt == "poll":
        scenes.append(Scene(kind="point", narration="Vice City, the Leonida Keys, or Grassrivers?",
                            on_screen="VICE CITY · KEYS · GRASSRIVERS", fact_ids=["six_regions"]))
        scenes.append(Scene(kind="point", narration="Or Port Gellhorn, Ambrosia, or Mount Kalaga National Park?",
                            on_screen="GELLHORN · AMBROSIA · KALAGA", fact_ids=["six_regions"]))
        for f in body:
            if f.id != "six_regions":
                scenes.append(_point(f, rng))
    else:
        for f in body:
            scenes.append(_point(f, rng))

    cta = rng.choice(CTAS.get(fmt, CTAS["top3"])).format(**fill)
    scenes.append(Scene(kind="cta", narration=cta, on_screen="COMMENT BELOW"))

    title = rng.choice(TITLES[fmt]).format(**fill)
    return Script(id=video_id, format=fmt, title=title, scenes=scenes, hook_pattern=pattern, provider="template")
