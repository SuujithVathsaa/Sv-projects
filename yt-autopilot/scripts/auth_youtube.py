#!/usr/bin/env python3
"""One-time YouTube OAuth. Run once; the refresh token is cached afterwards.

    python scripts/auth_youtube.py

Opens a browser for consent. The resulting token.json is gitignored.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from autopilot.config import ROOT  # noqa: E402
from autopilot.youtube import service  # noqa: E402


def main() -> int:
    load_dotenv(ROOT / ".env")
    try:
        youtube = service(interactive=True)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    response = youtube.channels().list(part="snippet", mine=True).execute()
    items = response.get("items") or []
    if not items:
        print("Authorised, but this account has no YouTube channel.", file=sys.stderr)
        return 1
    print(f"Authorised for channel: {items[0]['snippet']['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
