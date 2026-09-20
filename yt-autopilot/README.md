# yt-autopilot

An automated YouTube Shorts pipeline. It researches a topic, writes a script,
narrates it, generates the visuals, assembles the video, makes a thumbnail,
shows you everything for approval, and uploads.

**You never open a video editor.** FFmpeg does all of it.

```
ideate → script → voice → visuals → assemble → thumbnail → REVIEW → publish
```

---

## Setup

### 1. Install

```bash
cd yt-autopilot
pip install -r requirements.txt
```

FFmpeg comes bundled via `imageio-ffmpeg` — nothing to install by hand.

### 2. Gemini key (required)

Get a **free** key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
No credit card.

> **A Gemini Pro / Google AI Pro subscription is not API access.** That is a
> consumer chat product; its Veo allowance lives in the Flow web UI and no
> script can authenticate against it. The API key above is separate, and free.

```bash
cp .env.example .env
# open .env and set GEMINI_API_KEY=...
```

### 3. YouTube upload (needed only for the last stage)

1. [Google Cloud Console](https://console.cloud.google.com/) → create a project
2. Enable **YouTube Data API v3**
3. APIs & Services → Credentials → Create OAuth client ID → type **Desktop app**
4. Download the JSON, save it as `client_secret.json` here
5. Run it once:

```bash
python scripts/auth_youtube.py
```

### 4. Higgsfield (optional, costs money)

Only if you want real generated video on the hook instead of a still.

```bash
cp .env.local.example .env.local
# set HF_KEY="your-key-id:your-key-secret" from https://cloud.higgsfield.ai/
```

Then set `visuals.use_higgsfield: true` in `config/channel.yaml`.

> **A free Higgsfield plan cannot generate anything.** Tested against a live
> free account with 10 credits: the API refuses with
> `Requires basic plan or higher`, before credits are even consulted. Credits
> alone are not enough — you need at least a Basic plan for any generation to
> run, through the SDK or otherwise.
>
> **The SDK path is also unverified against the live API.** It was written from
> the official SDK but could not be run from the environment it was built in.
> Once you are on a paid plan, check it with `python main.py`, which should
> print a video URL.

**`.env` and `.env.local` are gitignored. Never paste either into a chat.**

---

## Use it

```bash
python -m autopilot run --dry-run   # full run, no API calls, no spend — start here
python -m autopilot run             # make a real video
```

| Command | What it does |
|---|---|
| `run` | Make a video start to finish |
| `run --dry-run` | Same path, no API calls, no cost |
| `resume` | Continue after an interruption |
| `stage <name>` | Re-run one stage (e.g. `stage script`) |
| `list` | Recent runs and how far each got |
| `voices` | The 30 narration voices |
| `models --refresh` | Re-resolve Gemini model ids |

Stages are resumable. Kill it at any point and `resume` picks up where it
stopped — a failure at the visuals stage never costs you the script.

Re-running a stage invalidates everything after it, so
`stage script` then `resume` rebuilds the video with the new script.

---

## The file you actually edit

`config/channel.yaml`. The three settings that matter most:

```yaml
channel:
  niche: "..."    # Be specific. "space" is too broad.
  voice: "..."    # Your channel's personality. Biggest lever on quality.
visuals:
  style: "..."    # Applied to every image. Keeps the channel recognisable.
```

Prompt templates live in `config/prompts/` and are plain Markdown — edit them
to change how scripts get written.

---

## Free tier

Everything runs on Gemini's free tier. One quota binds before the others:

| Quota | Free limit | Used per video | Ceiling |
|---|---|---|---|
| **TTS** | **15 req/day** | 1 (batch mode) | **15 videos/day** |
| Images | ~500 req/day | 7 | ~71 videos/day |
| Text | ~1,500 req/day | ~3 | not binding |

`voice_over.batch: true` (the default) sends one TTS request per video. Setting
it to `false` sends one per beat — exact timings, but it drops you to about
2 videos/day. Switch it off once you are on billing.

Hitting the daily cap stops the run with a clear message rather than retrying;
the run is saved, so `resume` continues it after the quota resets at midnight
Pacific.

## Cost

Roughly, per 45-second Short:

| Item | Cost |
|---|---|
| Script + metadata (Gemini Flash text) | ~free tier |
| Narration (Gemini TTS) | cents |
| 6 scene images (Flash Image tier) | low cents each |
| 1 thumbnail (Pro Image tier) | ~$0.13 |
| Assembly (FFmpeg) | $0 |
| **Total** | **under $1** |

Higgsfield on the hook adds roughly $0.20–$1.00 when enabled.

Generating the whole video with Veo-class models instead would cost $7–25 per
Short. That is why stills plus Ken Burns motion is the default.

---

## Why there is a review gate

YouTube's 2026 inauthentic-content policy is enforced **at channel level**, not
per video. Generic, repetitive or template-shaped output gets the whole channel
demonetized: warning → 90-day suspension → permanent removal from the Partner
Program. AI content stays monetizable if it carries original value and is
disclosed.

So two things are built in and should stay on:

- **The ledger** (`originality` in the config) records every published topic,
  hook and structure, and rejects a new script that is too close to a recent
  one. Structures are rotated deliberately rather than reused.
- **The review gate** shows you the video, title, thumbnail and script on one
  page before anything uploads.

Uploads set `status.containsSyntheticMedia`, so the altered-or-synthetic
disclosure is automatic instead of something you have to remember in Studio.

Turning these off is how channels get themselves banned.

---

## Troubleshooting

**`GEMINI_API_KEY is not set`** — you skipped step 2, or `.env` is in the wrong
directory. It belongs next to `README.md`.

**`Not authorised to upload to YouTube`** — run `python scripts/auth_youtube.py`.

**`All proposed topics were too close to recent videos`** — the anti-repetition
guard working as intended. Widen `channel.niche`, or raise
`originality.max_similarity`.

**`Could not write a hook distinct from recent videos`** — same guard, at the
script stage. Raise `originality.max_regenerations`, or pick a different angle.

**Captions hidden behind the YouTube UI** — lower `captions.position`. Anything
below 390px from the bottom is clamped automatically, and you'll see a warning.

**`hit the daily free-tier quota`** — expected on the free tier. Resets at
midnight Pacific; `python -m autopilot resume` picks the run back up. Check
`voice_over.batch` is `true`.

**`every candidate model was overloaded`** — Gemini is busy, not broken. The
pipeline already tried three different models. Wait a few minutes and run
`python -m autopilot resume`; the run is saved and picks up where it stopped.
Newer models (the default first pick) are busiest at peak times.

**`ffmpeg failed`** — run with `--traceback` for the full error. The most common
cause is a generated image that failed to download; re-run `stage visuals`.

**Narration longer than 180s** — Shorts are capped at 3 minutes. Lower
`format.target_seconds` or `format.beats`.

---

## Layout

```
autopilot/
  cli.py          commands
  config.py       loads channel.yaml, .env, prompts
  state.py        resumable per-run state
  ledger.py       anti-repetition store (SQLite)
  models.py       resolves Gemini model ids at runtime
  youtube.py      OAuth
  providers/      gemini.py, higgsfield.py
  stages/         the eight stages, one file each
config/
  channel.yaml    your settings
  prompts/        editable prompt templates
runs/             per-video working dirs (gitignored)
main.py           standalone Higgsfield example
```

Gemini model ids are resolved at runtime via ListModels rather than hardcoded,
because the image and TTS ids are preview-tier and get renamed. If generation
starts failing after a rename, `python -m autopilot models --refresh`.
