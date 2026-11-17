# Operations: the daily routine

All of this works from the GitHub mobile app.

## Every day (about 2 minutes)

1. **Review issue** (label `video-review`). Tap **Watch the video**, skim the fact-check table and the QC list.
   - Stage 2: leave a comment if something's off. Close the issue when done.
   - Stage 3+: add the label **`approved`** to publish it, or **`rejected`** to discard it.
     The workflow comments with the result and closes the issue.
2. **Fact review issue** (label `fact-review`, when news appears). Tick only headlines you know are true.
   You may first edit the claim text or status in the line (keep the ` | ` separators).
   Saving the issue adds the ticked items to `data/facts.yaml` automatically.
3. **Daily report issue** (label `daily-report`): views, likes, comments, subscribers, best videos, free-tier meters and anything that needs attention.
   Yesterday's report is closed automatically.

## Keeping facts fresh (important around launch)

- Every fact has `verified_on` and `review_after_days`. When a fact goes stale, the pipeline **stops using it**, and the daily report lists it under "Needs attention".
- To re-verify: open `data/facts.yaml`, check the source link, then update `verified_on:` to today's date (or fix the claim).
- Launch-week facts (`release_date`, `release_time`) are set to go stale after 4 days on purpose. After 19 November the countdown format retires itself and the `launch_recap` format takes over once `release_date` is re-verified.
- Add facts by hand anytime with the same structure: `id`, `claim`, `short` (max ~28 chars), `status`, `topics`, `sources`, `verified_on`, `review_after_days`.

## Adjusting the channel (config/settings.yaml)

| Want to… | Change |
|---|---|
| Rename the on-screen channel tag | `channel.name` |
| Make more/fewer videos | `schedule.videos_per_run`, `schedule.max_videos_per_day` (keep ≤ 2) and the cron line in `.github/workflows/create-video.yml` |
| Change the voice | `voice.kokoro_voice` (e.g. `af_heart`, `am_michael`, or a blend `af_bella:60,af_heart:40`), `voice.speed` |
| Turn music off | `music.mode: off` |
| Use your own licensed music | put files in `assets/music/`, list them in `assets/music/LICENSES.yaml`, set `music.mode: licensed` |
| Prefer a different writer | reorder `writer.providers` |
| Force a format for one run | Actions → Create video → Run workflow → "format" |

## When something fails

| Symptom | What to do |
|---|---|
| Review issue labelled `qc-failed` | Read the ❌ lines in the issue. Most common: too short/long (writer), or a fact went stale. The next run tries a different topic. |
| "no writer produced a valid script" | The LLMs kept inventing facts and the template had nothing new to say. Usually all facts were used recently: add facts or wait a day. |
| YouTube "refresh token was rejected" | Your OAuth app was left in *Testing* (7-day tokens), or access was revoked. Fix the consent screen and repeat SETUP step 4.5. |
| Daily cap reached | Working as intended (`max_videos_per_day`). |
| Workflow didn't run on schedule | GitHub pauses scheduled workflows in repos with no activity for 60 days. This pipeline commits daily, so it shouldn't happen; if it does, re-enable it in the Actions tab. |
| Kokoro download failed | Temporary network issue: re-run the workflow. The model is cached after the first success. |

## Useful commands (local, optional)

```bash
python -m shorts facts                       # validate facts, list stale ones
python -m shorts create --format top3        # one video now
python -m shorts styles --out styles.jpg     # preview the visual styles
python -m shorts report                      # today's report in the terminal
python -m shorts usage                       # free-tier meters
```
