import random
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shorts.config import Paths, load_settings  # noqa: E402
from shorts.facts import load_facts, usable_facts  # noqa: E402

TODAY = "2026-11-17"


@pytest.fixture(autouse=True)
def fixed_day(monkeypatch):
    """All tests run as if today were the day the facts were verified."""
    monkeypatch.setenv("SHORTS_TODAY", TODAY)
    for key in ("CLAUDE_CODE_OAUTH_TOKEN", "GROQ_API_KEY", "GEMINI_API_KEY", "YOUTUBE_CLIENT_ID",
                "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN", "TIKTOK_CLIENT_KEY"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def settings():
    s = load_settings()
    s["writer"]["providers"] = ["template"]
    return s


@pytest.fixture
def facts():
    return load_facts()


@pytest.fixture
def pool(facts):
    import datetime as dt
    return usable_facts(facts, dt.date.fromisoformat(TODAY))


@pytest.fixture
def today():
    import datetime as dt
    return dt.date.fromisoformat(TODAY)


@pytest.fixture
def tmp_paths(tmp_path):
    """Paths with data files redirected into a temp folder (repo data stays untouched)."""
    p = Paths()
    data = tmp_path / "data"
    data.mkdir()
    shutil.copy(p.facts, data / "facts.yaml")
    p.data = data
    p.facts = data / "facts.yaml"
    p.registry = data / "videos.json"
    p.usage = data / "usage.json"
    p.stats = data / "stats"
    p.reports = data / "reports"
    p.fact_candidates = data / "fact_candidates.json"
    p.out = tmp_path / "out"
    return p


@pytest.fixture
def rng():
    return random.Random(42)
