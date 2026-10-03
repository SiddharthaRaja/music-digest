"""Optional AI summary written by Claude (only runs when ANTHROPIC_API_KEY is set)."""
from __future__ import annotations

import json
import os

import requests

from util import describe_error

API_URL = "https://api.anthropic.com/v1/messages"


def ai_summary(sections, cfg: dict, artists_followed: list[str], log=print) -> dict | None:
    ai_cfg = cfg.get("ai") or {}
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    enabled = ai_cfg.get("enabled", "auto")
    if enabled is False or str(enabled).lower() == "false" or not key:
        return None
    budget = int(ai_cfg.get("max_headlines", 160))
    blocks, n = [], 0
    usable = [s for s in sections if s.stories]
    per_section = max(4, budget // max(1, len(usable)))
    for sec in usable:
        lines = []
        for st in sec.stories[:per_section]:
            n += 1
            line = f"- {st.lead.title} ({', '.join(st.sources[:3])})"
            if st.lead.summary:
                line += f" — {st.lead.summary[:160]}"
            lines.append(line)
        blocks.append(f"## {sec.name} [id: {sec.id}]\n" + "\n".join(lines))
    if not blocks:
        return None
    prompt = f"""You write the top of a daily music-news email for an independent artist preparing to release their first single.
They follow the whole industry: superstars, rising and independent artists, the US and UK, and underground scenes.

Today's headlines, grouped by the email's sections:

{chr(10).join(blocks)}

Reply with ONLY a JSON object, no other text:
{{
  "brief": ["4 to 6 bullets: the most important things that happened, one plain-English sentence each"],
  "section_notes": {{"<section id>": "one sentence capturing the main thread of that section today"}},
  "releases": [{{"artist": "", "release": "", "date": ""}}],
  "artist_takeaway": ""
}}
Rules:
- section_notes: only for sections where there is a real thread worth naming; use the ids exactly as given.
- releases: upcoming releases whose date is stated in the headlines or summaries (date as written, e.g. "Oct 17"). Max 12. [] if none.
- artist_takeaway: one or two sentences on something practical an independent artist could take from today's news (release timing, rollout tactics, platform or industry changes). "" if nothing useful.
- Use only facts present above. Never guess numbers or dates."""
    try:
        resp = requests.post(
            API_URL,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": ai_cfg.get("model", "claude-haiku-4-5-20251001"), "max_tokens": 2000,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=120,
        )
        resp.raise_for_status()
        text = "".join(b.get("text", "") for b in resp.json().get("content", []) if b.get("type") == "text")
        data = json.loads(text[text.find("{"): text.rfind("}") + 1])
    except Exception as exc:
        log(f"  AI summary skipped ({describe_error(exc)})")
        return None
    notes = data.get("section_notes") or {}
    return {
        "brief": [str(b).strip() for b in data.get("brief") or [] if str(b).strip()][:6],
        "section_notes": {str(k): str(v).strip() for k, v in notes.items() if str(v).strip()} if isinstance(notes, dict) else {},
        "releases": [r for r in data.get("releases") or [] if isinstance(r, dict) and r.get("artist")][:12],
        "artist_takeaway": str(data.get("artist_takeaway") or "").strip(),
        "headlines_used": n,
    }
