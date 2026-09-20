"""Stage 6 — packaging: title, description, tags, and the thumbnail image.

Metadata lives here rather than in its own stage because it and the thumbnail
are one decision: they are what a viewer sees before they watch anything.

The thumbnail uses the Pro image tier. That tier costs more per image, but it
is the one that renders legible text, and a video needs exactly one thumbnail
where it needs six scene images — so the cost lands in the right place.
"""

from __future__ import annotations

from ..config import load_prompt
from . import Context


def run(ctx: Context) -> None:
    cfg, state = ctx.cfg, ctx.state
    state.require("script")

    script = state["script"]
    beats = script["beats"]
    script_text = " ".join((b.get("narration") or "") for b in beats)

    # --- metadata ---
    if ctx.dry_run:
        state.set(
            "metadata",
            {
                "title": script.get("title_working", "Untitled"),
                "description": "Placeholder description.\n\n#shorts",
                "tags": ["placeholder"],
            },
        )
        print("  [dry-run] placeholder metadata")
    else:
        prompt = load_prompt(
            "metadata",
            topic=state["topic"],
            script_text=script_text,
            niche=cfg.channel["niche"],
        )
        metadata = ctx.require_gemini().json(prompt)
        title = (metadata.get("title") or "").strip()
        if not title:
            raise RuntimeError("Metadata generation returned no title.")
        if len(title) > 100:
            metadata["title"] = title[:97] + "..."  # YouTube hard limit is 100.
        state.set("metadata", metadata)
        print(f"  title: {metadata['title']}")

    # --- thumbnail ---
    out = state.path("output", "thumbnail.png")
    if ctx.dry_run:
        from .visuals import _placeholder

        width, height = cfg.dimensions
        _placeholder(out, width, height)
        print("  [dry-run] placeholder thumbnail")
    else:
        prompt = load_prompt(
            "thumbnail",
            visual=beats[0].get("visual", state["topic"]),
            style=cfg.visuals.get("style", ""),
        )
        ctx.require_gemini().image(prompt, out, pro=True)
        print(f"  thumbnail: {out}")

    state.set("thumbnail", str(out))
