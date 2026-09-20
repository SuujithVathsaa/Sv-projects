"""Higgsfield Seedance 2.5 text-to-video example.

Run:  python main.py

Credentials come from .env.local as HF_KEY="key-id:key-secret". That file is
gitignored and its contents are never printed or logged.

NOTE: running this makes a real, billable generation request.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

MODEL = "bytedance/seedance-2.5/text-to-video"
ARGUMENTS = {
    "prompt": "A cinematic scene at sunset",
    "duration": 5,
    "resolution": "720p",
    "aspect_ratio": "16:9",
}

ENV_FILE = Path(__file__).parent / ".env.local"


def load_credentials() -> None:
    """Load HF_KEY from .env.local into the environment.

    The SDK reads HF_KEY (or HF_API_KEY + HF_API_SECRET) via os.getenv at call
    time, so it is enough to place it in the environment. The value itself is
    never read, printed or logged here.
    """
    load_dotenv(ENV_FILE)
    if not (os.getenv("HF_KEY") or (os.getenv("HF_API_KEY") and os.getenv("HF_API_SECRET"))):
        sys.exit(
            f"Higgsfield credentials not found.\n"
            f"  Create {ENV_FILE.name} containing:\n"
            f'    HF_KEY="your-key-id:your-key-secret"\n'
            f"  Get credentials from https://cloud.higgsfield.ai/\n"
            f"  ({ENV_FILE.name} is gitignored.)"
        )


def extract_video_url(result: dict) -> str | None:
    """Pull the video URL out of a completed result.

    The result shape is checked defensively rather than assumed: the SDK README
    documents result['images'][0]['url'] for image models, and the video
    equivalent is not something this code should guess at silently.
    """
    for collection in ("videos", "video", "images", "outputs"):
        value = result.get(collection)
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, dict) and isinstance(first.get("url"), str):
                return first["url"]
            if isinstance(first, str) and first.startswith("http"):
                return first
        elif isinstance(value, dict) and isinstance(value.get("url"), str):
            return value["url"]
    if isinstance(result.get("url"), str):
        return result["url"]
    return None


def main() -> int:
    load_credentials()

    import higgsfield_client

    # subscribe() returns normally on failure as well as success: the SDK's
    # DONE_STATUSES are (Completed, NSFW, Cancelled, Failed), so polling stops
    # on all four. The terminal status is captured here so a failed or
    # moderated request is never reported as a success.
    terminal: list = []

    def on_queue_update(status) -> None:
        terminal.append(status)
        print(f"  status: {type(status).__name__}")

    print(f"Submitting to {MODEL} ...")
    try:
        result = higgsfield_client.subscribe(
            MODEL,
            arguments=ARGUMENTS,
            on_enqueue=lambda request_id: print(f"  queued as {request_id}"),
            on_queue_update=on_queue_update,
        )
    except higgsfield_client.CredentialsMissedError as exc:
        print(f"FAILED — credentials rejected: {exc}", file=sys.stderr)
        return 2
    except higgsfield_client.InsufficientCreditsError as exc:
        print(f"FAILED — insufficient credits: {exc}", file=sys.stderr)
        return 3
    except higgsfield_client.HiggsfieldClientError as exc:
        print(f"FAILED — API error: {exc}", file=sys.stderr)
        return 4
    except Exception as exc:
        print(f"FAILED — {type(exc).__name__}: {exc}", file=sys.stderr)
        return 5

    final = terminal[-1] if terminal else None
    if not isinstance(final, higgsfield_client.Completed):
        name = type(final).__name__ if final else "unknown"
        reasons = {
            "Failed": "generation failed on the provider side",
            "NSFW": "request was moderated (flagged NSFW)",
            "Cancelled": "request was canceled",
            "unknown": "no terminal status was observed",
        }
        print(f"FAILED — {reasons.get(name, name)}", file=sys.stderr)
        return 6

    url = extract_video_url(result)
    if not url:
        print(
            f"FAILED — completed, but no video URL found in the result.\n"
            f"  Result keys: {sorted(result)}",
            file=sys.stderr,
        )
        return 7

    print(f"\nVideo URL: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
