"""Turns the collected news and charts into emails (and a full web-page copy)."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from util import ago, esc, nice_day, nice_time

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
CSS = f"""
body{{margin:0;padding:0;background:#f3f1ee}}
.wrap{{max-width:680px;margin:0 auto;background:#ffffff;font-family:{FONT};color:#16161a}}
.hd{{background:#16161a;padding:22px 24px;color:#ffffff}}
.kick{{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#ff8a65;font-weight:700}}
.big{{font-size:22px;font-weight:700;margin-top:4px;color:#ffffff}}
.sub{{font-size:13px;color:#b9b9c2;margin-top:6px;line-height:1.5}}
.sub b{{color:#ffffff;font-weight:600}}
.sec{{padding:26px 24px 0}}
.st{{font-size:13px;letter-spacing:.07em;text-transform:uppercase;color:#d9481f;font-weight:800;padding-bottom:7px;border-bottom:2px solid #16161a}}
.st span{{color:#6b6b76;font-weight:500;letter-spacing:0}}
.grp{{font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:#6b6b76;font-weight:700;padding:30px 24px 0}}
.note{{font-size:13px;color:#45454d;margin:9px 0 2px;line-height:1.45}}
.it{{padding:11px 0;border-bottom:1px solid #efece7}}
.t{{color:#16161a;font-weight:600;font-size:15px;line-height:1.35;text-decoration:none}}
.m{{font-size:12px;color:#6b6b76;margin-top:3px;line-height:1.4}}
.m a{{color:#6b6b76}}
.hot{{color:#d9481f;font-weight:700}}
.s{{font-size:13px;color:#45454d;margin-top:4px;line-height:1.45}}
.c{{display:inline-block;background:#fdeee8;color:#c2410c;border-radius:4px;padding:1px 6px;font-size:11px;font-weight:600;margin:0 4px 3px 0}}
.g{{display:inline-block;background:#eeeef1;color:#45454d;border-radius:4px;padding:1px 6px;font-size:11px;margin:0 4px 3px 0}}
.ln{{padding:5px 0;font-size:13px;line-height:1.4;border-bottom:1px solid #f6f4f1}}
.ln a{{color:#16161a;text-decoration:none}}
.ln span{{color:#6b6b76;font-size:12px}}
.more{{padding:7px 0 0;font-size:12px;color:#6b6b76}}
.ah{{padding:16px 0 2px;font-size:15px;font-weight:700}}
.ah span{{font-size:12px;font-weight:500;color:#6b6b76}}
.box{{background:#fdeee8;border-radius:10px;padding:15px 17px;margin-top:18px}}
.box2{{background:#f6f4f1;border-radius:10px;padding:13px 15px;margin-top:12px}}
.bt{{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#d9481f;font-weight:700}}
.box ul{{margin:8px 0 0;padding-left:18px;font-size:14px;line-height:1.45}}
.box li{{margin:0 0 6px}}
.day{{font-size:13px;font-weight:700;margin-top:10px}}
.day span{{color:#d9481f}}
table.ch{{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}}
.ch td{{padding:5px 4px;border-bottom:1px solid #f1eee9;vertical-align:top}}
.ch th{{padding:4px;font-size:11px;color:#6b6b76;text-align:left;font-weight:600;border-bottom:1px solid #e4e0da}}
.p{{width:22px;color:#6b6b76;font-size:12px}}
.mv{{width:38px;font-size:11px;white-space:nowrap}}
span.up{{color:#1f8a4c}}
span.dn{{color:#c0392b}}
span.nw{{color:#d9481f;font-weight:700;font-size:10px}}
span.eq{{color:#9a9aa3}}
.r{{text-align:right;color:#6b6b76;font-size:12px;white-space:nowrap}}
.a{{color:#6b6b76;font-size:12px}}
tr.hl td{{background:#fff4cc}}
.cn{{font-weight:700;font-size:14px;color:#16161a;text-decoration:none}}
.cd{{color:#6b6b76;font-size:12px}}
.chart{{padding:16px 0 4px}}
.ft{{padding:28px 24px 24px;font-size:11px;line-height:1.55;color:#6b6b76}}
"""


@dataclass
class Ctx:
    cfg: dict
    now: dt.datetime
    since: dt.datetime
    tz: object
    sections: list
    charts: list
    analysis: object
    health: list
    chart_health: list
    ai: dict | None = None
    calendar: dict = field(default_factory=dict)
    numbers: list = field(default_factory=list)
    total_items: int = 0
    pinned_artists: list = field(default_factory=list)

    @property
    def local_now(self):
        return self.now.astimezone(self.tz)

    @property
    def stories(self):
        return [st for s in self.sections for st in s.stories]

    @property
    def title(self):
        return self.cfg.get("digest_name", "Music Digest")


# --------------------------------------------------------------------------- #
# Small building blocks
# --------------------------------------------------------------------------- #
def chip(text: str, gray: bool = False) -> str:
    return f'<span class="{"g" if gray else "c"}">{esc(text)}</span>'


def story_full(st, now, hide_artist: str | None = None) -> str:
    lead = st.lead
    meta = [esc(lead.source)]
    when = ago(st.newest, now)
    if when:
        meta.append(when)
    also, seen = [], {lead.source}
    for o in st.items[1:]:
        if o.source not in seen:
            seen.add(o.source)
            also.append(f'<a href="{esc(o.link)}">{esc(o.source)}</a>')
    if also:
        meta.append("also " + ", ".join(also[:3]) + (f" +{len(also) - 3}" if len(also) > 3 else ""))
    hot = f' <span class="hot">&#9679; {len(st.sources)} outlets</span>' if len(st.sources) >= 3 else ""
    chips = "".join(chip(a.name) for a in st.artists if a.name != hide_artist)
    chips += "".join(chip(c, gray=True) for c in st.chips)
    summary = f'<div class="s">{esc(lead.summary)}</div>' if lead.summary else ""
    return (f'<div class="it">{chips}<a class="t" href="{esc(lead.link)}">{esc(lead.title)}</a>'
            f'<div class="m">{" &middot; ".join(meta)}{hot}</div>{summary}</div>')


def story_line(st) -> str:
    return (f'<div class="ln">&bull; <a href="{esc(st.lead.link)}">{esc(st.lead.title)}</a> '
            f'<span>{esc(st.lead.source)}</span></div>')


def section_head(icon: str, name: str, count, note: str = "", sub: str = "") -> str:
    n = f" <span>&middot; {count}</span>" if count not in (None, "") else ""
    out = f'<div class="st">{esc(icon)} {esc(name)}{n}</div>'
    if sub:
        out += f'<div class="note">{esc(sub)}</div>'
    if note:
        out += f'<div class="note"><b>Today:</b> {esc(note)}</div>'
    return out


def header(kicker: str, big: str, sub_html: str) -> str:
    return (f'<div class="hd"><div class="kick">{esc(kicker)}</div><div class="big">{esc(big)}</div>'
            f'<div class="sub">{sub_html}</div></div>')


def page(title: str, body: str) -> str:
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="color-scheme" content="light only"><title>{esc(title)}</title><style>{CSS}</style></head>'
            f'<body><div class="wrap">{body}</div></body></html>')


def health_text(health, now, stale_default: int) -> str:
    problems = []
    for h in health:
        if not h.ok:
            problems.append(f"{h.name} ({h.error})")
        elif h.kind == "feed" and h.newest and (now - h.newest).days >= (h.stale_days or stale_default):
            problems.append(f"{h.name} (nothing new in {(now - h.newest).days} days)")
    ok = sum(1 for h in health if h.ok)
    text = f"Checked {len(health)} sources; {ok} worked."
    if problems:
        text += " Needs a look: " + "; ".join(problems) + "."
    return text


def footer(ctx: Ctx, health, extra: str = "") -> str:
    stale = int((ctx.cfg.get("settings") or {}).get("stale_feed_days", 7))
    ln = ctx.local_now
    return (f'<div class="ft">{esc(health_text(health, ctx.now, stale))}<br>{extra}'
            f'Made {nice_day(ln)}, {nice_time(ln)}. Change artists, websites, sections or charts in <b>config.yaml</b>.</div>')


def fmt_metric(raw: str) -> str:
    digits = re.sub(r"[^\d.]", "", raw or "")
    if not digits:
        return ""
    try:
        n = float(digits)
    except ValueError:
        return esc(raw)
    if n >= 1e6:
        return f"{n / 1e6:.2f}M"
    if n >= 1e4:
        return f"{n / 1e3:.0f}K"
    return f"{n:g}"


def fmt_move(r) -> str:
    if r.status == "new":
        return '<span class="nw">NEW</span>'
    if r.status == "re":
        return '<span class="nw">RE</span>'
    if r.status == "up":
        return f'<span class="up">&#9650;{r.move}</span>'
    if r.status == "down":
        return f'<span class="dn">&#9660;{-r.move}</span>'
    return '<span class="eq">&ndash;</span>'


# --------------------------------------------------------------------------- #
# News email pieces
# --------------------------------------------------------------------------- #
def quick_numbers(ctx: Ctx) -> str:
    want = ["hot100", "bb200", "uk_singles", "uk_albums", "spotify_global"]
    parts = []
    for s in ctx.analysis.snapshot:
        ch, r = s["chart"], s["row"]
        if ch.id in want:
            parts.append((want.index(ch.id), f"<b>{esc(ch.name.replace(' (daily)', ''))} #1:</b> {esc(r.title)} &ndash; {esc(r.artist)}"))
    return "<br>".join(p for _, p in sorted(parts))


def ai_box(ai: dict | None) -> str:
    if not ai:
        return ""
    parts = []
    if ai.get("brief"):
        parts.append('<div class="bt">Today in 60 seconds</div><ul>' +
                     "".join(f"<li>{esc(b)}</li>" for b in ai["brief"]) + "</ul>")
    if ai.get("artist_takeaway"):
        parts.append(f'<div class="bt" style="margin-top:10px">For your rollout</div>'
                     f'<div class="note" style="font-size:14px;color:#16161a">{esc(ai["artist_takeaway"])}</div>')
    return f'<div class="sec" style="padding-top:18px"><div class="box">{"".join(parts)}</div></div>' if parts else ""


def calendar_box(ctx: Ctx, max_entries: int) -> str:
    today = ctx.local_now.date()
    entries = sorted((e for e in ctx.calendar.values() if e.get("date", "") >= today.isoformat()),
                     key=lambda e: (e["date"], e.get("title", "")))
    if not entries or max_entries <= 0:
        return ""
    fridays: dict[str, int] = {}
    for e in entries:
        d = dt.date.fromisoformat(e["date"])
        if d.weekday() == 4:
            fridays[e["date"]] = fridays.get(e["date"], 0) + 1
    busy = sorted(fridays.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    busy_html = ""
    if busy:
        busy_html = ('<div class="note"><b>Busiest Fridays coming up:</b> ' +
                     ", ".join(f"{nice_day(dt.date.fromisoformat(k))} ({v})" for k, v in busy) + "</div>")
    rows, last_day = [], None
    for e in entries[:max_entries]:
        d = dt.date.fromisoformat(e["date"])
        if e["date"] != last_day:
            label = "Today" if d == today else "Tomorrow" if d == today + dt.timedelta(days=1) else nice_day(d)
            rows.append(f'<div class="day">{esc(label)}{" <span>&middot; release Friday</span>" if d.weekday() == 4 else ""}</div>')
            last_day = e["date"]
        who = "".join(chip(a) for a in e.get("artists") or [])
        title = (f'<a href="{esc(e["link"])}">{esc(e["title"])}</a>' if e.get("link") else esc(e["title"]))
        rows.append(f'<div class="ln">{who}{title} <span>{esc(e.get("source", ""))}</span></div>')
    more = len(entries) - max_entries
    tail = f'<div class="more">+ {more} more dates in the full digest</div>' if more > 0 else ""
    return (f'<div class="sec">{section_head("🗓️", "Release calendar", len(entries), sub="Release dates mentioned in the news (kept from earlier digests too). Double-check before planning around them.")}'
            f'{busy_html}{"".join(rows)}{tail}</div>')


def mini_chart_list(title: str, rows, limit: int) -> str:
    if not rows:
        return ""
    lines = "".join(f'<div class="ln">#{r.pos} {fmt_move(r)} <b>{esc(r.title)}</b> <span>{esc(r.artist)}</span></div>'
                    for r in rows[:limit])
    return f'<div class="box2"><div class="bt">{esc(title)}</div>{lines}</div>'


def breakout_list(breakouts, limit: int, title="Chart breakouts") -> str:
    if not breakouts or limit <= 0:
        return ""
    lines = "".join(f'<div class="ln"><b>{esc(b["title"])}</b> <span>&ndash; {esc(b["artist"])}</span><br>'
                    f'<span>{esc(" · ".join(b["evidence"][:4]))}</span></div>' for b in breakouts[:limit])
    return (f'<div class="box2"><div class="bt">{esc(title)}</div>'
            f'<div class="note">Songs outside your superstar list that are new on a chart, jumping fast, or being Shazamed.</div>{lines}</div>')


def superstar_section(sec, ctx: Ctx, per_full: int, per_compact: int, max_artists: int) -> str:
    groups: dict[str, list] = {}
    meta: dict[str, object] = {}
    for st in sec.stories:
        main = next((a for a in st.artists if a.tier == "superstar"), None)
        if not main:
            continue
        groups.setdefault(main.name, []).append(st)
        meta[main.name] = main
    order = sorted(groups, key=lambda n: (-len(groups[n]), -max(s.rank for s in groups[n])))
    note = (ctx.ai or {}).get("section_notes", {}).get(sec.id, "")
    out = [section_head(sec.icon, sec.name, len(sec.stories), note,
                        sub=f"{len(order)} artists in the news")]
    for name in order[:max_artists]:
        sts = groups[name]
        a = meta[name]
        out.append(f'<div class="ah">{esc(name)} <span>{esc(a.group)} &middot; {len(sts)} {"story" if len(sts) == 1 else "stories"}</span></div>')
        out += [story_full(st, ctx.now, hide_artist=name) for st in sts[:per_full]]
        out += [story_line(st) for st in sts[per_full: per_full + per_compact]]
        rest = len(sts) - per_full - per_compact
        if rest > 0:
            out.append(f'<div class="more">+ {rest} more about {esc(name)} in the full digest</div>')
    if len(order) > max_artists:
        tail = ", ".join(f"{esc(n)} ({len(groups[n])})" for n in order[max_artists:])
        out.append(f'<div class="note"><b>Also in the news:</b> {tail}</div>')
    return f'<div class="sec">{"".join(out)}</div>'


def plain_section(sec, ctx: Ctx, full_n: int, compact_n: int, extra_html: str = "") -> str:
    note = (ctx.ai or {}).get("section_notes", {}).get(sec.id, "")
    out = [section_head(sec.icon, sec.name, len(sec.stories), note)]
    out.append(extra_html)
    out += [story_full(st, ctx.now) for st in sec.stories[:full_n]]
    out += [story_line(st) for st in sec.stories[full_n: full_n + compact_n]]
    rest = len(sec.stories) - full_n - compact_n
    if rest > 0:
        out.append(f'<div class="more">+ {rest} more in the full digest</div>')
    return f'<div class="sec">{"".join(out)}</div>'


def chart_by_id(ctx: Ctx, cid: str):
    return next((c for c in ctx.charts if c.id == cid), None)


def news_body(ctx: Ctx, level: dict) -> str:
    full_n, compact_n = level["full"], level["compact"]
    parts = [ai_box(ctx.ai), calendar_box(ctx, level["calendar"])]
    group_titles = {"topic": "The news by topic", "region": "By country", "scene": "Scenes"}
    last_kind = None
    for sec in ctx.sections:
        if not sec.stories and sec.id not in ("rising",):
            continue
        if sec.kind in group_titles and sec.kind != last_kind:
            parts.append(f'<div class="grp">{group_titles[sec.kind]}</div>')
        last_kind = sec.kind
        if sec.id == "superstars":
            parts.append(superstar_section(sec, ctx, level["artist_full"], level["artist_compact"], level["artists"]))
        elif sec.id == "rising":
            extra = breakout_list(ctx.analysis.breakouts, level["breakouts"])
            if sec.stories or extra:
                parts.append(plain_section(sec, ctx, full_n, compact_n, extra))
        elif sec.id == "independent":
            ib = chart_by_id(ctx, "uk_indie_breakers")
            extra = mini_chart_list("UK Indie Singles Breakers (independent acts climbing)", ib.rows if ib else [], level["mini"])
            parts.append(plain_section(sec, ctx, full_n, compact_n, extra))
        elif sec.id == "more":
            parts.append(plain_section(sec, ctx, 0, level["more"]))
        elif sec.id == "biggest":
            parts.append(plain_section(sec, ctx, max(full_n, 6), compact_n))
        else:
            parts.append(plain_section(sec, ctx, full_n, compact_n))
    return "".join(parts)


NEWS_LEVELS = [
    dict(full=6, compact=10, artist_full=3, artist_compact=3, artists=30, calendar=30, breakouts=12, mini=5, more=25),
    dict(full=5, compact=8, artist_full=2, artist_compact=3, artists=25, calendar=24, breakouts=10, mini=5, more=15),
    dict(full=4, compact=6, artist_full=2, artist_compact=2, artists=20, calendar=18, breakouts=8, mini=5, more=10),
    dict(full=3, compact=5, artist_full=1, artist_compact=2, artists=16, calendar=14, breakouts=8, mini=3, more=8),
    dict(full=2, compact=4, artist_full=1, artist_compact=1, artists=12, calendar=10, breakouts=6, mini=3, more=5),
    dict(full=2, compact=2, artist_full=1, artist_compact=0, artists=10, calendar=8, breakouts=5, mini=3, more=0),
]
FULL_LEVEL = dict(full=10_000, compact=0, artist_full=10_000, artist_compact=0, artists=10_000,
                  calendar=10_000, breakouts=40, mini=10, more=10_000)


def news_header(ctx: Ctx, kicker: str) -> str:
    ln = ctx.local_now
    since = ctx.since.astimezone(ctx.tz)
    total = len(ctx.stories)
    counts = [f"{s.name.split(' (')[0].split(',')[0]} {len(s.stories)}" for s in ctx.sections
              if s.stories and s.kind in ("top", "who")]
    sub = (f"{total} stories from {ctx.total_items} articles since {nice_day(since)}, {nice_time(since)}"
           f"<br>{esc(' · '.join(counts))}")
    qn = quick_numbers(ctx)
    if qn:
        sub += f'<br><br>{qn}'
    return header(kicker, f"{ln:%A}, {ln.day} {ln:%B}", sub)


def news_subject(ctx: Ctx) -> str:
    ln = ctx.local_now
    sup = next((s for s in ctx.sections if s.id == "superstars"), None)
    names = []
    if sup:
        counts: dict[str, int] = {}
        for st in sup.stories:
            main = next((a for a in st.artists if a.tier == "superstar"), None)
            if main:
                counts[main.name] = counts.get(main.name, 0) + 1
        names = [n for n, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:3]]
    total = len(ctx.stories)
    subj = f"{ctx.title} · {nice_day(ln)}"
    if names:
        subj += " · " + ", ".join(names)
    return subj + (f" · {total} stories" if total else " · quiet day")


def fit(render_fn, levels, max_bytes):
    html = ""
    for lv in levels:
        html = render_fn(lv)
        if len(html.encode("utf-8")) <= max_bytes:
            return html, lv
    return html, levels[-1]


def news_email(ctx: Ctx, include_charts: bool = False):
    max_bytes = int((ctx.cfg.get("email") or {}).get("max_email_kb", 95)) * 1024
    hlth = ctx.health + (ctx.chart_health if include_charts else [])

    def build(lv):
        body = news_header(ctx, ctx.title) + news_body(ctx, lv)
        if include_charts:
            body += f'<div class="grp" style="padding-top:40px">Charts &amp; stats</div>' + charts_body(ctx, CHART_LEVELS[min(2, NEWS_LEVELS.index(lv) // 2)])
        extra = "Every story is in the attached full digest.<br>" if (ctx.cfg.get("email") or {}).get("attach_full_digest", True) else ""
        return page(ctx.title, body + footer(ctx, hlth, extra))

    html, _ = fit(build, NEWS_LEVELS, max_bytes)
    return news_subject(ctx), html, news_text(ctx)


def news_text(ctx: Ctx) -> str:
    ln = ctx.local_now
    out = [f"{ctx.title.upper()} - {ln:%A} {ln.day} {ln:%B}", ""]
    if ctx.ai and ctx.ai.get("brief"):
        out += ["TODAY IN 60 SECONDS"] + [f"- {b}" for b in ctx.ai["brief"]] + [""]
    for sec in ctx.sections:
        if not sec.stories:
            continue
        out.append(f"{sec.name.upper()} ({len(sec.stories)})")
        for st in sec.stories[:5]:
            out.append(f"- {st.lead.title} ({st.lead.source})\n  {st.lead.link}")
        out.append("")
    out.append("The HTML version of this email has everything laid out properly.")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Charts email pieces
# --------------------------------------------------------------------------- #
def chart_table(ch, pinned_matchers, top: int) -> str:
    rows = []
    is_official = any(r.peak or r.weeks for r in ch.rows[:3]) and not ch.metric_name
    for r in ch.rows[:top]:
        hl = ' class="hl"' if any(m.search(r.artist) for m in pinned_matchers) else ""
        if ch.metric_name:
            right = fmt_metric(r.metric)
        else:
            bits = []
            if r.peak:
                bits.append(f"pk {esc(r.peak)}")
            if r.weeks:
                bits.append(f"{esc(r.weeks)} {ch.span_unit}")
            right = " · ".join(bits)
        rows.append(f'<tr{hl}><td class="p">{r.pos}</td><td class="mv">{fmt_move(r)}</td>'
                    f'<td><b>{esc(r.title)}</b><br><span class="a">{esc(r.artist)}</span></td>'
                    f'<td class="r">{right}</td></tr>')
    new = [r for r in ch.rows[top:100] if r.status == "new"][:6]
    notes = ""
    if new:
        notes = ('<div class="note"><b>Also new this time:</b> ' +
                 ", ".join(f"{esc(r.title)} &ndash; {esc(r.artist)} (#{r.pos})" for r in new) + "</div>")
    metric = {"streams": "daily streams", "pts": "points", "aud": "audience (m)"}.get(ch.metric_name, ch.metric_name)
    when = f" &middot; {nice_day(ch.date)}" if ch.date else ""
    right_head = esc(metric) if ch.metric_name else ("peak · weeks" if is_official else "")
    return (f'<div class="chart"><a class="cn" href="{esc(ch.url)}">{esc(ch.name)}</a><span class="cd">{when}</span>'
            f'<table class="ch"><tr><th></th><th></th><th></th><th class="r">{right_head}</th></tr>{"".join(rows)}</table>{notes}</div>')


def chart_compact(ch) -> str:
    r = ch.rows[0]
    when = nice_day(ch.date) if ch.date else "last week"
    weeks = f" ({r.weeks} {ch.span_unit})" if r.weeks else ""
    return (f'<div class="ln"><a href="{esc(ch.url)}"><b>{esc(ch.name)}</b></a> <span>&middot; no new chart since {esc(when)}. '
            f'#1 {esc(r.title)} &ndash; {esc(r.artist)}{esc(weeks)}</span></div>')


def snapshot_box(ctx: Ctx) -> str:
    if not ctx.analysis.snapshot:
        return ""
    rows = "".join(
        f'<tr><td><a class="cn" style="font-size:13px" href="{esc(s["chart"].url)}">{esc(s["chart"].name)}</a></td>'
        f'<td><b>{esc(s["row"].title)}</b><br><span class="a">{esc(s["row"].artist)}</span></td>'
        f'<td class="r">{fmt_move(s["row"])}{(" " + esc(s["row"].weeks) + " " + s["chart"].span_unit) if s["row"].weeks else ""}</td></tr>'
        for s in ctx.analysis.snapshot)
    return f'<div class="sec">{section_head("🥇", "Number ones right now", len(ctx.analysis.snapshot))}<table class="ch">{rows}</table></div>'


def scoreboard_box(ctx: Ctx, limit: int) -> str:
    from charts import short_chart_name
    board = [e for e in ctx.analysis.scoreboard if e["artist"].tier in ("superstar", "pinned", "rising")][:limit]
    if not board:
        return ""
    rows = "".join(
        f'<tr><td><b>{esc(e["artist"].name)}</b><br><span class="a">{e["entries"]} {"entry" if e["entries"] == 1 else "entries"}</span></td><td class="a">' +
        " &middot; ".join(f"{esc(short_chart_name(ch.name))} <b>#{best}</b>" + (f" ({n})" if n > 1 else "")
                          for ch, best, n in sorted(e["charts"], key=lambda x: x[1])) +
        "</td></tr>" for e in board)
    return (f'<div class="sec">{section_head("⭐", "Who is where", len(board), sub="Best position for each followed artist on every chart (number of songs in brackets).")}'
            f'<table class="ch">{rows}</table></div>')


def sales_box(ctx: Ctx, limit: int) -> str:
    nums = ctx.numbers[:limit]
    stories = [st for st in ctx.stories if "sales" in st.tags or any("hits daily" in s.lower() for s in st.sources)]
    stories.sort(key=lambda st: -(st.newest.timestamp() if st.newest else 0))
    if not nums and not stories:
        return ""
    out = [section_head("💿", "Sales, units & forecasts", "", sub="Numbers quoted in today's news, plus HITS Daily Double's chart forecasts.")]
    if nums:
        out.append("".join(f'<div class="ln"><b>{esc(n["label"])}</b> &middot; <a href="{esc(n["story"].lead.link)}">{esc(n["story"].lead.title)}</a> <span>{esc(n["story"].lead.source)}</span></div>' for n in nums))
    if stories:
        out.append('<div class="box2"><div class="bt">Forecasts &amp; sales headlines</div>' +
                   "".join(story_line(st) for st in stories[:limit]) + "</div>")
    return f'<div class="sec">{"".join(out)}</div>'


BILLBOARD_CHART_RE = re.compile(r"hot 100|billboard 200|global 200|global excl|artist 100|emerging artists|no\. 1|chart", re.I)


def billboard_box(ctx: Ctx, limit: int) -> str:
    sts = [st for st in ctx.stories if "billboard" in st.tags and BILLBOARD_CHART_RE.search(st.lead.title)]
    sts.sort(key=lambda st: -(st.newest.timestamp() if st.newest else 0))
    if not sts:
        return ""
    return (f'<div class="sec">{section_head("📰", "Billboard chart headlines", len(sts), sub="Billboard blocks automated readers, so the Global 200, Global Excl. US, Artist 100 and Emerging Artists come through as their headlines.")}'
            + "".join(story_full(st, ctx.now) for st in sts[:limit]) + "</div>")


CHART_LEVELS = [dict(scale=1.0, board=25, breakouts=20, sales=10, bb=8),
                dict(scale=0.75, board=20, breakouts=15, sales=8, bb=6),
                dict(scale=0.5, board=15, breakouts=10, sales=6, bb=5)]


def charts_body(ctx: Ctx, lv: dict, force_full: bool = False) -> str:
    pinned = [a.matcher for a in ctx.pinned_artists]
    parts = [snapshot_box(ctx), scoreboard_box(ctx, lv["board"])]
    if ctx.analysis.breakouts:
        parts.append(f'<div class="sec">{section_head("🚀", "Breakouts", len(ctx.analysis.breakouts))}'
                     f'{breakout_list(ctx.analysis.breakouts, lv["breakouts"], "Rising on the charts")}</div>')
    parts += [sales_box(ctx, lv["sales"]), billboard_box(ctx, lv["bb"])]
    groups: dict[str, list] = {}
    for ch in ctx.charts:
        groups.setdefault(ch.group, []).append(ch)
    for g, chs in groups.items():
        inner = []
        for ch in chs:
            if ch.weekly and not ch.fresh and not force_full:
                inner.append(chart_compact(ch))
            else:
                inner.append(chart_table(ch, pinned, max(5, int(round(ch.top * lv["scale"])))))
        parts.append(f'<div class="sec">{section_head("📊", g, len(chs))}{"".join(inner)}</div>')
    return "".join(parts)


def charts_email(ctx: Ctx):
    max_bytes = int((ctx.cfg.get("email") or {}).get("max_email_kb", 95)) * 1024
    ln = ctx.local_now

    def build(lv):
        fresh = [c.name for c in ctx.charts if c.weekly and c.fresh]
        sub = f"{len(ctx.charts)} charts"
        if fresh:
            sub += f" &middot; new this week: {esc(', '.join(fresh))}"
        body = header(f"{ctx.title} · Charts & stats", f"{ln:%A}, {ln.day} {ln:%B}", sub) + charts_body(ctx, lv)
        return page(f"{ctx.title} · Charts & stats", body + footer(ctx, ctx.chart_health))

    html, _ = fit(build, CHART_LEVELS, max_bytes)
    return charts_subject(ctx), html, charts_text(ctx)


def charts_subject(ctx: Ctx) -> str:
    ln = ctx.local_now
    bits = []
    for cid, label in (("hot100", "Hot 100"), ("uk_singles", "UK"), ("spotify_global", "Spotify")):
        ch = chart_by_id(ctx, cid)
        if ch and ch.rows:
            bits.append(f"{label} #1 {ch.rows[0].title}")
    return f"Charts & Stats · {nice_day(ln)}" + (" · " + " · ".join(bits[:2]) if bits else "")


def charts_text(ctx: Ctx) -> str:
    out = [f"CHARTS & STATS - {nice_day(ctx.local_now)}", ""]
    for ch in ctx.charts:
        out.append(f"{ch.name.upper()}" + (f" ({nice_day(ch.date)})" if ch.date else ""))
        out += [f"{r.pos:>3}. {r.title} - {r.artist}" for r in ch.rows[: min(ch.top, 10)]]
        out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Full digest (attachment / saved copy): everything, no trimming
# --------------------------------------------------------------------------- #
def full_digest(ctx: Ctx) -> str:
    body = news_header(ctx, f"{ctx.title} · full digest") + news_body(ctx, FULL_LEVEL)
    body += '<div class="grp" style="padding-top:40px">Charts &amp; stats</div>' + charts_body(ctx, dict(scale=1.0, board=60, breakouts=40, sales=20, bb=20), force_full=True)
    return page(f"{ctx.title} · full digest", body + footer(ctx, ctx.health + ctx.chart_health))
