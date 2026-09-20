"""Stage 8 — upload to YouTube.

Two things are non-negotiable here.

`status.containsSyntheticMedia` is set on the insert call (the API has
supported it since October 2024), so the altered-or-synthetic disclosure is
automatic rather than a toggle you have to remember in Studio.

Nothing uploads unless the review stage recorded approval.

Quota is not the constraint people expect: since 1 June 2026 videos.insert
bills to its own bucket at 1 unit against a default 100 calls a day, separate
from the 10,000-unit general quota.
"""

from __future__ import annotations

from pathlib import Path

from . import Context

CHUNK_SIZE = 4 * 1024 * 1024


def run(ctx: Context) -> None:
    cfg, state, ledger = ctx.cfg, ctx.state, ctx.ledger
    state.require("video", "metadata")

    if not state.get("approved"):
        print("  not approved in the review stage — nothing uploaded.")
        return

    meta = state["metadata"]
    disclose = bool(cfg.publish.get("disclose_synthetic", True))
    body = {
        "snippet": {
            "title": meta["title"],
            "description": meta.get("description", ""),
            "tags": meta.get("tags", []),
            "categoryId": str(cfg.publish.get("category_id", "27")),
        },
        "status": {
            "privacyStatus": cfg.publish.get("privacy", "private"),
            "selfDeclaredMadeForKids": bool(cfg.publish.get("made_for_kids", False)),
            "containsSyntheticMedia": disclose,
        },
    }

    if ctx.dry_run:
        print("  [dry-run] would upload with:")
        print(f"    title      {body['snippet']['title']}")
        print(f"    privacy    {body['status']['privacyStatus']}")
        print(f"    synthetic  {body['status']['containsSyntheticMedia']}")
        return

    from googleapiclient.http import MediaFileUpload

    from ..youtube import service

    youtube = service()
    media = MediaFileUpload(
        state["video"], chunksize=CHUNK_SIZE, resumable=True, mimetype="video/mp4"
    )
    request = youtube.videos().insert(
        part="snippet,status", body=body, media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  uploading… {int(status.progress() * 100)}%")

    video_id = response["id"]
    url = f"https://www.youtube.com/watch?v={video_id}"
    state.set("video_id", video_id)
    state.set("video_url", url)
    print(f"  uploaded: {url}")
    if disclose:
        print("  altered/synthetic content disclosure: set")

    thumbnail = state.get("thumbnail")
    if thumbnail and Path(thumbnail).exists():
        try:
            youtube.thumbnails().set(
                videoId=video_id, media_body=MediaFileUpload(thumbnail)
            ).execute()
            print("  thumbnail set")
        except Exception as exc:
            # Custom thumbnails need a verified channel; not worth failing the run.
            print(f"  ! could not set thumbnail ({exc}).")
            print("  ! custom thumbnails require a phone-verified channel.")

    # Record only after a successful upload, so a failed run does not burn the topic.
    script = state["script"]
    ledger.record(
        run_id=state.run_id,
        topic=state.get("topic", ""),
        angle=state.get("angle", ""),
        opening=(script["beats"][0].get("narration") or ""),
        structure=script.get("structure_used", ""),
        beat_count=len(script["beats"]),
        title=meta["title"],
        video_id=video_id,
    )
    print(f"  recorded in the ledger ({ledger.count()} videos total)")
