# Free-tier limits and how they're monitored

Checked 17 November 2026. Providers change these, so the pipeline reads its ceilings from `limits:` in `config/settings.yaml` and stops early instead of failing.

| Service | Free allowance | This pipeline's use | Monitored by |
|---|---|---|---|
| GitHub Actions, **public** repo | Standard runners free and unlimited | ~8–12 min per video, ~2 min stats, ~1 min research | – |
| GitHub Actions, **private** repo | 2,000 min/month (Free plan) | ~700 min/month at 2 videos/day | stats workflow sums billable minutes → `usage.json` → dashboard meter |
| GitHub Pages | Free for public repos (private repos need a paid plan) | 1 static page | – |
| Actions cache | 10 GB per repo | Kokoro model ~340 MB, pip cache | – |
| Artifacts | Retention set to 30 days | ~5–10 MB per video | – |
| YouTube Data API: `videos.insert` | Own bucket: **100 uploads/day**, 1 unit each (since June 2026) | ≤ 2/day | `youtube_uploads` meter, publish gate |
| YouTube Data API: everything else | 10,000 units/day | stats ≈ 2–10 units/day | `youtube_units` meter |
| YouTube Analytics API | Separate quota | 1 query/day | – |
| Claude Code (your Pro plan) | Your normal Pro usage limits | 1–3 short prompts/day | `llm_requests` meter (cap: `limits.llm_requests_per_day`) |
| Groq free tier | e.g. ~1,000 requests/day on 70B-class models (per model, per org) | 1–3/day | same meter, 429 → next provider |
| Gemini free tier | Varies (Google no longer publishes fixed numbers) | 1–3/day | same meter, 429 → next provider |
| Kokoro, FFmpeg, Flite, Python libraries | Open source | – | – |
| Google News RSS | Free | 2 feeds × 3/day | – |

## What happens near a limit

- At `warn_at_percent` (70 %) the dashboard meter turns orange and the daily report flags it.
- At 100 %, that part of the pipeline pauses until the counter resets. The LLM writer falls back to the next provider or the offline template writer, and uploads wait for the next day.
- **GitHub Models is not used.** GitHub retired it on 30 July 2026.

## Things that are not free and are not used

Paid TTS (ElevenLabs etc.), paid LLM APIs (Anthropic Console API keys are billed separately from Pro), stock footage subscriptions, paid hosting, third-party "social posting" services.
