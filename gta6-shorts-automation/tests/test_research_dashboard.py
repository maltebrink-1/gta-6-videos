import json
from pathlib import Path

import yaml

from shorts.dashboard import build_data, demo_data
from shorts.facts import load_facts, validate_facts
from shorts.research import apply_review, discover, parse_review, parse_rss, review_issue_body
from shorts.usage import Usage

FIXTURE = (Path(__file__).parent / "fixtures" / "news.xml").read_text(encoding="utf-8")


def test_rss_parsing_strips_source_suffix():
    items = parse_rss(FIXTURE)
    assert items[0]["title"] == "Rockstar shares GTA VI launch trailer"
    assert items[1]["source_url"] == "https://www.ign.com"


def test_discover_filters_and_classifies(settings, tmp_paths, monkeypatch):
    import datetime as dt
    monkeypatch.setattr("shorts.research.dt.datetime", type("D", (dt.datetime,), {
        "now": classmethod(lambda cls, tz=None: dt.datetime(2026, 11, 17, 12, tzinfo=dt.timezone.utc))}))
    sources = {"feeds": [{"name": "n", "url": "https://example/rss", "official": False}],
               "official_domains": ["rockstargames.com"], "trusted_press_domains": ["ign.com"],
               "keywords": ["gta 6", "gta vi"], "blocked_keywords": ["free download", "apk"]}
    tmp_paths.sources = tmp_paths.data / "sources.yaml"
    tmp_paths.sources.write_text(yaml.safe_dump(sources))
    new = discover(settings, tmp_paths, fetch=lambda url: FIXTURE)
    by_title = {c["title"]: c["status"] for c in new}
    assert by_title["Rockstar shares GTA VI launch trailer"] == "confirmed"
    assert by_title["GTA 6 reviews are in: here is the Metacritic score"] == "reported"
    assert by_title["Leaker claims GTA 6 PC port is coming in 2027"] == "rumor"
    assert not any("apk" in t or "pizza" in t.lower() or "Old" in t for t in by_title)
    assert discover(settings, tmp_paths, fetch=lambda url: FIXTURE) == []   # already seen


def test_review_roundtrip_adds_valid_facts(tmp_paths, today):
    cands = [{"id": "fc-20261117-1", "status": "reported", "claim": "IGN published its GTA 6 review.",
              "short": "IGN REVIEW IS OUT", "link": "https://www.ign.com/gta6-review"},
             {"id": "fc-20261117-2", "status": "rumor", "claim": "A leaker claims a 2027 PC port.",
              "short": "PC IN 2027?", "link": "https://randomblog.example/x"}]
    body = review_issue_body(cands).replace("- [ ] `fc-20261117-1`", "- [x] `fc-20261117-1`")
    assert [x["id"] for x in parse_review(body)] == ["fc-20261117-1"]
    added = apply_review(body, tmp_paths)
    assert added == ["fc_20261117_1"]
    facts = load_facts(tmp_paths.facts)
    assert facts["fc_20261117_1"].status == "reported"
    assert not [i for i in validate_facts(facts, today) if i.level == "error"]
    assert apply_review(body, tmp_paths) == []   # idempotent


def test_dashboard_data_empty_and_demo(settings, tmp_paths):
    data = build_data(settings, tmp_paths)
    assert data["totals"]["created"] == 0 and len(data["daily"]) == 30
    assert data["platforms"]["youtube"]["connected"] is False
    demo = demo_data(settings)
    assert demo["demo"] and len(demo["daily"]) == 30 and demo["weekly"][-1]["partial"] is True
    assert all(w["days"] == 7 for w in demo["weekly"][:-1])
    json.dumps(demo)


def test_usage_meters_warn(settings, tmp_paths):
    u = Usage(tmp_paths.usage)
    u.add("llm_requests", 35, sub="groq")
    meters = {m["name"]: m for m in u.meters(settings)}
    assert meters["AI writer requests today"]["status"] == "warn"
    assert not u.allows(settings, "llm_requests", "llm_requests_per_day", needed=6)
