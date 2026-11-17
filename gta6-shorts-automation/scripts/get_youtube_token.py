"""One-time helper: get a YouTube refresh token on your own PC (alternative to the OAuth Playground).

Before running: in your Google Cloud OAuth client (type "Web application") add the
authorised redirect URI  http://127.0.0.1:8765/

Run:  python scripts/get_youtube_token.py
It opens your browser, you log in with the channel's Google account, and it
prints the three values to save as GitHub secrets. Uses only the standard library.
"""
from __future__ import annotations

import http.server
import json
import secrets
import urllib.parse
import urllib.request
import webbrowser

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly",
          "https://www.googleapis.com/auth/yt-analytics.readonly"]
REDIRECT = "http://127.0.0.1:8765/"


def main() -> None:
    client_id = input("Client ID: ").strip()
    client_secret = input("Client secret: ").strip()
    state = secrets.token_urlsafe(16)
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": REDIRECT, "response_type": "code", "scope": " ".join(SCOPES),
        "access_type": "offline", "prompt": "consent", "state": state})
    result: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            result.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Done - you can close this tab and go back to the terminal.")

        def log_message(self, *args):
            pass

    print("\nOpening your browser. If it doesn't open, visit:\n" + url + "\n")
    webbrowser.open(url)
    with http.server.HTTPServer(("127.0.0.1", 8765), Handler) as srv:
        while "code" not in result and "error" not in result:
            srv.handle_request()
    if result.get("error") or result.get("state") != state:
        raise SystemExit(f"Login failed: {result}")
    body = urllib.parse.urlencode({"code": result["code"], "client_id": client_id, "client_secret": client_secret,
                                   "redirect_uri": REDIRECT, "grant_type": "authorization_code"}).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=body, timeout=30) as resp:
        tokens = json.load(resp)
    if "refresh_token" not in tokens:
        raise SystemExit("No refresh token returned. Revoke the app's access at myaccount.google.com/permissions "
                         "and run again.")
    print("Add these as GitHub repository secrets:\n")
    print(f"YOUTUBE_CLIENT_ID      = {client_id}")
    print(f"YOUTUBE_CLIENT_SECRET  = {client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN  = {tokens['refresh_token']}")
    print("\nReminder: your OAuth consent screen must be 'In production', otherwise this token expires in 7 days.")


if __name__ == "__main__":
    main()
