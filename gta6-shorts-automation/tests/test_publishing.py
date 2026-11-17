import json

import pytest

from shorts.publish.guard import can_publish
from shorts.publish.metadata import build_metadata
from shorts.publish.youtube import YouTubeClient, YouTubeNotConfigured

GOOD = {"id": "v1", "status": "approved", "voice": "kokoro", "qc": {"passed": True}}


def enable(settings, stage=3):
    settings["stage"] = stage
    settings["publishing"]["enabled"] = True
    settings["publishing"]["youtube"]["enabled"] = True
    return settings


def test_default_settings_block_everything(settings):
    ok, why = can_publish(GOOD, settings, "youtube", approved=True)
    assert not ok and "stage" in why


def test_stage3_needs_approval(settings):
    enable(settings, 3)
    assert not can_publish(GOOD, settings, "youtube", approved=False)[0]
    assert can_publish(GOOD, settings, "youtube", approved=True) == (True, "ok")


def test_stage4_without_approval_only_when_configured(settings):
    enable(settings, 4)
    assert not can_publish(GOOD, settings, "youtube", approved=False)[0]   # require_approval still true
    settings["publishing"]["require_approval"] = False
    assert can_publish(GOOD, settings, "youtube", approved=False)[0]


def test_test_voice_failed_qc_and_caps_block(settings):
    enable(settings, 3)
    assert not can_publish({**GOOD, "voice": "flite"}, settings, "youtube", True)[0]
    assert not can_publish({**GOOD, "qc": {"passed": False}}, settings, "youtube", True)[0]
    assert not can_publish(GOOD, settings, "youtube", True, uploads_today=2)[0]
    assert not can_publish(GOOD, settings, "tiktok", True)[0]   # TikTok disabled by default


def test_metadata_has_sources_disclaimers_and_limits(settings, pool):
    from shorts.models import Scene, Script
    s = Script(id="x", format="countdown", title="GTA 6 in 2 days", scenes=[
        Scene("hook", "GTA 6 is 2 days away.", "DAYS", ["days_until_release"]),
        Scene("rumor", "Insiders say reviews land Nov 18.", "REVIEWS?", ["review_embargo"])])
    meta = build_metadata(s, pool, settings)
    assert "Sources:" in meta["description"] and "rockstargames.com" in meta["description"]
    assert "unconfirmed" in meta["description"] and "AI-generated voice" in meta["description"]
    assert "Not affiliated" in meta["description"] and "#Shorts" in meta["description"]
    assert len(meta["title"]) <= 100 and sum(len(t) + 1 for t in meta["tags"]) <= 500


class FakeResp:
    def __init__(self, status, payload=None, headers=None, text=""):
        self.status_code, self._p, self.headers, self.text = status, payload or {}, headers or {}, text
        self.content = b"x"

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self):
        self.calls = []
        self.puts = 0

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        if "oauth2" in url:
            return FakeResp(200, {"access_token": "tok", "expires_in": 3600})
        return FakeResp(200, headers={"Location": "https://upload.example/session"})

    def put(self, url, **kw):
        self.calls.append(("PUT", url, kw))
        self.puts += 1
        if self.puts == 1:   # server says: got the first 3 bytes, resume after
            return FakeResp(308, headers={"Range": "bytes=0-2"})
        return FakeResp(200, {"id": "abc123", "status": {"privacyStatus": "private"}})

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        if url.endswith("/videos"):
            return FakeResp(200, {"items": [{"id": "abc123", "statistics": {"viewCount": "10", "likeCount": "2",
                                                                              "commentCount": "1"}}]})
        return FakeResp(200, {"items": [{"id": "UC1", "statistics": {"subscriberCount": "5"}}]})


def test_youtube_requires_secrets():
    with pytest.raises(YouTubeNotConfigured):
        YouTubeClient()


def test_youtube_resumable_upload_and_stats(monkeypatch, tmp_path):
    for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
        monkeypatch.setenv(k, "x")
    video = tmp_path / "v.mp4"
    video.write_bytes(b"0123456789")
    session = FakeSession()
    yt = YouTubeClient(session=session)
    res = yt.upload(video, {"title": "t", "description": "d", "tags": ["a"]}, privacy="private")
    assert res["id"] == "abc123"
    init = [c for c in session.calls if c[0] == "POST" and "upload" in c[1]][0]
    body = json.loads(init[2]["data"])
    assert body["status"]["privacyStatus"] == "private" and body["status"]["selfDeclaredMadeForKids"] is False
    puts = [c for c in session.calls if c[0] == "PUT"]
    assert puts[1][2]["headers"]["Content-Range"] == "bytes 3-9/10"     # resumed after the 308
    assert yt.video_stats(["abc123"])["abc123"]["views"] == 10
    assert yt.channel_stats()["subscribers"] == 5


def test_publish_dry_run_never_uploads(settings, tmp_paths):
    from shorts.publish import publish_video
    from shorts.registry import Registry
    enable(settings, 3)
    reg = Registry(tmp_paths.registry)
    reg.add({**GOOD, "status": "awaiting_review"})
    reg.save()
    folder = tmp_paths.out / "v1"
    folder.mkdir(parents=True)
    (folder / "video.mp4").write_bytes(b"x")
    (folder / "metadata.json").write_text(json.dumps({"title": "t", "description": "d", "tags": []}))
    res = publish_video("v1", "youtube", True, settings, tmp_paths)
    assert res["ok"] and res["dry_run"]
