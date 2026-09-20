"""Pipeline stages. Each exposes run(ctx) and records its output on the run state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Config
    from ..ledger import Ledger
    from ..providers.gemini import Gemini
    from ..state import RunState

# Natural narration pace, words per second. Used to size scripts to a duration.
WORDS_PER_SECOND = 2.5


@dataclass
class Context:
    """Everything a stage needs, assembled once by the CLI."""

    cfg: "Config"
    state: "RunState"
    ledger: "Ledger"
    gemini: "Gemini | None"  # None in --dry-run

    @property
    def dry_run(self) -> bool:
        return self.gemini is None

    def require_gemini(self) -> "Gemini":
        if self.gemini is None:
            raise RuntimeError("This stage needs a live Gemini client (not --dry-run).")
        return self.gemini
