# GTA 6 Shorts Automation

A cloud pipeline that makes original, fact-checked GTA 6 videos for YouTube Shorts and TikTok. It runs on free GitHub Actions, so your PC can stay off, and it costs nothing beyond your Claude Pro plan.

Each day it does the following:

1. **Finds a topic.** It picks a format and facts from a verified facts database. A rotation rule stops the channel from repeating itself. New headlines from free RSS feeds go to you for a tick-box review.
2. **Writes an original script.** The writer is Claude via your Pro plan, Groq or Gemini (both free tiers), or an offline template writer as a fallback.
3. **Checks every claim against the facts database.** Invented numbers, uncited claims, stale facts, unlabelled rumours and repeated hooks are all rejected.
4. **Records an energetic AI voice.** It uses Kokoro, an open-source model that runs on the free cloud CPU. It is an original voice and does not clone anyone.
5. **Animates a 1080×1920 video with FFmpeg.** The motion graphics are original: neon backgrounds, word-by-word captions, CONFIRMED/RUMOR badges, source labels, a progress bar, sound effects and generated music.
6. **Runs quality control.** It checks resolution, length, −14 LUFS loudness, dead air, black frames, caption coverage, hook speed and A/V sync.
7. **Opens a review issue** with a preview, the full fact check and the upload text.
8. **Publishes, depending on the stage.** In Stage 3 it publishes after you approve. In Stage 4 it publishes automatically. It then collects stats, posts a daily report and updates the dashboard.

> **Nothing is published now.** The project ships in **Stage 2 (testing)**: `publishing.enabled: false`, `dry_run: true`, and the publish gate refuses everything below Stage 3.

## What's tested and what isn't

| Part | Status |
|---|---|
| Facts DB, verifier, rumour labelling, originality checks | ✅ Tested here (54 automated tests) |
| Template script writer (9 formats) | ✅ Tested, every format passes verification across seeds |
| Voice text normalisation, word timing, captions | ✅ Tested |
| Renderer (4 backgrounds, 5 palettes, 3 caption styles, 4 transitions), audio mix, music, loudness | ✅ Tested: real 1080×1920 renders pass every QC check |
| QC module, publish gate, metadata, review issue text | ✅ Tested |
| YouTube upload/stats client | ⚠️ Unit-tested against a fake server. **Not yet run against your channel** (needs your Google credentials, Stage 3) |
| Kokoro production voice | ⚠️ Code written, **not run here**: this workspace couldn't download the model. The first GitHub run will use it. The sample video uses the robotic *test* voice |
| Claude / Groq / Gemini writers | ⚠️ Fallback logic tested with simulated replies. **Real calls need your token/keys** |
| GitHub Actions workflows, Pages dashboard deploy | ⚠️ Written and syntax-checked. **They run for the first time in your repo** |
| RSS discovery | ⚠️ Parsing/filtering tested on a saved feed. Live fetching runs in the cloud |
| TikTok upload/stats | ⏸️ Client written, disabled. It needs TikTok to approve a developer app first |
| Dashboard | ✅ Rendered and checked on desktop and mobile, light and dark, with demo data |

## Quick start

1. Follow **[docs/SETUP.md](docs/SETUP.md)**. It takes about 30 minutes, nothing to install, and you can do it all in the browser.
2. Run **Actions → Create video → Run workflow**. A review issue appears with your first Kokoro-voiced video.
3. Read **[docs/OPERATIONS.md](docs/OPERATIONS.md)** for the 2-minute daily routine.

Locally (optional, needs Python 3.12 and FFmpeg):

```bash
pip install -r requirements.txt            # + requirements-voice.txt for Kokoro
python -m shorts facts                     # validate the facts database
python -m shorts create --tts flite        # make a test video into out/
python -m shorts dashboard --demo          # build site/ with demo numbers
pytest -q
```

## Stages

| Stage | What happens | How to enter |
|---|---|---|
| 1 Foundation | Code, docs, tests | ✅ done |
| **2 Testing** ← now | Daily videos + review issues, **no publishing** | default |
| 3 Publishing with approval | Adding the `approved` label uploads (start with `privacy: private`) | `stage: 3`, `publishing.enabled: true`, `dry_run: false`, `youtube.enabled: true` |
| 4 Full automation | Videos that pass every check upload automatically, within daily caps | `stage: 4`, `require_approval: false` |

## Cost: 0 DKK

Free GitHub Actions minutes (unlimited on public repos), free GitHub Pages, free YouTube Data API quota and open-source tools: FFmpeg, Kokoro, Python and the bundled Poppins font. The script writer uses your existing Claude Pro plan (through Claude Code) or a free tier. See [docs/FREE_TIER_LIMITS.md](docs/FREE_TIER_LIMITS.md) for every limit and how it's monitored.

## Documentation

- [docs/SETUP.md](docs/SETUP.md): accounts, secrets, first run
- [docs/OPERATIONS.md](docs/OPERATIONS.md): reviewing, approving, adding facts, troubleshooting
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): how it works and why
- [docs/CONTENT_POLICY.md](docs/CONTENT_POLICY.md): copyright, facts, rumours, platform rules
- [docs/FREE_TIER_LIMITS.md](docs/FREE_TIER_LIMITS.md): limits and monitoring

*Fan project. Not affiliated with or endorsed by Rockstar Games or Take-Two Interactive.*
