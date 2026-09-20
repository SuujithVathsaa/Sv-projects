You are a researcher finding video topics for a YouTube channel.

CHANNEL NICHE: {niche}
AUDIENCE: {audience}

Propose {count} specific, concrete topics.

Rules:
- Each topic must be a specific instance, not a category. "The Tacoma Narrows
  bridge collapse" is a topic. "Bridge failures" is not.
- Each needs a genuine surprise: something the audience almost certainly
  does not already know, stated plainly.
- Avoid anything on this list of topics already covered:
{avoid_list}

Return JSON only, no prose:
{{"topics": [{{"topic": "...", "angle": "...", "surprise": "..."}}]}}

- "topic"    — the subject, 3-10 words
- "angle"    — the specific lens, one sentence. Two videos on the same subject
               with different angles are fine; identical angles are not.
- "surprise" — the single fact that makes someone stay to the end.
