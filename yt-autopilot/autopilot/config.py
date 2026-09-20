"""Configuration loading: channel.yaml, .env, paths and prompt templates."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
PROMPTS_DIR = CONFIG_DIR / "prompts"
RUNS_DIR = ROOT / "runs"
LEDGER_DB = ROOT / "ledger.db"
MODEL_CACHE = CONFIG_DIR / "models.cache.json"


class ConfigError(RuntimeError):
    """Raised when configuration is missing or malformed."""


@dataclass
class Config:
    """Parsed channel.yaml plus environment secrets."""

    raw: dict[str, Any]

    # -- section accessors -------------------------------------------------
    @property
    def channel(self) -> dict[str, Any]:
        return self.raw.get("channel", {})

    @property
    def format(self) -> dict[str, Any]:
        return self.raw.get("format", {})

    @property
    def voice_over(self) -> dict[str, Any]:
        return self.raw.get("voice_over", {})

    @property
    def visuals(self) -> dict[str, Any]:
        return self.raw.get("visuals", {})

    @property
    def captions(self) -> dict[str, Any]:
        return self.raw.get("captions", {})

    @property
    def originality(self) -> dict[str, Any]:
        return self.raw.get("originality", {})

    @property
    def publish(self) -> dict[str, Any]:
        return self.raw.get("publish", {})

    @property
    def review(self) -> dict[str, Any]:
        return self.raw.get("review", {})

    # -- derived -----------------------------------------------------------
    @property
    def dimensions(self) -> tuple[int, int]:
        """Frame size for the configured format profile."""
        if self.format.get("profile", "short") == "short":
            return (1080, 1920)
        return (1920, 1080)

    @property
    def gemini_key(self) -> str:
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise ConfigError(
                "GEMINI_API_KEY is not set.\n"
                "  1. Get a key at https://aistudio.google.com/apikey\n"
                "  2. cp .env.example .env\n"
                "  3. Put the key in .env as GEMINI_API_KEY=..."
            )
        return key


def load_config(path: Path | None = None) -> Config:
    """Load .env then channel.yaml."""
    load_dotenv(ROOT / ".env")
    cfg_path = path or (CONFIG_DIR / "channel.yaml")
    if not cfg_path.exists():
        raise ConfigError(f"Missing config file: {cfg_path}")
    data = yaml.safe_load(cfg_path.read_text()) or {}
    return Config(raw=data)


def load_prompt(name: str, **fields: Any) -> str:
    """Load a prompt template and substitute {placeholders}.

    Templates use str.format, so any literal brace in a template (the JSON
    examples) must be doubled. Missing fields raise rather than silently
    emitting a broken prompt.
    """
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise ConfigError(f"Missing prompt template: {path}")
    try:
        return path.read_text().format(**fields)
    except KeyError as exc:
        raise ConfigError(
            f"Prompt '{name}' references {exc} but it was not supplied. "
            f"Either pass it, or double the braces if it is literal JSON."
        ) from exc
