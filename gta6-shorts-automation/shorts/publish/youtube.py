"""YouTube Data API v3 + YouTube Analytics API client (plain HTTPS, no SDK).

Secrets (GitHub → Settings → Secrets → Actions):
  YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
Scopes needed when you create the refresh token (see docs/SETUP.md):
  youtube.upload, youtube.readonly, yt-analytics.readonly

STATUS: written against the public API docs; NOT yet tested against your
channel. The first real call happens in Stage 3 with privacy=private.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from ..config import secret
from ..usage import Usage

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
CHUNK = 8 * 1024 * 1024


class YouTubeNotConfigured(RuntimeError):
    pass


class YouTubeClient:
    def __init__(self, usage: Usage | None = None, session: requests.Session | None = None):
        self.client_id = secret("YOUTUBE_CLIENT_ID")
        self.client_secret = secret("YOUTUBE_CLIENT_SECRET")
        self.refresh_token = secret("YOUTUBE_REFRESH_TOKEN")
        if not (self.client_id and self.client_secret and self.refresh_token):
            raise YouTubeNotConfigured("YouTube secrets are not set (see docs/SETUP.md, step 4)")
        self.http = session or requests.Session()
        self.usage = usage
        self._token: str | None = None
        self._expires = 0.0

    # ── auth ────────────────────────────────────────────────────────────────
    def token(self) -> str:
        if self._token and time.time() < self._expires - 60:
            return self._token
        r = self.http.post(TOKEN_URL, data={"client_id": self.client_id, "client_secret": self.client_secret,
                                            "refresh_token": self.refresh_token, "grant_type": "refresh_token"},
                           timeout=30)
        if r.status_code == 400 and "invalid_grant" in r.text:
            raise YouTubeNotConfigured("refresh token was rejected (expired or revoked). If your OAuth app is in "
                                       "'Testing' mode, tokens expire after 7 days – publish it to 'In production' "
                                       "and create a new token (docs/SETUP.md).")
        r.raise_for_status()
        data = r.json()
        self._token = data["access_token"]
        self._expires = time.time() + int(data.get("expires_in", 3600))
        return self._token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token()}"}

    def _get(self, url: str, params: dict, method_name: str) -> dict:
        for attempt in range(4):
            r = self.http.get(url, params=params, headers=self._headers(), timeout=60)
            if r.status_code in (500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            if self.usage and url.startswith(API):
                self.usage.youtube_call(method_name)
            r.raise_for_status()
            return r.json()
        r.raise_for_status()
        return {}

    # ── upload ──────────────────────────────────────────────────────────────
    def upload(self, video: str | Path, meta: dict, privacy: str = "private", publish_at: str | None = None,
               synthetic: bool = False, made_for_kids: bool = False) -> dict:
        path = Path(video)
        size = path.stat().st_size
        status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": made_for_kids,
                  "containsSyntheticMedia": synthetic}
        if publish_at:
            status.update(privacyStatus="private", publishAt=publish_at)
        body = {"snippet": {"title": meta["title"], "description": meta["description"], "tags": meta["tags"],
                            "categoryId": meta.get("category_id", "20"), "defaultLanguage": "en",
                            "defaultAudioLanguage": "en"},
                "status": status}
        init = self.http.post(UPLOAD, params={"uploadType": "resumable", "part": "snippet,status"},
                              headers={**self._headers(), "Content-Type": "application/json; charset=UTF-8",
                                       "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
                              data=json.dumps(body), timeout=60)
        init.raise_for_status()
        session_url = init.headers["Location"]
        offset = 0
        with open(path, "rb") as fh:
            while offset < size:
                fh.seek(offset)
                chunk = fh.read(CHUNK)
                end = offset + len(chunk) - 1
                for attempt in range(5):
                    r = self.http.put(session_url, data=chunk, timeout=300,
                                      headers={**self._headers(), "Content-Length": str(len(chunk)),
                                               "Content-Range": f"bytes {offset}-{end}/{size}"})
                    if r.status_code in (500, 502, 503, 504):
                        time.sleep(2 ** attempt)
                        continue
                    break
                if r.status_code in (200, 201):
                    if self.usage:
                        self.usage.youtube_call("videos.insert")
                    return r.json()
                if r.status_code == 308:
                    rng = r.headers.get("Range")
                    offset = int(rng.split("-")[1]) + 1 if rng else 0
                    continue
                r.raise_for_status()
        raise RuntimeError("upload ended without a final response")

    # ── stats ───────────────────────────────────────────────────────────────
    def video_stats(self, video_ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i + 50]
            data = self._get(f"{API}/videos", {"part": "statistics,status,snippet", "id": ",".join(batch)},
                             "videos.list")
            for item in data.get("items", []):
                st = item.get("statistics", {})
                out[item["id"]] = {"views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                                   "comments": int(st.get("commentCount", 0)),
                                   "privacy": item.get("status", {}).get("privacyStatus"),
                                   "title": item.get("snippet", {}).get("title")}
        return out

    def channel_stats(self) -> dict:
        data = self._get(f"{API}/channels", {"part": "statistics,snippet", "mine": "true"}, "channels.list")
        items = data.get("items", [])
        if not items:
            return {}
        st = items[0].get("statistics", {})
        return {"channel_id": items[0]["id"], "title": items[0].get("snippet", {}).get("title"),
                "subscribers": int(st.get("subscriberCount", 0)), "views": int(st.get("viewCount", 0)),
                "videos": int(st.get("videoCount", 0))}

    def daily_analytics(self, start: str, end: str) -> list[dict]:
        """Per-day views/likes/comments/subscribers for the channel (YouTube Analytics API)."""
        data = self._get(ANALYTICS, {"ids": "channel==MINE", "startDate": start, "endDate": end,
                                     "metrics": "views,likes,comments,subscribersGained,subscribersLost",
                                     "dimensions": "day", "sort": "day"}, "analytics")
        cols = [c["name"] for c in data.get("columnHeaders", [])]
        return [dict(zip(cols, row)) for row in data.get("rows", [])]
