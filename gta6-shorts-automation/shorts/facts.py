"""Loading, validating and querying the verified facts database (data/facts.yaml)."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import yaml

from .config import Paths
from .models import STATUSES, Fact, Issue, Source

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")


def _to_date(value) -> dt.date | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def load_facts(path: str | Path | None = None) -> dict[str, Fact]:
    p = Path(path) if path else Paths().facts
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    facts: dict[str, Fact] = {}
    for item in raw.get("facts", []):
        fact = Fact(
            id=str(item["id"]),
            claim=str(item["claim"]).strip(),
            status=str(item.get("status", "")).strip(),
            short=str(item.get("short", "")).strip(),
            topics=list(item.get("topics") or []),
            sources=[Source(name=str(s.get("name", "")), url=str(s.get("url", "")),
                            official=bool(s.get("official", False))) for s in item.get("sources") or []],
            verified_on=_to_date(item.get("verified_on")),
            review_after_days=int(item.get("review_after_days", 30)),
            valid_until=_to_date(item.get("valid_until")),
            rebuttal=item.get("rebuttal"),
        )
        if fact.id in facts:
            raise ValueError(f"Duplicate fact id: {fact.id}")
        facts[fact.id] = fact
    return facts


def validate_facts(facts: dict[str, Fact], today: dt.date) -> list[Issue]:
    """Structural checks plus freshness warnings. Errors here stop the pipeline."""
    issues: list[Issue] = []
    for f in facts.values():
        if f.status not in STATUSES:
            issues.append(Issue("error", "bad_status", f"{f.id}: status '{f.status}' must be one of {STATUSES}"))
        if not f.sources:
            issues.append(Issue("error", "no_source", f"{f.id}: every fact needs at least one source"))
        for s in f.sources:
            if not s.url.startswith(("http://", "https://")):
                issues.append(Issue("error", "bad_url", f"{f.id}: source URL '{s.url}' is not a web link"))
        if f.verified_on is None:
            issues.append(Issue("error", "no_date", f"{f.id}: verified_on is missing"))
        if f.status == "debunked":
            if not f.rebuttal or f.rebuttal not in facts:
                issues.append(Issue("error", "no_rebuttal", f"{f.id}: debunked facts need a 'rebuttal' fact id"))
        if len(f.short) > 28:
            issues.append(Issue("warning", "long_short", f"{f.id}: 'short' is {len(f.short)} chars; keep it under 28"))
        if f.is_stale(today) and not f.is_expired(today):
            issues.append(Issue("warning", "stale", f"{f.id}: last verified {f.verified_on}, needs re-checking"))
    return issues


def release_date(facts: dict[str, Fact]) -> dt.date | None:
    """Parse the launch date out of the release_date fact (single source of truth)."""
    f = facts.get("release_date")
    if not f:
        return None
    m = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)"
                  r"\s+(\d{1,2}),\s+(\d{4})", f.claim)
    if not m:
        return None
    month = _MONTHS.index(m.group(1).lower()) + 1
    return dt.date(int(m.group(3)), month, int(m.group(2)))


def derived_facts(facts: dict[str, Fact], today: dt.date) -> dict[str, Fact]:
    """Facts computed from other facts at run time, e.g. 'launches in 2 days'."""
    out: dict[str, Fact] = {}
    base = facts.get("release_date")
    launch = release_date(facts)
    if base and launch and base.usable(today):
        days = (launch - today).days
        if days > 1:
            out["days_until_release"] = Fact(
                id="days_until_release", claim=f"GTA VI launches in {days} days.", short=f"{days} DAYS LEFT",
                status="confirmed", topics=["countdown"], sources=base.sources, verified_on=today,
                review_after_days=0, derived=True)
        elif days == 1:
            out["days_until_release"] = Fact(
                id="days_until_release", claim="GTA VI launches tomorrow, in 1 day.", short="1 DAY LEFT",
                status="confirmed", topics=["countdown"], sources=base.sources, verified_on=today,
                review_after_days=0, derived=True)
        elif days == 0:
            out["days_since_release"] = Fact(
                id="days_since_release", claim="GTA VI is out today, launch day.", short="LAUNCH DAY",
                status="confirmed", topics=["post_launch"], sources=base.sources, verified_on=today,
                review_after_days=0, derived=True)
        else:
            n = -days
            out["days_since_release"] = Fact(
                id="days_since_release", claim=f"GTA VI has been out for {n} day{'s' if n != 1 else ''}.",
                short=f"DAY {n + 1}", status="confirmed", topics=["post_launch"],
                sources=base.sources, verified_on=today, review_after_days=0, derived=True)
    return out


def usable_facts(facts: dict[str, Fact], today: dt.date) -> dict[str, Fact]:
    pool = {k: v for k, v in facts.items() if v.usable(today)}
    pool.update(derived_facts(facts, today))
    return pool


def numbers_in(text: str) -> set[str]:
    """Numbers as they appear in text, normalised ('79.99', '2026', '93')."""
    return {n.replace(",", "") for n in _NUM_RE.findall(text)}


def by_topic(facts: dict[str, Fact], topic: str) -> list[Fact]:
    return [f for f in facts.values() if topic in f.topics]
