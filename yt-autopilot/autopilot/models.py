"""Runtime model discovery.

Gemini's image and TTS model ids are preview-tier and get renamed regularly
(gemini-2.5-flash-preview-tts, gemini-3.1-flash-tts-preview, gemini-3-1-flash-image,
gemini-3-pro-image-preview all existed during 2026). Hardcoding one means the
pipeline breaks silently months from now, on a machine we cannot see.

So instead: ask the API what exists, score the candidates for each role, and
cache the winners. Hardcoded ids appear only as a last-resort fallback, and
the cache can be overridden by hand.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .config import MODEL_CACHE

# Roles the pipeline needs filled.
ROLES = ("text", "tts", "image", "image_pro")

# Used only when discovery fails outright (offline, bad key, API change).
# Checked against the live catalogue. `gemini-flash-latest` is an alias Google
# repoints, so it is the safest text fallback; the rest prefer stable ids.
FALLBACKS = {
    "text": "gemini-flash-latest",
    "tts": "gemini-3.1-flash-tts-preview",
    "image": "gemini-3.1-flash-image",
    "image_pro": "gemini-3-pro-image",
}

# Never select these for any role.
_EXCLUDE = re.compile(
    r"embedding|aqa|imagen|veo|learnlm|gemma|live|native-audio|realtime|robotics"
)
_VERSION = re.compile(r"(\d+(?:[.-]\d+)?)")
_UNSTABLE = re.compile(r"preview|-exp\b|experimental")

# Smaller than the 0.1 gap between adjacent versions, so a newer model still wins
# and the penalty only breaks ties between a model and its own preview twin.
# Preview tiers carry tighter rate limits and can be withdrawn without notice.
_PREVIEW_PENALTY = 0.05


def _version_score(name: str) -> float:
    """Rough version ordering, so 3.1 beats 2.5 when both are present."""
    match = _VERSION.search(name)
    if not match:
        return 0.0
    try:
        return float(match.group(1).replace("-", "."))
    except ValueError:
        return 0.0


def _score(name: str, actions: list[str], role: str) -> float:
    """How well a model fits a role. Negative means unusable."""
    n = name.lower()
    if _EXCLUDE.search(n):
        return -1.0

    is_tts = "tts" in n
    is_image = "image" in n
    is_pro = "pro" in n
    is_lite = "lite" in n
    is_flash = "flash" in n

    if role == "tts":
        if not is_tts:
            return -1.0
        # Cheapest capable tier wins. The penalty is deliberately tiny: every TTS
        # model in the catalogue is preview-only, so this must not disqualify them.
        return (
            100 + _version_score(n) + (5 if is_flash else 0) - (10 if is_pro else 0)
            - (_PREVIEW_PENALTY if _UNSTABLE.search(n) else 0)
        )

    if role == "image":
        if not is_image or is_tts:
            return -1.0
        # The cheap tier: flash, explicitly not pro. Lite is cheaper still but
        # visibly weaker, and without this it ties its non-lite sibling exactly.
        return (
            100 + _version_score(n)
            + (10 if is_flash else 0)
            - (20 if is_pro else 0)
            - (5 if is_lite else 0)
            - (_PREVIEW_PENALTY if _UNSTABLE.search(n) else 0)
        )

    if role == "image_pro":
        if not is_image or is_tts:
            return -1.0
        # Pro renders legible text, which is what a thumbnail needs.
        return (
            100 + _version_score(n) + (20 if is_pro else 0)
            - (_PREVIEW_PENALTY if _UNSTABLE.search(n) else 0)
        )

    # role == "text"
    if is_tts or is_image:
        return -1.0
    if actions and "generateContent" not in actions:
        return -1.0
    # Flash is the cost/quality sweet spot; lite writes noticeably flatter scripts.
    return (
        100 + _version_score(n) + (10 if is_flash else 0) - (15 if is_lite else 0)
        - (_PREVIEW_PENALTY if _UNSTABLE.search(n) else 0)
    )


# How many models to keep per role. The newest model is also the one everyone
# else is hitting, so the first choice is the likeliest to answer 503. Keeping
# ranked alternates lets a saturated model be stepped over instead of retried.
CANDIDATES_PER_ROLE = 3


@dataclass
class ModelSet:
    """The model chosen for each role, plus ranked alternates to fall back on."""

    text: str
    tts: str
    image: str
    image_pro: str
    discovered: bool = False
    alternates: dict[str, list[str]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, str]:
        return {r: getattr(self, r) for r in ROLES}

    def candidates(self, role: str) -> list[str]:
        """The preferred model for a role, then its fallbacks."""
        return [getattr(self, role), *self.alternates.get(role, [])]

    def __str__(self) -> str:
        source = "discovered" if self.discovered else "fallback"
        rows = []
        for r in ROLES:
            spare = self.alternates.get(r, [])
            tail = f"   (else: {', '.join(spare)})" if spare else ""
            rows.append(f"    {r:<10} {getattr(self, r)}{tail}")
        return f"  models ({source}):\n" + "\n".join(rows)


def _available(api_key: str) -> list[tuple[str, list[str]]]:
    """(name, supported_actions) for every model the key can reach."""
    from google import genai

    client = genai.Client(api_key=api_key)
    out: list[tuple[str, list[str]]] = []
    for model in client.models.list():
        name = (model.name or "").removeprefix("models/")
        if name:
            out.append((name, list(model.supported_actions or [])))
    return out


def discover(api_key: str, refresh: bool = False) -> ModelSet:
    """Resolve every role, preferring cache, then the live API, then fallbacks."""
    if not refresh and MODEL_CACHE.exists():
        try:
            cached = json.loads(MODEL_CACHE.read_text())
            if all(cached.get(r) for r in ROLES):
                return ModelSet(
                    **{r: cached[r] for r in ROLES},
                    discovered=True,
                    alternates=cached.get("alternates", {}),
                )
        except (json.JSONDecodeError, TypeError):
            pass  # Corrupt cache is not worth failing over; re-discover.

    try:
        catalog = _available(api_key)
    except Exception as exc:  # network, auth, or an SDK change
        print(f"  ! model discovery failed ({type(exc).__name__}: {exc})")
        print("  ! falling back to known-good ids; run `models --refresh` later")
        return ModelSet(**FALLBACKS)

    chosen: dict[str, str] = {}
    alternates: dict[str, list[str]] = {}
    for role in ROLES:
        ranked = [
            n for n, score in sorted(
                ((n, _score(n, a, role)) for n, a in catalog),
                key=lambda pair: pair[1],
                reverse=True,
            )
            if score > 0
        ]
        if ranked:
            chosen[role] = ranked[0]
            alternates[role] = ranked[1:CANDIDATES_PER_ROLE]
        else:
            chosen[role] = FALLBACKS[role]
            alternates[role] = []
            print(f"  ! no model matched role '{role}'; using {FALLBACKS[role]}")

    MODEL_CACHE.write_text(json.dumps({**chosen, "alternates": alternates}, indent=2))
    return ModelSet(**chosen, discovered=True, alternates=alternates)
