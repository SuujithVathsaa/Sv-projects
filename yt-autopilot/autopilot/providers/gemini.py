"""Gemini backend: structured text, text-to-speech, and images."""

from __future__ import annotations

import json
import re
import struct
import time
import wave
from pathlib import Path
from typing import Any

from ..models import ModelSet

# TTS returns raw signed 16-bit little-endian PCM at 24 kHz, mono.
TTS_SAMPLE_RATE = 24_000
TTS_CHANNELS = 1
TTS_SAMPLE_WIDTH = 2

_RETRYABLE = ("503", "502", "500", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "overloaded")

# A per-minute limit clears on its own; a per-day one does not. Retrying a spent
# daily quota just burns four backoff delays and then fails obscurely, so the two
# are told apart by the quota id Google returns in the error.
_DAILY_QUOTA = re.compile(r"per.?day|requests?_per_day|daily.{0,12}limit", re.IGNORECASE)


class GeminiError(RuntimeError):
    """A Gemini call failed in a way retrying will not fix."""


class DailyQuotaExhausted(GeminiError):
    """The free tier's daily allowance for this model is gone until it resets."""


class Gemini:
    """Thin wrapper over google-genai covering the three things we need."""

    def __init__(self, api_key: str, models: ModelSet, max_retries: int = 4):
        from google import genai

        self._genai = genai
        self.client = genai.Client(api_key=api_key)
        self.models = models
        self.max_retries = max_retries

    # -- retry -------------------------------------------------------------
    def _call(self, fn, what: str):
        """Run `fn`, retrying transient API failures with exponential backoff."""
        delay = 2.0
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return fn()
            except Exception as exc:  # SDK raises a variety of error classes
                last = exc
                text = f"{type(exc).__name__}: {exc}"
                if _DAILY_QUOTA.search(text):
                    raise DailyQuotaExhausted(
                        f"{what} hit the daily free-tier quota.\n"
                        f"  It resets at midnight Pacific.\n"
                        f"  Free-tier TTS allows 15 requests a day, which is 15 videos\n"
                        f"  in batch mode or 2 with `voice_over.batch: false`.\n"
                        f"  The run is saved — `python -m autopilot resume` continues it."
                    ) from exc
                if not any(token in text for token in _RETRYABLE):
                    raise GeminiError(f"{what} failed — {text}") from exc
                if attempt < self.max_retries - 1:
                    print(f"    transient error on {what}, retrying in {delay:.0f}s")
                    time.sleep(delay)
                    delay *= 2
        raise GeminiError(f"{what} failed after {self.max_retries} attempts — {last}")

    # -- text --------------------------------------------------------------
    def json(self, prompt: str, *, temperature: float = 1.0) -> dict[str, Any]:
        """Generate and parse a JSON object."""
        from google.genai import types

        def run():
            return self.client.models.generate_content(
                model=self.models.text,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    response_mime_type="application/json",
                ),
            )

        response = self._call(run, "text generation")
        raw = (response.text or "").strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Some models still wrap JSON in a fenced block despite the mime type.
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                raise GeminiError(f"Model did not return JSON. Got: {raw[:300]}")
            return json.loads(match.group(0))

    # -- speech ------------------------------------------------------------
    def speak(self, text: str, out_path: Path, *, voice: str, style: str = "") -> Path:
        """Synthesise `text` to a mono 24 kHz WAV file."""
        from google.genai import types

        prompt = f"{style}\n\n{text}".strip() if style else text

        def run():
            return self.client.models.generate_content(
                model=self.models.tts,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voice
                            )
                        )
                    ),
                ),
            )

        response = self._call(run, "speech synthesis")
        pcm = self._first_inline(response, "audio")
        if pcm is None:
            raise GeminiError(
                "TTS returned no audio. The voice name may be invalid — "
                "run `python -m autopilot voices` to list valid names."
            )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as wav:
            wav.setnchannels(TTS_CHANNELS)
            wav.setsampwidth(TTS_SAMPLE_WIDTH)
            wav.setframerate(TTS_SAMPLE_RATE)
            wav.writeframes(pcm)
        return out_path

    # -- images ------------------------------------------------------------
    def image(self, prompt: str, out_path: Path, *, pro: bool = False) -> Path:
        """Generate one image. `pro` selects the tier that renders text legibly."""
        from google.genai import types

        model = self.models.image_pro if pro else self.models.image

        def run():
            return self.client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                ),
            )

        response = self._call(run, "image generation")
        data = self._first_inline(response, "image")
        if data is None:
            raise GeminiError(
                f"Image model {model} returned no image. The prompt may have been "
                f"blocked by a safety filter — try rewording the scene description."
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
        return out_path

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _first_inline(response: Any, kind: str) -> bytes | None:
        """First inline blob whose mime type starts with `kind`."""
        for candidate in response.candidates or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                blob = getattr(part, "inline_data", None)
                if blob and (blob.mime_type or "").startswith(kind) and blob.data:
                    return blob.data
        return None


def silent_wav(out_path: Path, seconds: float) -> Path:
    """A valid silent WAV, used by --dry-run so assembly is exercised for real."""
    frames = int(TTS_SAMPLE_RATE * max(seconds, 0.1))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as wav:
        wav.setnchannels(TTS_CHANNELS)
        wav.setsampwidth(TTS_SAMPLE_WIDTH)
        wav.setframerate(TTS_SAMPLE_RATE)
        wav.writeframes(struct.pack("<h", 0) * frames)
    return out_path
