# Setup

Everything happens in the browser. Your PC is only needed once, and only if you choose the Claude Pro writer (step 3a).

## 1. Create the GitHub repository (5 min)

1. Sign in to GitHub and create a **new repository**, e.g. `gta6-shorts`.
   - **Public (recommended):** Actions minutes are unlimited and the dashboard is hosted free on GitHub Pages.
     The trade-off is that the code, review issues and review videos are visible to anyone who finds the repo.
     Your channel stats are public on YouTube anyway, and secrets are never visible.
   - **Private:** 2,000 free Actions minutes a month, which is enough for about 2 videos a day (the usage monitor tracks it).
     GitHub Pages is not available for private repos on the free plan, so you get the daily report issue instead of the web dashboard.
2. Upload the project: **Add file → Upload files**, drag in the *contents* of the project folder, then commit.
   The `.github` folder must be included (it holds the workflows).
3. Go to **Settings → Actions → General** and set **Workflow permissions** to "Read and write permissions", then save.
4. Go to **Settings → Pages** and set **Source** to "GitHub Actions" (public repos only).

## 2. Run the first test (2 min)

**Actions → Create video → Run workflow → Run workflow.** After about 6–10 minutes:

- a **Review:** issue appears with a preview image, a link to the video, the QC checklist and the fact check
- the video is the first one using the real **Kokoro** voice

Then run **Actions → Daily stats, report & dashboard → Run workflow**. Your dashboard appears at
`https://<your-user>.github.io/<repo>/`. It shows zeros until videos are published.

> If the first run fails, open the run log. The step that failed tells you why.
> Most likely causes: the workflow permissions in step 1.3, or the Kokoro model download hitting a temporary network error (just re-run).

## 3. Give it a script writer (optional but recommended)

Without a writer key the pipeline still works using its offline template writer, but templates are less varied.
Add **one or more** of these under **Settings → Secrets and variables → Actions → New repository secret**.
They are tried in the order set by `writer.providers` in `config/settings.yaml`.

### 3a. Claude (uses your Claude Pro subscription, no extra cost)

Claude Code supports a long-lived token for exactly this (GitHub Actions):

1. On any computer with Node.js: `npm install -g @anthropic-ai/claude-code`, then run `claude setup-token` and log in with your Claude account.
2. Copy the token it prints. Add the secret **`CLAUDE_CODE_OAUTH_TOKEN`**.

Notes: each script uses a small amount of your normal Claude usage limits, shared with your own chats.
The token is long-lived and tied to your subscription. If it ever stops working (or your plan changes), run `claude setup-token` again and replace the secret.

### 3b. Groq (free tier, no card)

Create a key at console.groq.com and add it as the secret **`GROQ_API_KEY`**.
The default model is `llama-3.3-70b-versatile`; its free tier allows on the order of 1,000 requests a day, and we use a handful.

### 3c. Gemini (free tier, no card)

Create a key in Google AI Studio and add it as the secret **`GEMINI_API_KEY`**. Google changes free-tier limits often.
Check the current model name in AI Studio and set `writer.gemini_model` if `gemini-2.5-flash` is no longer offered.

## 4. Connect YouTube (when you're ready for Stage 3)

This gives the pipeline permission to upload to **your** channel and read its stats.

1. Go to **console.cloud.google.com** and create a project, e.g. "gta6-shorts".
2. Under **APIs & Services → Library**, enable **YouTube Data API v3** and **YouTube Analytics API**.
3. Under **Google Auth Platform → Branding/Audience** (the OAuth consent screen), choose user type **External** and fill in the app name and your e-mail.
   Then **Publish app → In production**.
   ⚠️ Do not leave it in *Testing*: Google expires Testing tokens after **7 days** and the pipeline would stop.
   As a personal-use app, it stays unverified. You'll click past a "Google hasn't verified this app" warning once.
4. Under **Clients → Create client**, choose type **Web application**. Add the authorised redirect URI
   `https://developers.google.com/oauthplayground`, create it, and copy the **Client ID** and **Client secret**.
5. Open **developers.google.com/oauthplayground**:
   - ⚙️ (top right) → tick **Use your own OAuth credentials** → paste the ID and secret.
   - In the left box, paste these scopes (space-separated) and click **Authorize APIs**:
     `https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/yt-analytics.readonly`
   - Sign in with the Google account **that owns the channel** → Advanced → continue.
   - Click **Exchange authorization code for tokens** and copy the **Refresh token**.
6. Add three repository secrets: **`YOUTUBE_CLIENT_ID`**, **`YOUTUBE_CLIENT_SECRET`**, **`YOUTUBE_REFRESH_TOKEN`**.
7. Run the stats workflow. The dashboard should now say "YouTube: Connected".

Prefer a script? Add `http://127.0.0.1:8765/` as a second redirect URI in step 4, then `python scripts/get_youtube_token.py` does step 5 on your PC (one time) and prints the three secrets.

### About private uploads

YouTube's current `videos.insert` documentation says uploads from unverified API projects are **not** restricted to private.
Older documentation said the opposite. That's why Stage 3 starts with `privacy: private`.
Approve one video, check it in YouTube Studio, then switch to `public`.
If YouTube marks it "locked as private", apply for the free YouTube API audit (Google Cloud console → YouTube API Services → audit form).

## 5. Turn on Stage 3 (publishing with your approval)

Edit `config/settings.yaml` in GitHub (pencil icon):

```yaml
stage: 3
publishing:
  enabled: true
  dry_run: false
  youtube:
    enabled: true
    privacy: private      # switch to public after your first check
```

From now on, adding the label **`approved`** to a review issue uploads that video. Adding **`rejected`** discards it.

## 6. TikTok (only after TikTok approves your app)

TikTok requires a reviewed developer app before any API posting. Until it passes TikTok's separate *audit*, API posts are forced to private and the account must be private.
The pipeline supports the gentler **inbox** mode: each video arrives in your TikTok inbox as a draft and you tap **Post**.

1. Create a developer account at developers.tiktok.com. Create an app with **Login Kit** and the **Content Posting API**.
   Request the scopes `user.info.basic`, `video.upload` (add `video.publish` and `user.info.stats` later).
2. TikTok asks for terms-of-service and privacy-policy URLs plus a demo video of the flow. Ask me and I'll prepare simple pages for your GitHub Pages site.
3. After approval, complete the OAuth login once to get a refresh token. Add the secrets **`TIKTOK_CLIENT_KEY`**, **`TIKTOK_CLIENT_SECRET`** and **`TIKTOK_REFRESH_TOKEN`**.
   Then set `publishing.tiktok.enabled: true`.

## 7. Stage 4 (full automation)

After a couple of weeks of approved videos you're happy with:

```yaml
stage: 4
publishing:
  require_approval: false
```

Review issues are still created, so you can read what was published and comment. Keep `max_videos_per_day` at 1–2.

## Secrets summary

| Secret | Needed for | Required? |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude writer (Pro plan) | optional |
| `GROQ_API_KEY` / `GEMINI_API_KEY` | free LLM writers | optional |
| `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` | upload + stats | Stage 3 |
| `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN` | TikTok | after approval |
