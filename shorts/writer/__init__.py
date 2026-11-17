"""Script writing with automatic fallback and verification.

Providers are tried in the order set in settings.yaml (writer.providers).
A script is only accepted once it passes the fact verifier and the
originality checks; otherwise the errors are fed back for one more attempt,
then the next provider is tried. The offline template writer is last.
"""
from __future__ import annotations

import datetime as dt
import logging
import random

from ..models import Fact, Issue, Scene, Script
from ..originality import check_originality
from ..topics import Plan
from ..usage import Usage
from ..verify import assign_badges, passed, verify_script
from .llm import ProviderUnavailable, build_prompt, complete, extract_json
from .templates import write_from_template

log = logging.getLogger(__name__)


def _check(script: Script, pool, all_facts, today, history, settings) -> list[Issue]:
    o = settings["originality"]
    v = settings["video"]
    issues = verify_script(script, pool, all_facts, today,
                           min_words=int(v["min_seconds"] * 2.3), max_words=int(v["max_seconds"] * 2.6))
    issues += check_originality(script, history, o["max_similarity"], o["hook_cooldown"], o["format_cooldown"])
    return issues


def write_script(plan: Plan, pool: dict[str, Fact], all_facts: dict[str, Fact], video_id: str,
                 settings: dict, history: list[dict], today: dt.date, usage: Usage | None = None,
                 rng: random.Random | None = None) -> tuple[Script, list[Issue], list[str]]:
    """Returns (script, issues of the accepted script, log lines describing what happened)."""
    rng = rng or random.Random(video_id)
    trail: list[str] = []
    recent_hooks = [h.get("hook", "") for h in history[-settings["originality"]["hook_cooldown"]:]]
    recent_patterns = {h.get("hook_pattern", "") for h in history[-settings["originality"]["hook_cooldown"]:]}
    channel = settings["channel"]["name"]
    attempts = int(settings["writer"].get("max_attempts_per_provider", 2))

    for provider in settings["writer"]["providers"]:
        if provider == "template":
            for attempt in range(6):  # different random picks until originality passes
                script = write_from_template(plan, pool, video_id, rng, avoid_hooks=recent_patterns)
                assign_badges(script, pool)
                issues = _check(script, pool, all_facts, today, history, settings)
                if passed(issues):
                    trail.append(f"template: accepted on attempt {attempt + 1}")
                    return script, issues, trail
                trail.append(f"template attempt {attempt + 1} rejected: " + "; ".join(map(str, issues))[:300])
            return script, issues, trail  # caller decides (QC will flag it)

        feedback: list[str] | None = None
        for attempt in range(attempts):
            try:
                if usage and not usage.allows(settings, "llm_requests", "llm_requests_per_day"):
                    raise ProviderUnavailable("daily AI request budget used up")
                prompt = build_prompt(plan, pool, channel, recent_hooks, feedback, today.isoformat())
                raw = complete(provider, prompt, settings)
                if usage:
                    usage.add("llm_requests", 1, sub=provider)
                data = extract_json(raw)
                script = Script(id=video_id, format=plan.format, title=str(data.get("title", "")).strip(),
                                scenes=[Scene.from_dict(s) for s in data.get("scenes", [])],
                                hook_pattern=f"{provider}:{data.get('hook_pattern', 'llm')}", provider=provider)
                assign_badges(script, pool)
                issues = _check(script, pool, all_facts, today, history, settings)
                if passed(issues):
                    trail.append(f"{provider}: accepted on attempt {attempt + 1}")
                    return script, issues, trail
                feedback = [i.message for i in issues if i.level == "error"]
                trail.append(f"{provider} attempt {attempt + 1} rejected: " + "; ".join(feedback)[:300])
            except ProviderUnavailable as exc:
                trail.append(f"{provider}: skipped ({exc})")
                break
            except Exception as exc:  # network errors, bad JSON, timeouts – try again / next provider
                trail.append(f"{provider}: error ({type(exc).__name__}: {str(exc)[:160]})")
                log.warning("writer %s failed: %s", provider, exc)
    raise RuntimeError("no writer produced a valid script:\n" + "\n".join(trail))
