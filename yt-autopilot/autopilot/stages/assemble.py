"""Stage 5 — build the video with FFmpeg. No editor, no manual work.

Stills become motion via zoompan (Ken Burns), captions are burned in from the
per-beat timings measured in the voice stage, and the result is written to
YouTube's Shorts spec.

Two details that are easy to get wrong and expensive to discover later:

- Captions must sit inside the centred 900x1350 safe zone (180px top, 390px
  bottom, 60px sides). Outside it, YouTube's own UI covers them on a phone.
- zoompan applied directly to a 1080-wide still jitters visibly. Upscaling
  before the zoom and letting zoompan output at the target size avoids it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import imageio_ffmpeg

from . import Context

FPS = 30
VIDEO_BITRATE = "12M"
AUDIO_BITRATE = "128k"

# YouTube Shorts safe zone, as pixel margins inside a 1080x1920 frame.
SAFE_TOP, SAFE_BOTTOM, SAFE_SIDE = 180, 390, 60

# Words per caption chunk. Short chunks read far better on a phone.
CAPTION_CHUNK_WORDS = 4


def ffmpeg() -> str:
    """Path to a usable ffmpeg, preferring the one bundled with the project."""
    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(args: list[str], what: str) -> None:
    result = subprocess.run(
        [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", *args],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-4:]
        raise RuntimeError(f"ffmpeg failed during {what}:\n  " + "\n  ".join(tail))


def _ass_time(seconds: float) -> str:
    """Seconds to the H:MM:SS.CC format ASS expects."""
    centis = int(round(seconds * 100))
    hours, centis = divmod(centis, 360000)
    minutes, centis = divmod(centis, 6000)
    secs, centis = divmod(centis, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _chunks(words: list[str], size: int) -> list[list[str]]:
    return [words[i:i + size] for i in range(0, len(words), size)] or [[]]


def build_captions(ctx: Context, out_path: Path) -> Path:
    """Write an ASS subtitle file timed to the per-beat audio durations."""
    cfg, state = ctx.cfg, ctx.state
    width, height = cfg.dimensions
    caps = cfg.captions

    position = float(caps.get("position", 0.62))
    margin_v = int(round((1.0 - position) * height))
    if margin_v < SAFE_BOTTOM:
        print(
            f"  ! captions.position {position} puts text {margin_v}px from the bottom,\n"
            f"  ! inside the {SAFE_BOTTOM}px Shorts UI zone. Clamping to keep them visible."
        )
        margin_v = SAFE_BOTTOM

    style = (
        f"Style: Default,DejaVu Sans,{caps.get('font_size', 54)},"
        f"{caps.get('primary_color', '&H00FFFFFF')},&H000000FF,"
        f"{caps.get('outline_color', '&H00000000')},&H00000000,"
        f"-1,0,0,0,100,100,0,0,1,{caps.get('outline', 3)},0,2,"
        f"{SAFE_SIDE},{SAFE_SIDE},{margin_v},1"
    )

    header = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour,"
        " BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle,"
        " BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        style, "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    events: list[str] = []
    clock = 0.0
    for clip, beat in zip(state["audio_clips"], state["script"]["beats"]):
        span = float(clip["seconds"])
        words = (beat.get("narration") or "").split()
        groups = _chunks(words, CAPTION_CHUNK_WORDS)
        total_words = max(len(words), 1)
        cursor = clock
        for group in groups:
            if not group:
                continue
            share = span * (len(group) / total_words)
            text = " ".join(group).replace("\n", " ")
            events.append(
                f"Dialogue: 0,{_ass_time(cursor)},{_ass_time(cursor + share)},"
                f"Default,,0,0,0,,{text}"
            )
            cursor += share
        clock += span

    out_path.write_text("\n".join(header + events) + "\n", encoding="utf-8")
    return out_path


def _segment(ctx: Context, asset: dict, seconds: float, out: Path) -> None:
    """One beat: a still with Ken Burns motion, or a generated clip, fitted to frame."""
    cfg = ctx.cfg
    width, height = cfg.dimensions
    frames = max(int(round(seconds * FPS)), 1)
    fill = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}"
    )

    if asset["kind"] == "video":
        # Generated clip: fit to frame, then loop or trim to the beat's length.
        chain = f"{fill},fps={FPS},setsar=1"
        _run(
            ["-stream_loop", "-1", "-i", asset["path"], "-t", f"{seconds:.3f}",
             "-vf", chain, "-an", "-c:v", "libx264", "-preset", "medium",
             "-pix_fmt", "yuv420p", str(out)],
            f"beat {asset['index'] + 1} (video)",
        )
        return

    if cfg.visuals.get("ken_burns", True):
        zoom_max = float(cfg.visuals.get("zoom_max", 1.12))
        span = zoom_max - 1.0
        # Alternate direction per beat so the motion itself is not a template.
        if asset["index"] % 2 == 0:
            zexpr = f"1+{span:.4f}*on/{frames}"
        else:
            zexpr = f"{zoom_max:.4f}-{span:.4f}*on/{frames}"
        chain = (
            f"{fill},scale={width * 2}:{height * 2},"
            f"zoompan=z='{zexpr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={frames}:s={width}x{height}:fps={FPS},setsar=1"
        )
    else:
        chain = f"{fill},fps={FPS},setsar=1"

    _run(
        ["-loop", "1", "-i", asset["path"], "-t", f"{seconds:.3f}",
         "-vf", chain, "-an", "-c:v", "libx264", "-preset", "medium",
         "-pix_fmt", "yuv420p", str(out)],
        f"beat {asset['index'] + 1}",
    )


def _concat(inputs: list[Path], out: Path, list_file: Path, extra: list[str]) -> None:
    list_file.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in inputs), encoding="utf-8"
    )
    _run(
        ["-f", "concat", "-safe", "0", "-i", str(list_file), *extra, str(out)],
        f"concatenating {len(inputs)} parts",
    )


def run(ctx: Context) -> None:
    cfg, state = ctx.cfg, ctx.state
    state.require("script", "audio_clips", "visual_assets")

    assets = {a["index"]: a for a in state["visual_assets"]}
    clips = state["audio_clips"]

    # 1. One video segment per beat.
    segments: list[Path] = []
    for clip in clips:
        index = clip["index"]
        out = state.path("segments", f"seg{index:02d}.mp4")
        _segment(ctx, assets[index], float(clip["seconds"]), out)
        segments.append(out)
        print(f"  segment {index + 1}/{len(clips)} built")

    # 2. Concatenate video, then audio.
    silent = state.path("segments", "video.mp4")
    _concat(segments, silent, state.path("segments", "video.txt"), ["-c", "copy"])

    narration = state.path("audio", "narration.wav")
    _concat(
        [Path(c["audio"]) for c in clips],
        narration,
        state.path("audio", "audio.txt"),
        ["-c", "copy"],
    )

    # 3. Mux, burn captions, encode to the Shorts spec.
    final = state.path("output", "video.mp4")
    filters = []
    if cfg.captions.get("enabled", True):
        ass = build_captions(ctx, state.path("output", "captions.ass"))
        # The filter argument is escaped, not the file: colons and backslashes
        # in a path would otherwise be read as filter syntax.
        escaped = str(ass).replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")
        filters.append(f"subtitles='{escaped}'")

    args = ["-i", str(silent), "-i", str(narration)]
    if filters:
        args += ["-vf", ",".join(filters)]
    args += [
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "medium", "-b:v", VIDEO_BITRATE,
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
        "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", "48000",
        "-movflags", "+faststart", "-shortest", str(final),
    ]
    _run(args, "final encode")

    state.set("video", str(final))
    print(f"  video: {final}")
