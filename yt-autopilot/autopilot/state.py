"""Per-run state, persisted to JSON so any stage can resume after a failure.

Each video gets a directory under runs/ holding state.json plus all of its
generated media. Stages read what earlier stages wrote and record their own
output, so killing the process at any point costs only the current stage.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import RUNS_DIR

STAGES = [
    "ideate",
    "script",
    "voice",
    "visuals",
    "assemble",
    "thumbnail",
    "review",
    "publish",
]


class RunState:
    """Mutable run state backed by runs/<run_id>/state.json."""

    def __init__(self, run_id: str, data: dict[str, Any] | None = None):
        self.run_id = run_id
        self.dir = RUNS_DIR / run_id
        self.data: dict[str, Any] = data if data is not None else {
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_stages": [],
            "dry_run": False,
        }

    # -- lifecycle ---------------------------------------------------------
    @classmethod
    def create(cls, dry_run: bool = False) -> "RunState":
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        state = cls(run_id)
        state.data["dry_run"] = dry_run
        state.dir.mkdir(parents=True, exist_ok=True)
        state.save()
        return state

    @classmethod
    def load(cls, run_id: str) -> "RunState":
        path = RUNS_DIR / run_id / "state.json"
        if not path.exists():
            raise FileNotFoundError(
                f"No run found with id '{run_id}'. "
                f"Use `python -m autopilot list` to see available runs."
            )
        return cls(run_id, json.loads(path.read_text()))

    @classmethod
    def latest(cls) -> "RunState":
        runs = sorted(
            (p for p in RUNS_DIR.glob("*/state.json")),
            key=lambda p: p.stat().st_mtime,
        )
        if not runs:
            raise FileNotFoundError("No runs yet. Start one with `python -m autopilot run`.")
        return cls.load(runs[-1].parent.name)

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "state.json").write_text(json.dumps(self.data, indent=2))

    # -- accessors ---------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()

    @property
    def dry_run(self) -> bool:
        return bool(self.data.get("dry_run"))

    def path(self, *parts: str) -> Path:
        """A path inside this run's directory, with parents created."""
        p = self.dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    # -- stage tracking ----------------------------------------------------
    def is_done(self, stage: str) -> bool:
        return stage in self.data.get("completed_stages", [])

    def mark_done(self, stage: str) -> None:
        done = self.data.setdefault("completed_stages", [])
        if stage not in done:
            done.append(stage)
        self.save()

    def next_stage(self) -> str | None:
        for stage in STAGES:
            if not self.is_done(stage):
                return stage
        return None

    def require(self, *keys: str) -> None:
        """Fail early and legibly when a prior stage's output is missing."""
        missing = [k for k in keys if k not in self.data]
        if missing:
            raise RuntimeError(
                f"Run {self.run_id} is missing {missing}, which an earlier stage "
                f"should have produced. Completed so far: "
                f"{self.data.get('completed_stages', [])}"
            )
