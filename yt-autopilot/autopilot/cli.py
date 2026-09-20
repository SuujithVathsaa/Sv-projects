"""Command line entry point.

    python -m autopilot run              # make a video, start to finish
    python -m autopilot run --dry-run    # same path, no API calls, no spend
    python -m autopilot resume           # continue the latest run
    python -m autopilot stage script     # re-run one stage of the latest run
    python -m autopilot list             # recent runs
    python -m autopilot models --refresh # re-resolve Gemini model ids
    python -m autopilot voices           # available narration voices
"""

from __future__ import annotations

import argparse
import importlib
import sys
import traceback

from .config import RUNS_DIR, ConfigError, load_config
from .ledger import Ledger
from .models import discover
from .state import STAGES, RunState
from .stages import Context

# The 30 prebuilt Gemini TTS voices, with a note on character.
VOICES = {
    "Zephyr": "bright", "Puck": "upbeat", "Charon": "informative",
    "Kore": "firm", "Fenrir": "excitable", "Leda": "youthful",
    "Orus": "firm", "Aoede": "breezy", "Callirrhoe": "easy-going",
    "Autonoe": "bright", "Enceladus": "breathy", "Iapetus": "clear",
    "Umbriel": "easy-going", "Algieba": "smooth", "Despina": "smooth",
    "Erinome": "clear", "Algenib": "gravelly", "Rasalgethi": "informative",
    "Laomedeia": "upbeat", "Achernar": "soft", "Alnilam": "firm",
    "Schedar": "even", "Gacrux": "mature", "Pulcherrima": "forward",
    "Achird": "friendly", "Zubenelgenubi": "casual", "Vindemiatrix": "gentle",
    "Sadachbia": "lively", "Sadaltager": "knowledgeable", "Sulafat": "warm",
}


def _context(dry_run: bool, state: RunState) -> Context:
    cfg = load_config()
    gemini = None
    if not dry_run:
        from .providers.gemini import Gemini

        models = discover(cfg.gemini_key)
        print(models)
        gemini = Gemini(cfg.gemini_key, models)
    return Context(cfg=cfg, state=state, ledger=Ledger(), gemini=gemini)


def _run_stage(ctx: Context, name: str) -> None:
    module = importlib.import_module(f".stages.{name}", package="autopilot")
    print(f"\n[{name}]")
    module.run(ctx)
    ctx.state.mark_done(name)


def _pipeline(ctx: Context, start_from: str | None = None) -> int:
    stages = STAGES[STAGES.index(start_from):] if start_from else STAGES
    for name in stages:
        if ctx.state.is_done(name):
            print(f"\n[{name}] already done — skipping")
            continue
        _run_stage(ctx, name)
    print(f"\nRun {ctx.state.run_id} finished.")
    if ctx.state.get("video"):
        print(f"  {ctx.state['video']}")
    return 0


def cmd_run(args) -> int:
    state = RunState.create(dry_run=args.dry_run)
    print(f"Run {state.run_id}" + (" (dry run — no API calls)" if args.dry_run else ""))
    return _pipeline(_context(args.dry_run, state))


def cmd_resume(args) -> int:
    state = RunState.load(args.run_id) if args.run_id else RunState.latest()
    nxt = state.next_stage()
    if nxt is None:
        print(f"Run {state.run_id} is already complete.")
        return 0
    print(f"Resuming run {state.run_id} at '{nxt}'")
    return _pipeline(_context(state.dry_run, state), start_from=nxt)


def cmd_stage(args) -> int:
    state = RunState.load(args.run_id) if args.run_id else RunState.latest()
    if args.name not in STAGES:
        print(f"Unknown stage '{args.name}'. Choose from: {', '.join(STAGES)}", file=sys.stderr)
        return 2
    # Re-running a stage invalidates it and everything after it.
    index = STAGES.index(args.name)
    state.data["completed_stages"] = [
        s for s in state.get("completed_stages", []) if STAGES.index(s) < index
    ]
    state.save()
    _run_stage(_context(state.dry_run, state), args.name)
    later = STAGES[index + 1:]
    if later:
        print(f"\nStages after this are now stale. `python -m autopilot resume` to rebuild.")
    return 0


def cmd_list(args) -> int:
    runs = sorted(RUNS_DIR.glob("*/state.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not runs:
        print("No runs yet.")
        return 0
    for path in runs[:args.limit]:
        state = RunState.load(path.parent.name)
        done = state.get("completed_stages", [])
        title = (state.get("metadata") or {}).get("title") or state.get("topic") or "—"
        flag = " [dry]" if state.dry_run else ""
        print(f"  {state.run_id}{flag}  {len(done)}/{len(STAGES)} stages  {title[:52]}")
    return 0


def cmd_models(args) -> int:
    cfg = load_config()
    print(discover(cfg.gemini_key, refresh=args.refresh))
    return 0


def cmd_voices(args) -> int:
    current = load_config().voice_over.get("voice_name", "")
    print("Set `voice_over.voice_name` in config/channel.yaml to one of:\n")
    for name, note in VOICES.items():
        mark = "  <- current" if name == current else ""
        print(f"  {name:<16} {note}{mark}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autopilot",
        description="Automated YouTube Shorts pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subs = parser.add_subparsers(dest="command", required=True)

    run = subs.add_parser("run", help="make a video from scratch")
    run.add_argument("--dry-run", action="store_true",
                     help="exercise every stage with no API calls and no spend")
    run.set_defaults(func=cmd_run)

    resume = subs.add_parser("resume", help="continue an unfinished run")
    resume.add_argument("run_id", nargs="?", help="defaults to the most recent run")
    resume.set_defaults(func=cmd_resume)

    stage = subs.add_parser("stage", help="re-run a single stage")
    stage.add_argument("name", help=f"one of: {', '.join(STAGES)}")
    stage.add_argument("run_id", nargs="?", help="defaults to the most recent run")
    stage.set_defaults(func=cmd_stage)

    listing = subs.add_parser("list", help="show recent runs")
    listing.add_argument("--limit", type=int, default=10)
    listing.set_defaults(func=cmd_list)

    models = subs.add_parser("models", help="show the Gemini models in use")
    models.add_argument("--refresh", action="store_true", help="re-query the API")
    models.set_defaults(func=cmd_models)

    voices = subs.add_parser("voices", help="list narration voices")
    voices.set_defaults(func=cmd_voices)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"\nConfiguration problem:\n{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted. `python -m autopilot resume` picks up where this stopped.")
        return 130
    except Exception as exc:
        print(f"\n{type(exc).__name__}: {exc}", file=sys.stderr)
        if "--traceback" in (argv or sys.argv):
            traceback.print_exc()
        return 1
