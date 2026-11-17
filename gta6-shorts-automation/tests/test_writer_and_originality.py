import json
import random

import pytest

from shorts.models import Scene, Script
from shorts.originality import check_originality, similarity
from shorts.topics import FORMATS, candidates, choose_plan
from shorts.verify import passed
from shorts.writer import write_script
from shorts.writer import llm as llm_mod
from shorts.writer.llm import build_prompt, extract_json


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_every_template_format_passes_verification(seed, settings, pool, facts, today):
    plans = candidates(pool, random.Random(seed))
    assert {p.format for p in plans} >= {"countdown", "top3", "myth_buster", "poll"}
    for plan in plans:
        script, issues, _ = write_script(plan, pool, facts, f"s{seed}-{plan.format}", settings, [], today)
        assert passed(issues), (plan.format, [str(i) for i in issues])
        assert script.scenes[0].kind == "hook" and script.scenes[-1].kind == "cta"
        assert 45 <= script.word_count() <= 156


def test_format_rotation(pool, today):
    history = [{"format": "countdown", "fact_ids": []}, {"format": "countdown", "fact_ids": []}]
    plan = choose_plan(pool, history, today, random.Random(5), format_cooldown=2)
    assert plan.format != "countdown"


def test_repeated_script_is_blocked(settings, pool, facts, today):
    plan = choose_plan(pool, [], today, random.Random(1), forced_format="myth_buster")
    script, _, _ = write_script(plan, pool, facts, "a", settings, [], today)
    history = [{"id": "old", "narration": script.narration, "hook": script.scenes[0].narration,
                "hook_pattern": script.hook_pattern, "format": "myth_buster"}]
    issues = check_originality(script, history)
    assert {"too_similar", "hook_reused"} & {i.code for i in issues}
    assert similarity("a b c d e", "a b c d e") == 1.0


def test_extract_json_handles_fences_and_chatter():
    assert extract_json('Sure!\n```json\n{"title": "x", "scenes": []}\n```') == {"title": "x", "scenes": []}
    assert extract_json('blah {"a": 1} trailing')["a"] == 1


def test_prompt_contains_only_plan_facts(pool):
    plan = choose_plan(pool, [], None, random.Random(3), forced_format="myth_buster")
    prompt = build_prompt(plan, pool, "Leonida Daily", ["old hook"])
    assert "myth_pc_day_one" in prompt and "platforms" in prompt
    assert "price_us" not in prompt
    assert "Never imitate" in llm_mod.SYSTEM


def test_llm_errors_are_fed_back_then_fallback(monkeypatch, settings, pool, facts, today):
    """First reply invents a number (rejected), second is valid -> accepted from the LLM."""
    settings["writer"]["providers"] = ["groq", "template"]
    plan = choose_plan(pool, [], today, random.Random(2), forced_format="myth_buster")
    good = {"title": "GTA 6 myth busted", "hook_pattern": "q", "scenes": [
        {"kind": "hook", "narration": "Think GTA 6 is on PC at launch? Think again.", "on_screen": "PC AT LAUNCH?",
         "fact_ids": []},
        {"kind": "myth", "narration": "The myth: GTA 6 launches on PC on day one. That one's fake.",
         "on_screen": "THE MYTH", "fact_ids": ["myth_pc_day_one"]},
        {"kind": "point", "narration": "False. It launches on PlayStation 5 and Xbox Series X|S. A PC version "
                                       "hasn't been announced at all.", "on_screen": "CONSOLES ONLY",
         "fact_ids": ["platforms"]},
        {"kind": "cta", "narration": "Did you fall for that one? Be honest in the comments below.",
         "on_screen": "COMMENT", "fact_ids": []}]}
    bad = json.loads(json.dumps(good))
    bad["scenes"][2]["narration"] = "False. It launches on PS5 and Xbox, and PC follows in 2027, trust me on it."
    replies = iter([json.dumps(bad), json.dumps(good)])
    prompts = []

    def fake_complete(provider, prompt, s):
        prompts.append(prompt)
        return next(replies)

    monkeypatch.setattr("shorts.writer.complete", fake_complete)
    monkeypatch.setenv("GROQ_API_KEY", "test")
    script, issues, trail = write_script(plan, pool, facts, "llm", settings, [], today)
    assert script.provider == "groq", trail
    assert "2027" in prompts[1] and "failed these checks" in prompts[1]
    assert passed(issues)


def test_unconfigured_providers_fall_back_to_template(settings, pool, facts, today):
    settings["writer"]["providers"] = ["claude_cli", "groq", "gemini", "template"]
    plan = choose_plan(pool, [], today, random.Random(1), forced_format="poll")
    script, issues, trail = write_script(plan, pool, facts, "fb", settings, [], today)
    assert script.provider == "template"
    assert any("skipped" in t for t in trail)


def test_all_formats_have_specs():
    for name, spec in FORMATS.items():
        assert spec["brief"] and spec["weight"] > 0, name


def test_script_roundtrip():
    s = Script(id="x", format="top3", title="t", scenes=[Scene("hook", "a", "B", ["c"], "", "1")])
    assert Script.from_dict(s.to_dict()).scenes[0].big == "1"
