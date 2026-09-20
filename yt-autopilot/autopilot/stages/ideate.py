"""Stage 1 — pick a topic that the channel has not already covered."""

from __future__ import annotations

from ..config import load_prompt
from . import Context

PROPOSALS = 6


def run(ctx: Context) -> None:
    cfg, state, ledger = ctx.cfg, ctx.state, ctx.ledger

    if ctx.dry_run:
        state.set("topic", "The Tacoma Narrows bridge collapse")
        state.set("angle", "Why the textbook explanation taught for decades was wrong")
        state.set("surprise", "It was not resonance. It was aeroelastic flutter.")
        print("  [dry-run] using a placeholder topic")
        return

    recent = ledger.recent_topics(cfg.originality.get("lookback", 25))
    avoid = "\n".join(f"  - {t}" for t in recent) or "  (nothing yet)"

    prompt = load_prompt(
        "ideate",
        niche=cfg.channel["niche"],
        audience=cfg.channel["audience"],
        count=PROPOSALS,
        avoid_list=avoid,
    )
    payload = ctx.require_gemini().json(prompt, temperature=1.2)
    topics = payload.get("topics") or []
    if not topics:
        raise RuntimeError("Ideation returned no topics. Try rewording the niche.")

    threshold = float(cfg.originality.get("max_similarity", 0.55))
    lookback = int(cfg.originality.get("lookback", 25))

    for candidate in topics:
        text = f"{candidate.get('topic','')} {candidate.get('angle','')}"
        too_close, score, match = ledger.is_too_similar(text, "topic", threshold, lookback)
        if too_close:
            print(f"  skipped '{candidate.get('topic','')}' — {score:.0%} like '{match[:50]}'")
            continue
        state.set("topic", candidate.get("topic", ""))
        state.set("angle", candidate.get("angle", ""))
        state.set("surprise", candidate.get("surprise", ""))
        print(f"  topic: {state['topic']}")
        return

    raise RuntimeError(
        f"All {len(topics)} proposed topics were too close to recent videos.\n"
        f"  Either widen `channel.niche` in config/channel.yaml, or raise\n"
        f"  `originality.max_similarity` (currently {threshold})."
    )
