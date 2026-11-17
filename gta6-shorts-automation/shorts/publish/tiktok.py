"""TikTok Content Posting API client – only usable once TikTok approves your app.

Modes (settings.publishing.tiktok.mode):
  inbox  – scope video.upload: the video lands in your TikTok inbox as a draft and
           you tap "post" in the app. Needs app review for the scope.
  direct – scope video.publish: posts directly. Until TikTok audits your app,
           every post is forced to private (SELF_ONLY) and the account must be private.

Secrets: TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REFRESH_TOKEN
STATUS: written from TikTok's public docs; NOT tested (needs an approved app).
"""
from __future__ import annotations

import time
from pathlib import Path

import requests

from ..config import secret

BASE = "https://open.tiktokapis.com/v2"


class TikTokNotConfigured(RuntimeError):
    pass


class TikTokClient:
    def __init__(self, session: requests.Session | None = None):
        self.key = secret("TIKTOK_CLIENT_KEY")
        self.secret = secret("TIKTOK_CLIENT_SECRET")
        self.refresh_token = secret("TIKTOK_REFRESH_TOKEN")
        if not (self.key and self.secret and self.refresh_token):
            raise TikTokNotConfigured("TikTok secrets are not set – TikTok publishing needs an approved developer "
                                      "app first (docs/SETUP.md, TikTok section)")
        self.http = session or requests.Session()
        self._token: str | None = None
        self.new_refresh_token: str | None = None

    def token(self) -> str:
        if self._token:
            return self._token
        r = self.http.post(f"{BASE}/oauth/token/", timeout=30,
                           headers={"Content-Type": "application/x-www-form-urlencoded"},
                           data={"client_key": self.key, "client_secret": self.secret,
                                 "grant_type": "refresh_token", "refresh_token": self.refresh_token})
        r.raise_for_status()
        data = r.json()
        if "access_token" not in data:
            raise TikTokNotConfigured(f"token refresh failed: {data}")
        self._token = data["access_token"]
        # TikTok may rotate the refresh token; the workflow warns you to update the secret.
        if data.get("refresh_token") and data["refresh_token"] != self.refresh_token:
            self.new_refresh_token = data["refresh_token"]
        return self._token

    def _post(self, path: str, payload: dict) -> dict:
        r = self.http.post(f"{BASE}{path}", json=payload, timeout=60,
                           headers={"Authorization": f"Bearer {self.token()}",
                                    "Content-Type": "application/json; charset=UTF-8"})
        data = r.json() if r.content else {}
        err = (data.get("error") or {}).get("code", "ok")
        if r.status_code >= 400 or err != "ok":
            raise RuntimeError(f"TikTok API {path} failed: {r.status_code} {data}")
        return data.get("data", {})

    def creator_info(self) -> dict:
        return self._post("/post/publish/creator_info/query/", {})

    def upload(self, video: str | Path, title: str, mode: str = "inbox", is_aigc: bool = True) -> dict:
        path = Path(video)
        size = path.stat().st_size
        if size > 64 * 1024 * 1024:
            raise ValueError("video larger than 64 MB – chunked upload not implemented")
        source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}
        if mode == "direct":
            info = self.creator_info()
            options = info.get("privacy_level_options") or ["SELF_ONLY"]
            privacy = "SELF_ONLY" if "SELF_ONLY" in options else options[0]
            init = self._post("/post/publish/video/init/", {
                "post_info": {"title": title[:2200], "privacy_level": privacy, "disable_duet": False,
                              "disable_comment": False, "disable_stitch": False, "is_aigc": is_aigc},
                "source_info": source})
        else:
            init = self._post("/post/publish/inbox/video/init/", {"source_info": source})
        with open(path, "rb") as fh:
            r = self.http.put(init["upload_url"], data=fh.read(), timeout=300,
                              headers={"Content-Type": "video/mp4", "Content-Length": str(size),
                                       "Content-Range": f"bytes 0-{size - 1}/{size}"})
        r.raise_for_status()
        publish_id = init["publish_id"]
        status: dict = {}
        for _ in range(20):
            status = self._post("/post/publish/status/fetch/", {"publish_id": publish_id})
            if status.get("status") in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE", "FAILED"):
                break
            time.sleep(6)
        return {"publish_id": publish_id, **status}

    def stats(self) -> dict:
        r = self.http.get(f"{BASE}/user/info/", params={"fields": "follower_count,likes_count,video_count"},
                          headers={"Authorization": f"Bearer {self.token()}"}, timeout=30)
        r.raise_for_status()
        return (r.json().get("data") or {}).get("user", {})
