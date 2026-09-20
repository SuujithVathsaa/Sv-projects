"""Stage 3 — narration.

Two modes, because the free Gemini tier allows only 15 TTS requests a day.

Batch (default): one request for the whole script, then recover where each beat
starts and ends. One request per video means 15 videos a day on the free tier.
Per-beat: one request per beat, which gives exact durations but burns the daily
quota after two videos. Worth switching to only on billing, or for a video that
matters enough to spend the quota on.

Beat boundaries have to be accurate either way, since both caption timing and
how long each image holds are derived from them. In batch mode they are
recovered by measuring the pauses in the audio, falling back to splitting by
word count when the pauses cannot be found.
"""

from __future__ import annotations

import re
import subprocess
import wave
from pathlib import Path

import imageio_ffmpeg

from ..providers.gemini import silent_wav
from . import WORDS_PER_SECOND, Context

# A pause shorter than this is speech rhythm, not a beat break.
MIN_GAP_SECONDS = 0.35
SILENCE_THRESHOLD_DB = -40

_SILENCE = re.compile(r"silence_(start|end):\s*([0-9.]+)")


def duration_of(path: Path) -> float:
    """Length of a WAV file in seconds."""
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / float(wav.getframerate())


def find_gaps(path: Path) -> list[tuple[float, float]]:
    """Silent spans in an audio file, as (start, end) pairs."""
    result = subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(path),
            "-af", f"silencedetect=noise={SILENCE_THRESHOLD_DB}dB:d={MIN_GAP_SECONDS}",
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    starts: list[float] = []
    ends: list[float] = []
    for kind, value in _SILENCE.findall(result.stderr):
        (starts if kind == "start" else ends).append(float(value))
    # A trailing silence may have no matching end; pair only what is complete.
    return list(zip(starts, ends))


def split_by_words(beats: list[dict], total: float) -> list[float]:
    """Divide `total` across beats in proportion to their word counts."""
    counts = [max(len((b.get("narration") or "").split()), 1) for b in beats]
    words = sum(counts)
    return [total * count / words for count in counts]


def split_by_gaps(beats: list[dict], total: float, path: Path) -> list[float] | None:
    """Beat durations measured from the pauses, or None if they don't line up."""
    gaps = find_gaps(path)
    # Ignore silence at the very start or end; only interior pauses separate beats.
    interior = [(s, e) for s, e in gaps if s > 0.05 and e < total - 0.05]
    if len(interior) != len(beats) - 1:
        return None

    # Each boundary sits at the middle of its pause, so every beat carries half
    # the surrounding silence and the durations still sum to the total.
    boundaries = [(s + e) / 2 for s, e in interior]
    edges = [0.0, *boundaries, total]
    durations = [edges[i + 1] - edges[i] for i in range(len(beats))]
    return durations if all(d > 0.2 for d in durations) else None


def run(ctx: Context) -> None:
    cfg, state = ctx.cfg, ctx.state
    state.require("script")

    beats = state["script"]["beats"]
    voice = cfg.voice_over.get("voice_name", "Charon")
    style = cfg.voice_over.get("style", "")
    batch = bool(cfg.voice_over.get("batch", True))

    clips = _batch(ctx, beats, voice, style) if batch else _per_beat(ctx, beats, voice, style)

    total = sum(c["seconds"] for c in clips)
    state.set("audio_clips", clips)
    state.set("duration", total)

    limit = 180 if cfg.format.get("profile", "short") == "short" else 3600
    if total > limit:
        print(
            f"  ! narration is {total:.0f}s, over the {limit}s Shorts limit.\n"
            f"  ! lower `format.target_seconds` or `format.beats` in config/channel.yaml"
        )
    print(f"  total narration: {total:.1f}s")


def _batch(ctx: Context, beats: list[dict], voice: str, style: str) -> list[dict]:
    """One TTS request for the whole script."""
    state = ctx.state
    out = state.path("audio", "narration.wav")

    text = "\n\n".join((b.get("narration") or "").strip() for b in beats)
    if ctx.dry_run:
        estimated = max(len(text.split()) / WORDS_PER_SECOND, len(beats) * 1.2)
        silent_wav(out, estimated)
    else:
        # The pause instruction is what makes the beat boundaries measurable.
        instruction = (
            f"{style}\n\nLeave a clear pause of about one second between paragraphs."
        ).strip()
        ctx.require_gemini().speak(text, out, voice=voice, style=instruction)
        print("  1 TTS request (batch mode)")

    total = duration_of(out)
    durations = split_by_gaps(beats, total, out)
    if durations is None:
        durations = split_by_words(beats, total)
        print(f"  beat timing: split by word count ({total:.1f}s total)")
    else:
        print(f"  beat timing: measured from pauses ({total:.1f}s total)")

    # One shared audio file; each beat is a span within it.
    clips = []
    offset = 0.0
    for index, seconds in enumerate(durations):
        clips.append(
            {"index": index, "audio": str(out), "seconds": seconds, "offset": offset}
        )
        offset += seconds
    return clips


def _per_beat(ctx: Context, beats: list[dict], voice: str, style: str) -> list[dict]:
    """One TTS request per beat — exact, but 6x the daily quota."""
    state = ctx.state
    clips = []
    for index, beat in enumerate(beats):
        narration = (beat.get("narration") or "").strip()
        out = state.path("audio", f"beat{index:02d}.wav")
        if ctx.dry_run:
            silent_wav(out, max(len(narration.split()) / WORDS_PER_SECOND, 1.2))
        else:
            ctx.require_gemini().speak(narration, out, voice=voice, style=style)
        seconds = duration_of(out)
        clips.append({"index": index, "audio": str(out), "seconds": seconds, "offset": 0.0})
        print(f"  beat {index + 1}/{len(beats)}: {seconds:.1f}s")
    return clips
