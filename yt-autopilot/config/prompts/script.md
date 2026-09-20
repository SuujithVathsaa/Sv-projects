Write a {target_seconds}-second vertical video script.

TOPIC: {topic}
ANGLE: {angle}
KEY SURPRISE: {surprise}
CHANNEL VOICE: {voice}
AUDIENCE: {audience}

STRUCTURE TO USE: {structure}
You must follow this structure. It is assigned deliberately to keep the
channel from falling into one repetitive shape.

AVOID THESE OPENINGS — recent videos already used them, and reusing their
shape puts the channel's monetization at risk:
{avoid_openings}

Requirements:
- Exactly {beats} beats.
- Total narration must read aloud in about {target_seconds} seconds at a
  natural pace. That is roughly {word_budget} words TOTAL. Count them.
- Beat 1 is the hook and must land in under 2 seconds of speech. Open on the
  concrete and specific. No "Did you know", no "Imagine if", no rhetorical
  question, no "Here's why".
- Write how a person talks. Contractions. Varied sentence length. At least one
  sentence under five words.
- No filler phrases: "the truth is", "what's fascinating", "little did they know".
- End on the consequence or the unresolved part. Do not end with a call to
  subscribe, and do not summarize what you just said.
- Each beat needs a "visual" — a literal description of one image. Describe
  what is physically in frame. No abstractions, no text-in-image, no camera
  directions.

Return JSON only, no prose:
{{"title_working": "...",
  "structure_used": "{structure}",
  "beats": [{{"narration": "...", "visual": "..."}}]}}
