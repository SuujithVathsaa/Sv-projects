"""YouTube Data API auth, shared by the publish stage and the auth script."""

from __future__ import annotations

import os
from pathlib import Path

from .config import ROOT

# youtube.upload covers videos.insert and thumbnails.set.
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _paths() -> tuple[Path, Path]:
    client = Path(os.environ.get("YOUTUBE_CLIENT_SECRET", "client_secret.json"))
    token = Path(os.environ.get("YOUTUBE_TOKEN_FILE", "token.json"))
    if not client.is_absolute():
        client = ROOT / client
    if not token.is_absolute():
        token = ROOT / token
    return client, token


def credentials(interactive: bool = False):
    """Load cached credentials, refreshing or running the OAuth flow as needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    client_secret, token_file = _paths()
    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_file.write_text(creds.to_json())
        return creds

    if not interactive:
        raise RuntimeError(
            f"Not authorised to upload to YouTube.\n"
            f"  Run: python scripts/auth_youtube.py"
        )

    if not client_secret.exists():
        raise RuntimeError(
            f"OAuth client file not found at {client_secret}.\n"
            f"  1. Google Cloud Console -> APIs & Services -> Credentials\n"
            f"  2. Create an OAuth client ID of type 'Desktop app'\n"
            f"  3. Download the JSON and save it there (it is gitignored)\n"
            f"  4. Make sure YouTube Data API v3 is enabled for the project"
        )

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=0)
    token_file.write_text(creds.to_json())
    print(f"Authorised. Token cached at {token_file}")
    return creds


def service(interactive: bool = False):
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=credentials(interactive), cache_discovery=False)
