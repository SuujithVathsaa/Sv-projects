"""Stage 3 — narration.

Each beat is synthesised separately. That costs the same as one long call (the
billing is per character either way) but yields an exact duration per beat,
which is what drives both caption timing and how long each image stays on
screen. Aligning captions to one long WAV would mean guessing.
"""

from __future__ import annotations

import wave
from pathlib import Path

from ..providers.gemini import silent_wav
from . import WORDS_PER_SECOND, Context


def duration_of(path: Path) -> float:
    """Length of a WAV file in seconds."""
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / float(wav.getframerate())


def run(ctx: Context) -> None:
    cfg, state = ctx.cfg, ctx.state
    state.require("script")

    beats = state["script"]["beats"]
    voice = cfg.voice_over.get("voice_name", "Charon")
    style = cfg.voice_over.get("style", "")

    clips: list[dict] = []
    for index, beat in enumerate(beats):
        narration = (beat.get("narration") or "").strip()
        out = state.path("audio", f"beat{index:02d}.wav")

        if ctx.dry_run:
            # A real silent WAV of plausible length, so assembly is exercised
            # for real rather than skipped.
            estimated = max(len(narration.split()) / WORDS_PER_SECOND, 1.2)
            silent_wav(out, estimated)
        else:
            ctx.require_gemini().speak(narration, out, voice=voice, style=style)

        seconds = duration_of(out)
        clips.append({"index": index, "audio": str(out), "seconds": seconds})
        print(f"  beat {index + 1}/{len(beats)}: {seconds:.1f}s")

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
