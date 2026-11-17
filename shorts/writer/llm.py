"""LLM script writers. All free options:

* claude_cli – Claude Code CLI using YOUR Claude Pro subscription
               (secret CLAUDE_CODE_OAUTH_TOKEN, made once with `claude setup-token`).
* groq       – Groq free tier, OpenAI-compatible API (secret GROQ_API_KEY).
* gemini     – Google AI Studio free tier, OpenAI-compatible API (secret GEMINI_API_KEY).

Every provider returns raw JSON text; the caller validates it with the fact
verifier, so a provider can never publish an unsupported claim.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import requests

from ..config import secret
from ..models import Fact
from ..topics import FORMATS, Plan


class ProviderUnavailable(RuntimeError):
    """Raised when a provider isn't configured (missing secret/CLI) – the next one is tried."""


SYSTEM = (
    "You write scripts for an English fan channel about Grand Theft Auto VI (YouTube Shorts and TikTok). "
    "Voice: an energetic, funny, original streamer-style narrator. Never imitate, name or reference a real "
    "streamer or creator, and never claim to be Rockstar. Family-friendly language, no slurs, no profanity. "
    "You ONLY state information contained in the facts you are given. You never invent numbers, dates, names, "
    "features or quotes. You answer with a single JSON object and nothing else."
)


def build_prompt(plan: Plan, pool: dict[str, Fact], channel: str, avoid_hooks: list[str],
                 feedback: list[str] | None = None, today: str = "") -> str:
    facts = [pool[i].to_prompt() for i in plan.fact_ids if i in pool]
    spec = FORMATS[plan.format]
    rules = [
        "Use ONLY the facts below. Every scene that states anything factual must list the ids it relies on "
        "in fact_ids. The hook and points cite facts; only the final call-to-action may have no fact_ids.",
        "Write numbers with digits exactly as they appear in the facts (e.g. $79.99, 93 million, 2026).",
        "status=rumor: the narration MUST say it is a rumour/unconfirmed/from insiders. Never in the title.",
        "status=reported: the narration MUST attribute it (e.g. 'according to', 'Rockstar says', 'reportedly').",
        "status=debunked: only call it a myth/false and then correct it with its rebuttal fact.",
        "Total narration 55–120 words (20–45 seconds). 4–7 scenes.",
        "Scene 1 is the hook: max 12 words, grabs attention instantly, kind='hook'.",
        "The last scene is kind='cta': one short question that invites comments, no facts.",
        "on_screen: 1–4 punchy words in CAPS for each scene. 'big': optional hero number like '2' or '#1'.",
        "Short sentences, contractions, rhetorical questions, real excitement. No emojis, no hashtags.",
        "Title: max 70 characters, curiosity-driven but honest, no rumours stated as fact, no ALL CAPS.",
        "Allowed scene kinds: hook, point, number, rumor, myth, cta.",
    ]
    if avoid_hooks:
        rules.append("Do NOT reuse or closely echo these recent hooks: " + " | ".join(avoid_hooks[-10:]))
    schema = {"title": "string", "hook_pattern": "short id describing your hook idea, e.g. 'question_vs'",
              "scenes": [{"kind": "hook|point|number|rumor|myth|cta", "narration": "string",
                          "on_screen": "STRING", "big": "optional string", "fact_ids": ["fact ids"]}]}
    parts = [
        f"Today's date: {today}. Use the right tense (a launch that has happened is in the past)." if today else "",
        f"Channel name: {channel}",
        f"Video format: {plan.format} – {spec['brief']}",
        "FACTS (JSON):\n" + json.dumps(facts, indent=1, ensure_ascii=False),
        "RULES:\n- " + "\n- ".join(rules),
        "Reply with JSON matching:\n" + json.dumps(schema, indent=1),
    ]
    if feedback:
        parts.append("Your previous attempt failed these checks, fix every one:\n- " + "\n- ".join(feedback))
    return "\n\n".join(p for p in parts if p)


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (handles ```json fences and chatter)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else text[text.find("{"): text.rfind("}") + 1]
    if not candidate:
        raise ValueError("no JSON object in model reply")
    return json.loads(candidate)


def call_claude_cli(prompt: str, model: str = "", timeout: int = 240) -> str:
    if not shutil.which("claude"):
        raise ProviderUnavailable("Claude Code CLI not installed")
    if not (secret("CLAUDE_CODE_OAUTH_TOKEN") or secret("ANTHROPIC_API_KEY")):
        raise ProviderUnavailable("CLAUDE_CODE_OAUTH_TOKEN secret not set")
    cmd = ["claude", "-p", f"{SYSTEM}\n\n{prompt}", "--output-format", "text"]
    if model:
        cmd += ["--model", model]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=os.environ.copy())
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def call_openai_compatible(prompt: str, base_url: str, api_key: str, model: str, temperature: float,
                           timeout: int = 90) -> str:
    resp = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "temperature": temperature,
              "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]},
        timeout=timeout,
    )
    if resp.status_code == 429:
        raise ProviderUnavailable("rate limited (free-tier limit reached)")
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def complete(provider: str, prompt: str, settings: dict) -> str:
    w = settings.get("writer", {})
    temperature = float(w.get("temperature", 0.9))
    if provider == "claude_cli":
        return call_claude_cli(prompt, model=w.get("claude_model", ""))
    if provider == "groq":
        key = secret("GROQ_API_KEY")
        if not key:
            raise ProviderUnavailable("GROQ_API_KEY secret not set")
        return call_openai_compatible(prompt, "https://api.groq.com/openai/v1", key,
                                      w.get("groq_model", "llama-3.3-70b-versatile"), temperature)
    if provider == "gemini":
        key = secret("GEMINI_API_KEY")
        if not key:
            raise ProviderUnavailable("GEMINI_API_KEY secret not set")
        return call_openai_compatible(prompt, "https://generativelanguage.googleapis.com/v1beta/openai", key,
                                      w.get("gemini_model", "gemini-2.5-flash"), temperature)
    raise ProviderUnavailable(f"unknown provider {provider}")
