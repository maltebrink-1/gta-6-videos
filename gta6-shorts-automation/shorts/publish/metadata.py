"""Titles, descriptions and tags for uploads (with sources and disclosures)."""
from __future__ import annotations

from ..models import Fact, Script

TOPIC_TAGS = {"price": ["GTA 6 price"], "regions": ["GTA 6 map"], "world": ["GTA 6 map", "Leonida"],
              "trailers": ["GTA 6 trailer"], "release": ["GTA 6 release date"], "countdown": ["GTA 6 countdown"],
              "characters": ["Lucia", "Jason"], "myths": ["GTA 6 myths"], "vice_city": ["Vice City"]}


def build_metadata(script: Script, pool: dict[str, Fact], settings: dict) -> dict:
    channel = settings["channel"]
    facts = [pool[f] for f in script.fact_ids if f in pool]
    title = script.title.strip()
    if len(title) > 100:
        title = title[:97].rstrip() + "..."

    lines = [script.scenes[0].narration if script.scenes else title, ""]
    sources: list[tuple[str, str]] = []
    for f in facts:
        for s in f.sources[:2]:
            if s.url not in {u for _, u in sources}:
                sources.append((s.name, s.url))
    if sources:
        lines.append("Sources:")
        lines += [f"• {name}: {url}" for name, url in sources[:8]]
        lines.append("")
    if any(f.status == "rumor" for f in facts):
        lines.append("Anything marked RUMOR in this video is unconfirmed by Rockstar Games.")
    if any(f.status == "reported" for f in facts):
        lines.append("Claims marked REPORTED come from press coverage or company statements, as attributed.")
    lines.append("Narration: AI-generated voice (no real person's voice). Visuals: original motion graphics.")
    if channel.get("disclaimer"):
        lines.append(channel["disclaimer"])
    lines.append("")
    hashtags = ["#GTA6", "#GTAVI", "#Shorts"] + [h for h in script.hashtags if h.startswith("#")][:3]
    lines.append(" ".join(dict.fromkeys(hashtags)))
    description = "\n".join(lines)[:4900]

    tags = list(dict.fromkeys(settings["publishing"]["youtube"].get("tags", [])))
    for f in facts:
        for topic in f.topics:
            for tag in TOPIC_TAGS.get(topic, []):
                if tag not in tags:
                    tags.append(tag)
    while sum(len(t) + 1 for t in tags) > 480:   # YouTube allows ~500 characters of tags
        tags.pop()
    return {"title": title, "description": description, "tags": tags,
            "category_id": settings["publishing"]["youtube"].get("category_id", "20")}
