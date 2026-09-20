"""Stage 4 — one visual per beat.

Stills by default, because cost is what decides whether a channel can run at
volume: generative video at $0.12-$0.40/second cannot. When Higgsfield is
enabled it is applied to the hook beat only, and any failure there falls back
to a still rather than failing the run.
"""

from __future__ import annotations

from ..providers import higgsfield
from . import Context



def _placeholder(path, width: int, height: int) -> None:
    """Write a solid dark frame without requiring an image library."""
    import subprocess

    import imageio_ffmpeg

    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=0x11151c:s={width}x{height}",
            "-frames:v", "1", str(path),
        ],
        check=True, capture_output=True,
    )


def run(ctx: Context) -> None:
    cfg, state = ctx.cfg, ctx.state
    state.require("script")

    beats = state["script"]["beats"]
    style = cfg.visuals.get("style", "")
    width, height = cfg.dimensions

    use_hf = bool(cfg.visuals.get("use_higgsfield", False))
    hf_scope = cfg.visuals.get("higgsfield_scope", "hook")
    hf_model = cfg.visuals.get("higgsfield_model", higgsfield.DEFAULT_MODEL)

    assets: list[dict] = []
    for index, beat in enumerate(beats):
        visual = (beat.get("visual") or "").strip()
        prompt = f"{visual}\n\nStyle: {style}\nVertical 9:16 composition." if style else visual

        # Generated video, where enabled and in scope.
        wants_video = use_hf and (hf_scope == "all" or (hf_scope == "hook" and index == 0))
        if wants_video and not ctx.dry_run:
            clip = higgsfield.generate(
                prompt,
                state.path("visuals", f"beat{index:02d}.mp4"),
                model=hf_model,
                duration=5,
                aspect=cfg.visuals.get("aspect", "9:16"),
            )
            if clip is not None:
                assets.append({"index": index, "path": str(clip), "kind": "video"})
                print(f"  beat {index + 1}/{len(beats)}: generated video")
                continue

        out = state.path("visuals", f"beat{index:02d}.png")
        if ctx.dry_run:
            _placeholder(out, width, height)
        else:
            ctx.require_gemini().image(prompt, out)
        assets.append({"index": index, "path": str(out), "kind": "image"})
        print(f"  beat {index + 1}/{len(beats)}: image")

    state.set("visual_assets", assets)
