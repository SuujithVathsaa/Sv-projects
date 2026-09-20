"""Stage 7 — the human gate.

This is the stage that keeps the channel alive. YouTube's inauthentic-content
policy is enforced against the channel, so a run of videos nobody looked at is
the fastest route to losing monetization on all of them. Everything the
pipeline produced is laid out on one page, and nothing uploads until you say so.
"""

from __future__ import annotations

import html
import webbrowser
from pathlib import Path

from . import Context

PAGE_CSS = """
:root { color-scheme: light dark; --bg:#fff; --fg:#14171a; --muted:#5b6570;
        --line:#e3e8ee; --accent:#2f6fed; }
@media (prefers-color-scheme: dark) { :root {
        --bg:#14171a; --fg:#e9edf2; --muted:#9aa5b1; --line:#262c33; --accent:#7aa2f7; } }
* { box-sizing:border-box; }
body { margin:0; padding:32px 16px; background:var(--bg); color:var(--fg);
       font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
.wrap { max-width:960px; margin:0 auto; }
h1 { font-size:22px; margin:0 0 4px; }
.sub { color:var(--muted); margin:0 0 28px; font-size:14px; }
.grid { display:grid; grid-template-columns:320px 1fr; gap:28px; align-items:start; }
@media (max-width:760px) { .grid { grid-template-columns:1fr; } }
video, .thumb { width:100%; border-radius:12px; border:1px solid var(--line);
                background:#000; display:block; }
.card { border:1px solid var(--line); border-radius:12px; padding:18px; margin-bottom:18px; }
.label { font-size:12px; text-transform:uppercase; letter-spacing:.06em;
         color:var(--muted); margin-bottom:6px; }
.title { font-size:19px; font-weight:600; margin-bottom:14px; }
.desc { white-space:pre-wrap; }
.tags { display:flex; flex-wrap:wrap; gap:8px; margin-top:8px; }
.tag { background:var(--line); border-radius:999px; padding:3px 11px; font-size:13px; }
table { width:100%; border-collapse:collapse; font-size:14px; }
td { padding:7px 0; border-bottom:1px solid var(--line); vertical-align:top; }
td:first-child { color:var(--muted); width:42%; }
.beat { padding:12px 0; border-bottom:1px solid var(--line); }
.beat:last-child { border-bottom:0; }
.beat .n { color:var(--muted); font-size:13px; }
.flag { display:inline-block; padding:3px 10px; border-radius:999px;
        font-size:13px; background:var(--accent); color:#fff; }
"""


def _build_page(ctx: Context, out: Path) -> Path:
    cfg, state = ctx.cfg, ctx.state
    meta = state.get("metadata", {})
    video = Path(state["video"])
    thumb = Path(state["thumbnail"])

    beats_html = "".join(
        f'<div class="beat"><div class="n">Beat {i + 1} · '
        f'{state["audio_clips"][i]["seconds"]:.1f}s</div>'
        f'<div>{html.escape(b.get("narration", ""))}</div></div>'
        for i, b in enumerate(state["script"]["beats"])
    )
    tags_html = "".join(
        f'<span class="tag">{html.escape(t)}</span>' for t in meta.get("tags", [])
    )
    disclose = bool(cfg.publish.get("disclose_synthetic", True))

    rows = {
        "Run": state.run_id,
        "Duration": f"{state.get('duration', 0):.1f}s",
        "Structure": state["script"].get("structure_used", "—"),
        "Privacy on upload": cfg.publish.get("privacy", "private"),
        "Synthetic-content disclosure": "on" if disclose else "OFF",
        "Made for kids": "yes" if cfg.publish.get("made_for_kids") else "no",
    }
    rows_html = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>"
        for k, v in rows.items()
    )

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Review — {html.escape(meta.get('title', 'Untitled'))}</title>
<style>{PAGE_CSS}</style></head><body><div class="wrap">
<h1>Review before publishing</h1>
<p class="sub">Nothing uploads until you approve this in the terminal.</p>
<div class="grid">
  <div>
    <video controls playsinline src="{html.escape(video.name)}"></video>
    <div class="label" style="margin-top:16px">Thumbnail</div>
    <img class="thumb" src="{html.escape(thumb.name)}" alt="thumbnail">
  </div>
  <div>
    <div class="card">
      <div class="label">Title</div>
      <div class="title">{html.escape(meta.get('title', '—'))}</div>
      <div class="label">Description</div>
      <div class="desc">{html.escape(meta.get('description', '—'))}</div>
      <div class="tags">{tags_html}</div>
    </div>
    <div class="card"><table>{rows_html}</table></div>
    <div class="card">
      <div class="label" style="margin-bottom:10px">Script</div>{beats_html}
    </div>
    <div class="card">
      <span class="flag">Check before approving</span>
      <ul style="margin:12px 0 0; padding-left:20px; color:var(--muted)">
        <li>Does the hook earn the next two seconds?</li>
        <li>Is anything factually wrong? You are responsible for what you publish.</li>
        <li>Are captions fully visible, not hidden behind the phone UI?</li>
        <li>Does this feel different from your last few videos?</li>
      </ul>
    </div>
  </div>
</div></div></body></html>"""
    out.write_text(page, encoding="utf-8")
    return out


def run(ctx: Context) -> None:
    cfg, state = ctx.cfg, ctx.state
    state.require("video", "thumbnail", "metadata")

    page = _build_page(ctx, state.path("output", "review.html"))
    print(f"  review page: {page}")

    if not cfg.review.get("required", True):
        print("  review.required is false — skipping the gate")
        state.set("approved", True)
        return

    if ctx.dry_run:
        print("  [dry-run] skipping the approval prompt")
        state.set("approved", False)
        return

    try:
        webbrowser.open(page.resolve().as_uri())
    except Exception:
        pass  # Headless machine; the printed path is enough.

    answer = input("\n  Publish this video? [y/N] ").strip().lower()
    approved = answer in ("y", "yes")
    state.set("approved", approved)
    if not approved:
        print("  not approved — nothing was uploaded.")
        print(f"  re-run a stage to change it, e.g. `python -m autopilot stage script`")
