"""Higgsfield backend (optional) — generated video for the hook beat.

Uses the official SDK (`higgsfield-client`) rather than shelling out to the CLI.

    pip install higgsfield-client

Credentials live in .env.local as HF_KEY="key-id:key-secret". The SDK reads
HF_KEY (or HF_API_KEY + HF_API_SECRET) from the environment at call time, so
this module only ensures the file is loaded — it never reads, prints or logs
the value.

Every failure here is non-fatal by design. If credentials are missing, credit
runs out, the request is moderated, or the network is unreachable, `generate`
returns None and the caller falls back to a still image. A paid optional
upgrade must never be able to break the pipeline.
"""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path

from ..config import ROOT

# Default model. The argument schema below matches its text-to-video endpoint.
DEFAULT_MODEL = "bytedance/seedance-2.5/text-to-video"

ENV_FILE = ROOT / ".env.local"


def _load_env() -> None:
    """Load .env.local so the SDK can find HF_KEY in the environment."""
    try:
        from dotenv import load_dotenv

        load_dotenv(ENV_FILE)
    except ImportError:
        pass


def available() -> tuple[bool, str]:
    """Whether the SDK is installed and credentials are present."""
    try:
        import higgsfield_client  # noqa: F401
    except ImportError:
        return False, "higgsfield-client not installed — `pip install higgsfield-client`"

    _load_env()
    has_key = bool(
        os.getenv("HF_KEY")
        or (os.getenv("HF_API_KEY") and os.getenv("HF_API_SECRET"))
    )
    if not has_key:
        return False, (
            f"no Higgsfield credentials — copy .env.local.example to "
            f"{ENV_FILE.name} and set HF_KEY"
        )
    return True, "ready"


def extract_video_url(result: dict) -> str | None:
    """Pull a video URL out of a completed result.

    Checked defensively rather than assumed: the SDK documents
    result['images'][0]['url'] for image models, and the video equivalent is
    not something this code should guess at silently.
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


def generate(
    prompt: str,
    out_path: Path,
    *,
    model: str = DEFAULT_MODEL,
    duration: int = 5,
    aspect: str = "9:16",
    resolution: str = "720p",
) -> Path | None:
    """Generate one clip. Returns the path, or None if anything went wrong.

    Makes a billable request when it proceeds.
    """
    ok, reason = available()
    if not ok:
        print(f"    higgsfield unavailable ({reason}) — using a still image instead")
        return None

    import higgsfield_client

    # subscribe() returns normally on failure as well as success: the SDK's
    # DONE_STATUSES are (Completed, NSFW, Cancelled, Failed), so polling stops
    # on all four. Capture the terminal status so a failed or moderated
    # request is never mistaken for a successful one.
    terminal: list = []

    print(f"    higgsfield: {model} {duration}s {aspect} (this can take a few minutes)")
    try:
        result = higgsfield_client.subscribe(
            model,
            arguments={
                "prompt": prompt,
                "duration": duration,
                "resolution": resolution,
                "aspect_ratio": aspect,
            },
            on_queue_update=terminal.append,
        )
    except Exception as exc:
        print(f"    higgsfield request failed ({type(exc).__name__}: {exc}) — using a still image")
        return None

    final = terminal[-1] if terminal else None
    if not isinstance(final, higgsfield_client.Completed):
        name = type(final).__name__ if final else "no terminal status"
        print(f"    higgsfield did not complete ({name}) — using a still image")
        return None

    url = extract_video_url(result)
    if not url:
        print(
            f"    higgsfield completed but returned no video URL "
            f"(keys: {sorted(result)}) — using a still image"
        )
        return None

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=180) as response:
            out_path.write_bytes(response.read())
    except Exception as exc:
        print(f"    could not download higgsfield result ({exc}) — using a still image")
        return None

    if out_path.stat().st_size < 1024:
        print("    higgsfield returned an empty file — using a still image")
        return None
    return out_path
