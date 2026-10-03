"""News: collect stories from feeds and Google News, merge duplicates, and decide where each one goes."""
from __future__ import annotations

import datetime as dt
import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from urllib.parse import quote_plus

import feedparser

from util import (UTC, NameMatcher, canonical_url, clean_summary, clean_title, describe_error, display_name,
                  http_get, keyword_pattern, norm_title, short_hash, title_tokens)

GOOGLE_EDITIONS = {
    "us": "hl=en-US&gl=US&ceid=US:en",
    "uk": "hl=en-GB&gl=GB&ceid=GB:en",
    "in": "hl=en-IN&gl=IN&ceid=IN:en",
    "ca": "hl=en-CA&gl=CA&ceid=CA:en",
    "au": "hl=en-AU&gl=AU&ceid=AU:en",
}
TAG_TO_TOPIC = {"charts": "charts", "sales": "charts", "industry": "industry"}


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class Item:
    title: str
    link: str
    source: str
    published: dt.datetime | None
    summary: str = ""
    via_search: bool = False
    tags: frozenset = frozenset()
    origin: str = ""          # which feed/search it came from

    @property
    def ids(self) -> list[str]:
        return ["u:" + short_hash(canonical_url(self.link)), "t:" + short_hash(norm_title(self.title))]


@dataclass
class Story:
    items: list[Item]
    tokens: set
    norm: str
    section: str = ""
    artists: list = field(default_factory=list)      # Artist objects named in the headlines, in order
    chips: list[str] = field(default_factory=list)   # small labels: country flags, scenes, topic
    rank: float = 0.0

    @property
    def lead(self) -> Item:
        return self.items[0]

    @property
    def sources(self) -> list[str]:
        out: list[str] = []
        for it in self.items:
            if it.source not in out:
                out.append(it.source)
        return out

    @property
    def newest(self) -> dt.datetime | None:
        times = [i.published for i in self.items if i.published]
        return max(times) if times else None

    @property
    def tags(self) -> set:
        out: set = set()
        for i in self.items:
            out |= set(i.tags)
        return out

    def text(self) -> tuple[str, str]:
        titles = " | ".join(i.title for i in self.items)
        body = " ".join(i.summary for i in self.items if i.summary)
        return titles, body


@dataclass
class SourceHealth:
    name: str
    ok: bool
    kind: str = "feed"
    total: int = 0
    fresh: int = 0
    newest: dt.datetime | None = None
    error: str = ""
    stale_days: int | None = None


@dataclass
class Artist:
    name: str
    group: str
    tier: str            # pinned | superstar | rising
    raw: str
    matcher: NameMatcher


# --------------------------------------------------------------------------- #
# Artists
# --------------------------------------------------------------------------- #
def build_artists(cfg: dict) -> list[Artist]:
    a = cfg.get("artists") or {}
    aka = {display_name(k): list(v or []) for k, v in (a.get("also_known_as") or {}).items()}
    out: list[Artist] = []
    seen: set[str] = set()

    def add(raw, group, tier):
        name = display_name(raw)
        if not name or name.lower() in seen:
            return
        seen.add(name.lower())
        out.append(Artist(name, group, tier, str(raw), NameMatcher([str(raw), *aka.get(name, [])])))

    for raw in a.get("pinned") or []:
        add(raw, "Pinned", "pinned")
    for group, names in (a.get("superstars") or {}).items():
        for raw in names or []:
            add(raw, group, "superstar")
    for raw in a.get("rising") or []:
        add(raw, "Rising", "rising")
    return out


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #
def google_url(query: str, days: int, edition: str = "us") -> str:
    params = GOOGLE_EDITIONS.get(str(edition).lower(), GOOGLE_EDITIONS["us"])
    return f"https://news.google.com/rss/search?q={quote_plus(f'{query} when:{days}d')}&{params}"


def build_jobs(cfg: dict, artists: list[Artist], days: int) -> list[dict]:
    jobs: list[dict] = []
    for f in cfg.get("feeds") or []:
        if f.get("enabled", True):
            jobs.append({"kind": "feed", "name": f["name"], "url": f["url"], "limit": f.get("limit"),
                         "tags": frozenset(f.get("tags") or []), "stale_days": f.get("stale_days")})
    gn = cfg.get("google_news") or {}
    if not gn.get("enabled", True):
        return jobs
    default_limit = int(gn.get("max_per_search", 25))
    for s in gn.get("searches") or []:
        if s.get("enabled", True):
            jobs.append({"kind": "search", "name": s["name"], "url": google_url(s["query"], days, s.get("edition", "us")),
                         "limit": s.get("limit", default_limit), "tags": frozenset(s.get("tags") or [])})
    # Artist searches, a batch of names per search. Exact-case names (=TWICE) are skipped
    # because Google ignores capitals and they'd match everyday words.
    extra = gn.get("artist_query_extra", "")
    per = max(1, int(gn.get("artists_per_search", 10)))
    limit = int(gn.get("max_per_artist_search", 30))
    want_super = (cfg.get("artists") or {}).get("search_superstars", True)
    groups: dict[str, list[str]] = {}
    for a in artists:
        if a.raw.startswith("=") or (a.tier == "superstar" and not want_super):
            continue
        groups.setdefault(a.tier if a.tier != "superstar" else a.group, []).append(a.name)
    for group, names in groups.items():
        for i in range(0, len(names), per):
            chunk = names[i:i + per]
            q = "(" + " OR ".join(f'"{n}"' for n in chunk) + ")" + (f" {extra}" if extra else "")
            label = f"{group.title() if group in ('pinned', 'rising') else group} artists {i // per + 1}"
            jobs.append({"kind": "search", "name": label, "url": google_url(q, days), "limit": limit,
                         "tags": frozenset({"artist_search"})})
    return jobs


def parse_feed(content: bytes, job: dict) -> list[Item]:
    fp = feedparser.parse(content)
    if not fp.entries:
        if fp.bozo:
            raise ValueError("not a readable RSS feed")
        return []
    via_search = job["kind"] == "search"
    items = []
    for e in fp.entries:
        title = clean_title(e.get("title", ""))
        link = (e.get("link") or "").strip()
        if not title or not link:
            continue
        source, summary = job["name"], ""
        if via_search:
            src = e.get("source") or {}
            src_title = (src.get("title") if hasattr(src, "get") else None) or ""
            src_title = src_title.strip()
            if src_title:
                source = src_title
                if title.endswith(" - " + source):
                    title = title[: -(len(source) + 3)].strip()
            elif " - " in title:
                title, source = (p.strip() for p in title.rsplit(" - ", 1))
        else:
            summary = clean_summary(e.get("summary") or e.get("description") or "", title)
        published = None
        for key in ("published_parsed", "updated_parsed"):
            if e.get(key):
                try:
                    published = dt.datetime(*e[key][:6], tzinfo=UTC)
                except Exception:
                    published = None
                break
        items.append(Item(title, link, source, published, summary, via_search, job.get("tags", frozenset()), job["name"]))
    return items


class Filters:
    def __init__(self, cfg: dict):
        gn = cfg.get("google_news") or {}
        self.blocked = [s.lower() for s in gn.get("blocked_sources") or []]
        self.title_res = [re.compile(p, re.I) for p in gn.get("blocked_title_patterns") or []]

    def ok(self, it: Item) -> bool:
        src = it.source.lower()
        if it.via_search and any(b == src or (len(b) > 4 and b in src) for b in self.blocked):
            return False
        return not any(r.search(it.title) for r in self.title_res)


def fetch_job(job: dict, cutoff: dt.datetime, filters: Filters) -> tuple[list[Item], SourceHealth]:
    health = SourceHealth(job["name"], ok=False, kind=job["kind"], stale_days=job.get("stale_days"))
    try:
        resp = http_get(job["url"])
        items = parse_feed(resp.content, job)
    except Exception as exc:
        health.error = describe_error(exc)
        return [], health
    health.ok = True
    health.total = len(items)
    dated = [i.published for i in items if i.published]
    health.newest = max(dated) if dated else None
    fresh = [i for i in items if (i.published is None or i.published >= cutoff) and filters.ok(i)]
    if job.get("limit"):
        fresh = fresh[: int(job["limit"])]
    health.fresh = len(fresh)
    return fresh, health


def collect(cfg: dict, artists: list[Artist], cutoff: dt.datetime, days: int, log=print) -> tuple[list[Item], list[SourceHealth]]:
    jobs = build_jobs(cfg, artists, days)
    filters = Filters(cfg)
    feeds = [j for j in jobs if j["kind"] == "feed"]
    searches = [j for j in jobs if j["kind"] == "search"]
    log(f"Checking {len(feeds)} news feeds and {len(searches)} Google News searches...")
    with ThreadPoolExecutor(max_workers=10) as fpool, ThreadPoolExecutor(max_workers=2) as spool:
        futures = [fpool.submit(fetch_job, j, cutoff, filters) for j in feeds] + \
                  [spool.submit(fetch_job, j, cutoff, filters) for j in searches]
        results = [f.result() for f in futures]
    items: list[Item] = []
    health: list[SourceHealth] = []
    for got, h in results:
        items.extend(got)
        health.append(h)
        status = f"{h.fresh} new" if h.ok else f"FAILED ({h.error})"
        log(f"  {h.name[:44]:<45} {status}")
    return items, health


# --------------------------------------------------------------------------- #
# Merging duplicate coverage into stories
# --------------------------------------------------------------------------- #
GENERIC = set(
    """share shares shared single singles album albums announce announces announced watch listen video videos
    music song songs tour tours debut debuts release releases released drop drops dropped live performs
    performance official track tracks stream streaming record records chart charts year week tonight today
    review reviews interview new best""".split()
)


def same_story(a_tokens: set, a_norm: str, b_tokens: set, b_norm: str) -> bool:
    shared = a_tokens & b_tokens
    if len(shared - GENERIC) < 2:
        return False
    if len(shared) >= 3 and len(shared) / max(1, len(a_tokens | b_tokens)) >= 0.45:
        return True
    return len(shared) >= 3 and SequenceMatcher(None, a_norm, b_norm).ratio() >= 0.75


def group_stories(items: list[Item]) -> list[Story]:
    unique: dict[str, Item] = {}
    for it in items:
        key = canonical_url(it.link)
        if key not in unique or (unique[key].via_search and not it.via_search):
            unique[key] = it
    ordered = sorted(unique.values(), key=lambda i: (i.via_search, -(i.published.timestamp() if i.published else 0)))
    stories: list[Story] = []
    index: dict[str, list[Story]] = {}   # token -> stories containing it (keeps this fast with ~1000 items)
    for it in ordered:
        toks, norm = title_tokens(it.title), norm_title(it.title)
        candidates: list[Story] = []
        seen_ids: set[int] = set()
        for t in toks - GENERIC:
            for st in index.get(t, []):
                if id(st) not in seen_ids:
                    seen_ids.add(id(st))
                    candidates.append(st)
        for st in candidates:
            if same_story(toks, norm, st.tokens, st.norm):
                st.items.append(it)
                break
        else:
            st = Story(items=[it], tokens=toks, norm=norm)
            stories.append(st)
            for t in toks:
                index.setdefault(t, []).append(st)
    for st in stories:
        st.items.sort(key=lambda i: (i.via_search, not i.summary, -(i.published.timestamp() if i.published else 0)))
    return stories


# --------------------------------------------------------------------------- #
# Ranking and placing stories into sections
# --------------------------------------------------------------------------- #
def _patterns(words) -> list[re.Pattern]:
    return [keyword_pattern(w) for w in words or []]


def rank_stories(stories: list[Story], cfg: dict, now: dt.datetime) -> None:
    top = [s.lower() for s in (cfg.get("settings") or {}).get("top_outlets") or []]
    for st in stories:
        r = 3.0 * len(st.sources)
        if any(any(t == s.lower() or t in s.lower() for t in top) for s in st.sources):
            r += 2
        if st.newest and (now - st.newest).total_seconds() < 12 * 3600:
            r += 1
        if not st.lead.via_search:
            r += 0.5
        if st.lead.summary:
            r += 0.3
        st.rank = r


def story_sort_key(st: Story):
    return (-st.rank, -(st.newest.timestamp() if st.newest else 0))


@dataclass
class Section:
    id: str
    name: str
    icon: str
    kind: str                 # top | who | topic | region | scene | more
    stories: list[Story] = field(default_factory=list)
    note: str = ""


def section_catalog(cfg: dict) -> list[Section]:
    out = [Section("biggest", "Biggest stories", "🔥", "top"),
           Section("pinned", "Pinned artists", "📌", "who"),
           Section("superstars", "Superstars", "⭐", "who"),
           Section("rising", "Rising & breakthrough", "🚀", "who"),
           Section("independent", "Independent & DIY artists", "🛠️", "who")]
    for t in cfg.get("topics") or []:
        out.append(Section(t["id"], t["name"], t.get("icon", ""), "topic"))
    for r in cfg.get("regions") or []:
        if r.get("enabled", True):
            out.append(Section("region:" + r["id"], r["name"], r.get("icon", ""), "region"))
    for s in cfg.get("scenes") or []:
        if s.get("enabled", True):
            out.append(Section("scene:" + s["id"], s["name"], s.get("icon", ""), "scene"))
    out.append(Section("more", "More headlines", "🗞️", "more"))
    return out


def place_stories(stories: list[Story], cfg: dict, artists: list[Artist], breakout_names: list[tuple[str, NameMatcher]]) -> list[Section]:
    settings = cfg.get("settings") or {}
    big_min = int(settings.get("biggest_story_min_outlets", 3))
    topics = [(t, _patterns(t.get("keywords")), bool(t.get("strong"))) for t in cfg.get("topics") or []]
    regions = [(r, _patterns(r.get("keywords"))) for r in cfg.get("regions") or [] if r.get("enabled", True)]
    scenes = [(s, _patterns(s.get("keywords"))) for s in cfg.get("scenes") or [] if s.get("enabled", True)]
    rising_kw = _patterns(cfg.get("rising_keywords"))
    indie_kw = _patterns(cfg.get("independent_keywords"))
    sections = section_catalog(cfg)
    by_id = {s.id: s for s in sections}

    for st in stories:
        titles, body = st.text()
        tags = st.tags

        def score(patterns):
            return sum(2 for p in patterns if p.search(titles)) + sum(1 for p in patterns if body and p.search(body))

        found = []
        for a in artists:
            m = a.matcher.search(titles)
            if m:
                found.append((m.start(), a))
        st.artists = [a for _, a in sorted(found, key=lambda x: x[0])]
        tiers = {a.tier for a in st.artists}
        breakout_hit = any(m.search(titles) for _, m in breakout_names)

        topic_scores = {}
        for t, pats, strong in topics:
            s = score(pats) + sum(2 for tag in tags if TAG_TO_TOPIC.get(tag) == t["id"])
            topic_scores[t["id"]] = (s, strong)
        scene_scores = {s["id"]: score(p) + (2 if s["id"] in tags else 0) for s, p in scenes}
        region_scores = {r["id"]: score(p) + (1 if r["id"] in tags else 0) for r, p in regions}
        region_in_title = {r["id"]: any(x.search(titles) for x in p) for r, p in regions}
        rising_score = score(rising_kw) + (1 if "rising" in tags else 0) + (3 if ("rising" in tiers or breakout_hit) else 0)
        indie_score = score(indie_kw) + (2 if "independent" in tags else 0)

        def best(d: dict, strong_only=None):
            items = [(k, v[0] if isinstance(v, tuple) else v) for k, v in d.items()
                     if strong_only is None or (isinstance(v, tuple) and v[1] == strong_only)]
            if not items:
                return None, 0
            k, v = max(items, key=lambda kv: kv[1])
            return k, v

        strong_id, strong_s = best(topic_scores, True)
        weak_id, weak_s = best(topic_scores, False)
        any_topic_id, any_topic_s = best(topic_scores)
        scene_id, scene_s = best(scene_scores)
        region_id, region_s = best(region_scores)

        if "pinned" in tiers:
            sec = "pinned"
        elif len(st.sources) >= big_min:
            sec = "biggest"
        elif "superstar" in tiers:
            sec = "superstars"
        elif rising_score >= 2:
            sec = "rising"
        elif indie_score >= 2:
            sec = "independent"
        elif strong_s >= 2:
            sec = strong_id
        elif scene_s >= 2:
            sec = "scene:" + scene_id
        elif region_s >= 2 and region_in_title.get(region_id):
            sec = "region:" + region_id
        elif weak_s >= 1:
            sec = weak_id
        else:
            sec = "more"
        st.section = sec

        # small labels so you can see the other angles at a glance
        chips: list[str] = []
        for r, _ in regions:
            if region_scores[r["id"]] >= 2 and sec != "region:" + r["id"]:
                chips.append(r.get("icon") or r["name"])
        if scene_s >= 2 and sec != "scene:" + scene_id:
            chips.append(next(s["name"] for s, _ in scenes if s["id"] == scene_id))
        if sec in ("biggest", "pinned", "superstars", "rising", "independent") or sec.startswith(("scene:", "region:")):
            if any_topic_s >= 2:
                chips.append(next(t.get("short", t["name"]) for t, _, _ in topics if t["id"] == any_topic_id))
        if sec not in ("rising",) and (rising_score >= 2 and "superstar" not in tiers):
            chips.append("Rising")
        if sec != "independent" and indie_score >= 2:
            chips.append("Indie")
        st.chips = chips
        by_id.get(sec, by_id["more"]).stories.append(st)

    for s in sections:
        s.stories.sort(key=story_sort_key)
    return sections


# --------------------------------------------------------------------------- #
# Release calendar: dates mentioned in the news
# --------------------------------------------------------------------------- #
_MON = r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_VERB = r"(?:out|arrives?|arriving|due(?:\s+out)?|drops?|dropping|lands?|landing|releas(?:es|ed|ing)?|coming|available|hits?\s+shelves|set\s+for\s+release|premieres?)"
DATE_RE = re.compile(_VERB + r"\s+(?:on\s+)?(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s+)?" + _MON + r"\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?\b", re.I)
PAREN_RE = re.compile(r"\(\s*(?:out\s+)?" + _MON + r"\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s*20\d\d)?\s*(?:via|on|\))", re.I)
REL_RE = re.compile(_VERB + r"\s+(?P<rel>this\s+friday|next\s+friday|friday|tonight|tomorrow)\b", re.I)
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _resolve(mon: str, day: int, today: dt.date) -> dt.date | None:
    try:
        d = dt.date(today.year, MONTHS[mon[:3].lower()], day)
    except (ValueError, KeyError):
        return None
    if d < today - dt.timedelta(days=3):
        if (today - d).days > 60:
            try:
                d = d.replace(year=d.year + 1)
            except ValueError:
                return None
        else:
            return None
    return d


def _relative(rel: str, base: dt.date) -> dt.date:
    rel = rel.lower()
    if rel == "tonight":
        return base
    if rel == "tomorrow":
        return base + dt.timedelta(days=1)
    ahead = (4 - base.weekday()) % 7          # 4 = Friday
    d = base + dt.timedelta(days=ahead)
    return d + dt.timedelta(days=7) if rel.startswith("next") else d


def parse_loose_date(text: str, today: dt.date) -> dt.date | None:
    """'Oct 17', 'October 17', '17 October', '2026-10-17' -> a date (or None)."""
    text = (text or "").strip()
    m = re.search(r"(20\d\d)-(\d\d)-(\d\d)", text)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(_MON + r"\.?\s+(?P<day>\d{1,2})", text, re.I) or re.search(r"(?P<day>\d{1,2})\s+" + _MON, text, re.I)
    if m:
        return _resolve(m.group("mon"), int(m.group("day")), today)
    m = re.search(r"\b(this friday|next friday|friday|tomorrow|tonight|today)\b", text, re.I)
    if m:
        rel = m.group(1).lower()
        return today if rel == "today" else _relative(rel, today)
    return None


def extract_release_dates(stories: list[Story], today: dt.date, days_ahead: int, tz) -> list[dict]:
    found = []
    limit = today + dt.timedelta(days=days_ahead)
    for st in stories:
        hits: set[dt.date] = set()
        for it in st.items:
            text = f"{it.title}. {it.summary}"
            base = it.published.astimezone(tz).date() if it.published else today
            for m in DATE_RE.finditer(text):
                d = _resolve(m.group("mon"), int(m.group("day")), today)
                if d:
                    hits.add(d)
            for m in PAREN_RE.finditer(text):
                d = _resolve(m.group("mon"), int(m.group("day")), today)
                if d:
                    hits.add(d)
            for m in REL_RE.finditer(text):
                hits.add(_relative(m.group("rel"), base))
        for d in hits:
            if today - dt.timedelta(days=1) <= d <= limit:
                found.append({"date": d.isoformat(), "title": st.lead.title, "link": st.lead.link,
                              "source": st.lead.source, "artists": [a.name for a in st.artists][:3]})
    return found


def merge_calendar(old: dict, new: list[dict], today: dt.date, stamp: str) -> dict:
    cal = {k: v for k, v in (old or {}).items() if v.get("date", "") >= (today - dt.timedelta(days=1)).isoformat()}
    for e in new:
        who = ",".join(sorted(e["artists"])) or short_hash(norm_title(e["title"]))
        key = f"{e['date']}|{who}"
        if key not in cal:
            cal[key] = dict(e, first_seen=stamp)
    return cal


# --------------------------------------------------------------------------- #
# Numbers in the news (units, streams, sales)
# --------------------------------------------------------------------------- #
_NUM = r"(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?P<mult>million|billion|thousand|bn|m|k)?"
NUMBER_RES = [
    ("units", re.compile(_NUM + r"\s+(?:equivalent\s+album\s+units|album[- ]equivalent\s+units|(?:album\s+)?units)\b", re.I)),
    ("streams", re.compile(_NUM + r"\s+(?:official\s+|on-demand\s+|global\s+|u\.s\.\s+|first-day\s+|first-week\s+)?(?:audio\s+|video\s+)?streams\b", re.I)),
    ("sales", re.compile(_NUM + r"\s+(?:copies|chart\s+sales|pure\s+(?:album\s+)?sales|vinyl\s+(?:copies|sales)|tickets\s+sold|in\s+sales)\b", re.I)),
]


def _to_number(num: str, mult: str | None) -> float:
    n = float(num.replace(",", ""))
    mult = (mult or "").lower()
    return n * {"million": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "thousand": 1e3, "k": 1e3}.get(mult, 1)


def extract_numbers(stories: list[Story]) -> list[dict]:
    out, seen = [], set()
    for st in stories:
        for it in st.items[:4]:
            text = f"{it.title}. {it.summary}"
            for kind, rx in NUMBER_RES:
                for m in rx.finditer(text):
                    value = _to_number(m.group("num"), m.group("mult"))
                    if value < 1000 or id(st) in seen:
                        continue
                    seen.add(id(st))
                    out.append({"kind": kind, "value": value, "label": m.group(0).strip(), "story": st})
    out.sort(key=lambda x: -x["value"])
    return out
