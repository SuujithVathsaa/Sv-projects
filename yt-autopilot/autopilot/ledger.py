"""Anti-repetition ledger.

YouTube's inauthentic-content policy is enforced at channel level: a channel
whose videos are generic, repetitive or template-shaped loses monetization,
however good any single video is. So the pipeline records what it has already
made and refuses to make something too close to it again.

Similarity uses Jaccard overlap on content-word sets. It is deliberately
simple — no embedding model, no extra dependency, no API call — and it is
sufficient for catching the failure mode that matters here, which is the
generator drifting into one repeated shape.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .config import LEDGER_DB

# Structural shapes rotated across videos so the channel never settles into
# a single recognisable template.
STRUCTURES = [
    "cold open on the aftermath, then rewind to explain how it happened",
    "chronological build: the decision, the warning missed, the consequence",
    "start from the everyday object, zoom out to the hidden system behind it",
    "compare two cases that look identical but ended differently",
    "follow one person's point of view through the event",
    "lead with the number that sounds wrong, then justify it",
    "describe the fix first, then reveal the problem it was built for",
]

_WORD = re.compile(r"[a-z']+")
_STOP = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at", "for",
    "with", "by", "from", "as", "is", "are", "was", "were", "be", "been", "it",
    "its", "this", "that", "these", "those", "you", "your", "they", "their",
    "what", "when", "how", "why", "which", "who", "we", "our", "not", "no",
    "so", "if", "than", "then", "there", "here", "into", "out", "up", "down",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT,
    created_at   TEXT NOT NULL,
    topic        TEXT NOT NULL,
    angle        TEXT,
    opening      TEXT,
    structure    TEXT,
    beat_count   INTEGER,
    title        TEXT,
    video_id     TEXT
);
"""


def _tokens(text: str) -> set[str]:
    """Content words of a string, lowercased, stopwords removed."""
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP and len(w) > 2}


def similarity(a: str, b: str) -> float:
    """Jaccard overlap of two strings' content words, 0.0-1.0."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class Ledger:
    """Record of everything the channel has already produced."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or LEDGER_DB
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def _rows(self, column: str, limit: int) -> list[str]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            cur = conn.execute(
                f"SELECT {column} FROM videos WHERE {column} IS NOT NULL "
                f"ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            return [r[0] for r in cur.fetchall()]

    # -- reads -------------------------------------------------------------
    def recent_topics(self, limit: int = 25) -> list[str]:
        return self._rows("topic", limit)

    def recent_openings(self, limit: int = 25) -> list[str]:
        return self._rows("opening", limit)

    def recent_structures(self, limit: int = 25) -> list[str]:
        return self._rows("structure", limit)

    def count(self) -> int:
        with closing(sqlite3.connect(self.db_path)) as conn:
            return conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]

    # -- checks ------------------------------------------------------------
    def closest(self, text: str, column: str, limit: int) -> tuple[float, str]:
        """Highest similarity between `text` and recent values of `column`."""
        best, match = 0.0, ""
        for prior in self._rows(column, limit):
            score = similarity(text, prior)
            if score > best:
                best, match = score, prior
        return best, match

    def is_too_similar(
        self, text: str, column: str, threshold: float, limit: int
    ) -> tuple[bool, float, str]:
        score, match = self.closest(text, column, limit)
        return score > threshold, score, match

    def next_structure(self, rotate: bool = True) -> str:
        """Pick the structural shape used least recently."""
        if not rotate:
            return STRUCTURES[0]
        recent = self.recent_structures(len(STRUCTURES))
        for structure in STRUCTURES:
            if structure not in recent:
                return structure
        # All used recently — take the one used longest ago.
        return recent[-1] if recent else STRUCTURES[0]

    # -- writes ------------------------------------------------------------
    def record(
        self,
        run_id: str,
        topic: str,
        angle: str = "",
        opening: str = "",
        structure: str = "",
        beat_count: int = 0,
        title: str = "",
        video_id: str = "",
    ) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO videos (run_id, created_at, topic, angle, opening, "
                "structure, beat_count, title, video_id) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    datetime.now(timezone.utc).isoformat(),
                    topic,
                    angle,
                    opening,
                    structure,
                    beat_count,
                    title,
                    video_id,
                ),
            )
            conn.commit()
