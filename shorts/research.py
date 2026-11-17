"""News discovery and the human fact-review loop.

1. `discover()` reads free RSS feeds (config/sources.yaml), keeps fresh GTA 6
   headlines, labels each by source type and drafts a neutral claim.
2. The candidates are posted as a checklist issue ("fact-review").
3. You tick the ones that are correct (and may edit the claim text first).
4. `apply_review()` turns ticked items into entries in data/facts.yaml.
Nothing from the news reaches a video without passing through step 3, unless
you enable research.auto_approve_official_sources.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml

from .config import Paths, get, today
from .writer.llm import ProviderUnavailable, complete, extract_json

UA = {"User-Agent": "gta6-shorts-automation/1.0 (+https://github.com)"}
LINE_RE = re.compile(r"^- \[(?P<tick>[ xX])\] `?(?P<id>fc-[\w-]+)`? \| (?P<status>confirmed|reported|rumor) \| "
                     r"(?P<claim>.+?) \| (?P<short>.*?) \| (?P<url>https?://\S+)\s*$")


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def parse_rss(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for it in root.iter("item"):
        src = it.find("source")
        pub = it.findtext("pubDate") or ""
        try:
            published = email.utils.parsedate_to_datetime(pub).astimezone(dt.timezone.utc).isoformat()
        except (TypeError, ValueError):
            published = ""
        title = (it.findtext("title") or "").strip()
        source_name = (src.text or "").strip() if src is not None else ""
        if source_name and title.endswith(f" - {source_name}"):
            title = title[: -len(source_name) - 3].strip()
        items.append({"title": title, "link": (it.findtext("link") or "").strip(), "published": published,
                      "source": source_name, "source_url": src.get("url", "") if src is not None else ""})
    return items


def classify(item: dict, sources_cfg: dict) -> str:
    domain = _domain(item.get("source_url") or item.get("link", ""))
    if any(domain.endswith(d) for d in sources_cfg.get("official_domains", [])):
        return "confirmed"
    if any(domain.endswith(d) for d in sources_cfg.get("trusted_press_domains", [])):
        return "reported"
    return "rumor"


def relevant(item: dict, sources_cfg: dict) -> bool:
    text = item["title"].lower()
    if not any(k in text for k in sources_cfg.get("keywords", [])):
        return False
    return not any(b in text for b in sources_cfg.get("blocked_keywords", []))


def draft_claims(cands: list[dict], settings: dict) -> None:
    """Ask the first available LLM to rewrite headlines as neutral claims (falls back to the headline)."""
    for c in cands:
        c["claim"] = re.sub(r"\s+", " ", c["title"]).strip().rstrip(".") + "."
        c["short"] = " ".join(c["title"].upper().split()[:4])[:26]
    prompt = ("Rewrite each headline as ONE neutral, factual sentence a narrator could read, without hype, "
              "without adding information. Also give a 2-4 word ALL-CAPS on-screen label. "
              "Reply as JSON {\"items\": [{\"id\": ..., \"claim\": ..., \"short\": ...}]}.\n\n" +
              json.dumps([{"id": c["id"], "headline": c["title"]} for c in cands], ensure_ascii=False))
    for provider in settings["writer"]["providers"]:
        if provider == "template":
            break
        try:
            data = extract_json(complete(provider, prompt, settings))
            by_id = {x["id"]: x for x in data.get("items", [])}
            for c in cands:
                if c["id"] in by_id:
                    c["claim"] = str(by_id[c["id"]].get("claim", c["claim"])).replace("|", "/")
                    c["short"] = str(by_id[c["id"]].get("short", c["short"])).upper().replace("|", "/")[:26]
            return
        except ProviderUnavailable:
            continue
        except Exception:
            continue


def discover(settings: dict, paths: Paths | None = None, fetch=None) -> list[dict]:
    paths = paths or Paths()
    cfg = yaml.safe_load(paths.sources.read_text(encoding="utf-8")) or {}
    store = json.loads(paths.fact_candidates.read_text(encoding="utf-8")) if paths.fact_candidates.exists() \
        else {"candidates": [], "seen": []}
    seen = set(store.get("seen", []))
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=int(get(settings, "research.news_lookback_hours", 36)))
    fetch = fetch or (lambda url: requests.get(url, headers=UA, timeout=30).text)
    new: list[dict] = []
    for feed in cfg.get("feeds", []):
        try:
            items = parse_rss(fetch(feed["url"]))
        except Exception:
            continue
        for item in items:
            key = re.sub(r"[^a-z0-9]+", " ", item["title"].lower()).strip()
            if key in seen or not relevant(item, cfg):
                continue
            if item["published"] and dt.datetime.fromisoformat(item["published"]) < cutoff:
                continue
            seen.add(key)
            status = "confirmed" if feed.get("official") else classify(item, cfg)
            new.append({**item, "id": f"fc-{today().strftime('%Y%m%d')}-{len(new) + 1}", "status": status,
                        "state": "pending"})
    if new:
        draft_claims(new, settings)
    store["candidates"] = (store.get("candidates", []) + new)[-300:]
    store["seen"] = list(seen)[-2000:]
    paths.fact_candidates.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")
    return new


def review_issue_body(cands: list[dict]) -> str:
    lines = ["New GTA 6 headlines found. **Tick only what is true.** You can edit the claim, status or "
             "on-screen label in a line before ticking (keep the ` | ` separators).", "",
             "status: `confirmed` = official Rockstar/Take-Two · `reported` = reputable press, will be attributed · "
             "`rumor` = will be labelled RUMOR", "", "Format: `id | status | claim | on-screen label | source`", ""]
    for c in cands:
        lines.append(f"- [ ] `{c['id']}` | {c['status']} | {c['claim']} | {c['short']} | {c['link']}")
    lines += ["", "_Saving the issue applies ticked items to `data/facts.yaml` automatically._",
              "<!-- fact-review -->"]
    return "\n".join(lines)


def parse_review(body: str) -> list[dict]:
    out = []
    for line in body.splitlines():
        m = LINE_RE.match(line.strip())
        if m and m.group("tick").lower() == "x":
            out.append({k: m.group(k).strip() for k in ("id", "status", "claim", "short", "url")})
    return out


def _yaml_block(item: dict) -> str:
    review = 7 if item["status"] == "rumor" else 30
    name = _domain(item["url"])
    fact = {"id": item["id"].replace("-", "_"), "claim": item["claim"], "short": item["short"][:28],
            "status": item["status"], "topics": ["news"], "verified_on": today().isoformat(),
            "review_after_days": review,
            "sources": [{"name": name, "url": item["url"], **({"official": True} if item["status"] == "confirmed"
                                                              else {})}]}
    dumped = yaml.safe_dump([fact], sort_keys=False, allow_unicode=True, width=120)
    return "\n".join("  " + ln if ln else ln for ln in dumped.splitlines()) + "\n"


def apply_review(body: str, paths: Paths | None = None) -> list[str]:
    paths = paths or Paths()
    ticked = parse_review(body)
    if not ticked:
        return []
    existing = yaml.safe_load(paths.facts.read_text(encoding="utf-8")) or {}
    ids = {f["id"] for f in existing.get("facts", [])}
    added = []
    text = paths.facts.read_text(encoding="utf-8").rstrip("\n") + "\n"
    for item in ticked:
        fid = item["id"].replace("-", "_")
        if fid in ids:
            continue
        text += "\n" + _yaml_block(item)
        added.append(fid)
    if added:
        Path(paths.facts).write_text(text, encoding="utf-8")
    if paths.fact_candidates.exists():
        store = json.loads(paths.fact_candidates.read_text(encoding="utf-8"))
        for c in store.get("candidates", []):
            if c["id"].replace("-", "_") in added:
                c["state"] = "approved"
        paths.fact_candidates.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")
    return added
