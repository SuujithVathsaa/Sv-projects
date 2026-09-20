"""Stage 2 — write the script, refusing to repeat a recent shape.

This is where the channel's monetization is protected. YouTube judges channels,
not videos: a channel whose scripts share one opening move and one structure
reads as mass-produced however good any single video is. So the structure is
assigned from a rotation, and a script whose hook is too close to a recent one
is thrown away and rewritten.
"""

from __future__ import annotations

from ..config import load_prompt
from . import WORDS_PER_SECOND, Context


def run(ctx: Context) -> None:
    cfg, state, ledger = ctx.cfg, ctx.state, ctx.ledger
    state.require("topic", "angle", "surprise")

    beats = int(cfg.format.get("beats", 6))
    seconds = int(cfg.format.get("target_seconds", 45))

    if ctx.dry_run:
        state.set(
            "script",
            {
                "title_working": "The bridge that tore itself apart",
                "structure_used": "dry-run placeholder",
                "beats": [
                    {
                        "narration": f"Placeholder narration for beat {i + 1}.",
                        "visual": f"A wide photographic shot illustrating beat {i + 1}.",
                    }
                    for i in range(beats)
                ],
            },
        )
        print(f"  [dry-run] placeholder script, {beats} beats")
        return

    structure = ledger.next_structure(bool(cfg.originality.get("rotate_structures", True)))
    threshold = float(cfg.originality.get("max_similarity", 0.55))
    lookback = int(cfg.originality.get("lookback", 25))
    attempts = int(cfg.originality.get("max_regenerations", 4))
    recent_openings = ledger.recent_openings(lookback)
    avoid = "\n".join(f"  - {o}" for o in recent_openings) or "  (nothing yet)"

    prompt = load_prompt(
        "script",
        topic=state["topic"],
        angle=state["angle"],
        surprise=state["surprise"],
        voice=cfg.channel["voice"],
        audience=cfg.channel["audience"],
        structure=structure,
        beats=beats,
        target_seconds=seconds,
        word_budget=int(seconds * WORDS_PER_SECOND),
        avoid_openings=avoid,
    )

    gemini = ctx.require_gemini()
    last_score = 0.0
    for attempt in range(1, attempts + 1):
        # Climbing temperature pushes later attempts further from the first.
        script = gemini.json(prompt, temperature=1.0 + 0.15 * (attempt - 1))
        script_beats = script.get("beats") or []
        if not script_beats:
            print(f"  attempt {attempt}: no beats returned, retrying")
            continue

        opening = (script_beats[0].get("narration") or "").strip()
        too_close, score, match = ledger.is_too_similar(
            opening, "opening", threshold, lookback
        )
        last_score = score
        if too_close:
            print(f"  attempt {attempt}: hook {score:.0%} like '{match[:45]}' — rewriting")
            continue

        script["structure_used"] = structure
        state.set("script", script)
        words = sum(len((b.get("narration") or "").split()) for b in script_beats)
        print(f"  script: {len(script_beats)} beats, ~{words} words, {words/WORDS_PER_SECOND:.0f}s")
        print(f"  structure: {structure[:60]}")
        return

    raise RuntimeError(
        f"Could not write a hook distinct from recent videos after {attempts} attempts "
        f"(closest {last_score:.0%}, limit {threshold:.0%}).\n"
        f"  This is the anti-repetition guard doing its job. Try a different angle,\n"
        f"  or raise `originality.max_regenerations` in config/channel.yaml."
    )
