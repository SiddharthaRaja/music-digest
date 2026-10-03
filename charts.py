"""Charts: read chart pages (UK Official Charts, kworb.net) and work out the stats."""
from __future__ import annotations

import datetime as dt
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from util import NameMatcher, describe_error, http_get, norm_title

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}


@dataclass
class Row:
    pos: int
    title: str
    artist: str
    status: str = ""        # new | re | up | down | same | ""
    move: int | None = None  # places moved (positive = up)
    last: int | None = None
    peak: str = ""
    weeks: str = ""
    metric: str = ""         # streams / points / audience, as shown on the source


@dataclass
class Chart:
    id: str
    name: str
    group: str
    url: str
    kind: str = "songs"
    weekly: bool = False
    top: int = 10
    rows: list[Row] = field(default_factory=list)
    date: dt.date | None = None
    metric_name: str = ""
    span_unit: str = "wk"     # "wk" or "days" (how long a song has been on the chart)
    fresh: bool = True       # False when a weekly chart hasn't changed since the last digest


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #
def smart_title(text: str) -> str:
    """Official Charts writes everything in CAPITALS; make it readable without mangling names."""
    text = (text or "").strip()
    if not text or not text.isupper():
        return text

    def fix(m):
        w = m.group(0)
        if len(w) <= 3 and w not in SMALL_WORDS:   # keep BTS, DJ, KEO, IVE as they are
            return w
        return w[0] + w[1:].lower()

    return " ".join(w if any(ch.isdigit() for ch in w) else re.sub(r"[A-ZÀ-Ý][A-ZÀ-Ý'’]*", fix, w)
                    for w in text.split(" "))


SMALL_WORDS = {"THE", "AND", "OF", "A", "AN", "IN", "ON", "TO", "MY", "ME", "YOU", "FOR", "IT", "IS", "BE", "DO",
               "GO", "NO", "SO", "UP", "WE", "US", "ALL", "OUT", "BUT", "NOT", "GET", "GOT", "ONE", "TWO", "HER",
               "HIM", "HIS", "SHE", "WAY", "DAY", "NEW", "OLD", "BAD", "BIG", "RED", "HOT", "LET", "OFF", "WHO",
               "AT", "AS", "OR", "BY", "IF", "OH", "YOUR", "I'M", "LOVE", "WITH", "FROM", "NOW", "HOW", "WHY",
               "TOO", "CAN", "SAY", "SEE", "WAR", "SKY", "SUN", "CRY", "DIE", "LIE", "YES", "HEY", "RUN", "FUN", "MAN"}


def _parse_move(raw: str, pos: int) -> tuple[str, int | None, int | None]:
    raw = (raw or "").strip().upper()
    if raw.startswith("NEW"):
        return "new", None, None
    if raw.startswith("RE"):
        return "re", None, None
    if raw in ("=", "-", "–", ""):
        return ("same", 0, pos) if raw == "=" else ("", None, None)
    m = re.match(r"^([+-])(\d+)$", raw)
    if m:
        n = int(m.group(2)) * (1 if m.group(1) == "+" else -1)
        return ("up" if n > 0 else "down" if n < 0 else "same"), n, pos + n if n else pos
    return "", None, None


def parse_kworb(html: str, chart: Chart) -> None:
    soup = BeautifulSoup(html, "html.parser")
    table, heads = None, []
    for t in soup.find_all("table"):
        first = t.find("tr")
        if not first:
            continue
        hs = [c.get_text(" ", strip=True).lower() for c in first.find_all(["th", "td"])]
        if any("artist" in h or h == "track" for h in hs):
            table, heads = t, hs
            break
    if table is None:
        raise ValueError("chart table not found on the page")

    def col(*names):
        for n in names:
            if n in heads:
                return heads.index(n)
        return None

    i_pos = col("pos", "#", "rank") or 0
    i_move = col("p+", "+/-")
    i_who = next(i for i, h in enumerate(heads) if "artist" in h or h == "track")
    i_metric = col("streams", "pts", "aud", "points")
    i_peak = col("pk", "peak")
    i_days = col("days", "wks", "weeks")
    chart.metric_name = heads[i_metric] if i_metric is not None else ""
    chart.span_unit = "days" if i_days is not None and heads[i_days] == "days" else "wk"
    for tr in table.find_all("tr")[1:]:
        tds = tr.find_all("td")
        if len(tds) <= i_who:
            continue

        def cell(i):
            return tds[i].get_text(" ", strip=True) if i is not None and i < len(tds) else ""

        digits = re.sub(r"\D", "", cell(i_pos))
        if not digits:
            continue
        pos = int(digits)
        artist, _, title = cell(i_who).partition(" - ")
        status, move, last = _parse_move(cell(i_move), pos)
        chart.rows.append(Row(pos, (title or artist).strip(), artist.strip(), status, move, last,
                              cell(i_peak), cell(i_days), cell(i_metric)))
    m = re.search(r"(20\d\d)[/-](\d\d)[/-](\d\d)", soup.get_text(" "))
    if m:
        chart.date = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def parse_officialcharts(html: str, chart: Chart) -> None:
    soup = BeautifulSoup(html, "html.parser")
    for item in soup.select(".chart-item"):
        name = item.select_one("a.chart-name")
        key = item.select_one(".chart-key strong")
        if not name or not key:
            continue
        try:
            pos = int(re.sub(r"\D", "", key.get_text()))
        except ValueError:
            continue
        title = " ".join(s.get_text(strip=True) for s in name.find_all("span", recursive=False)
                         if "movement-icon" not in (s.get("class") or []))
        artist_el = item.select_one("a.chart-artist")
        artist = artist_el.get_text(" ", strip=True) if artist_el else ""
        lw_el = item.select_one("li.movement")
        lw = lw_el.get_text(" ", strip=True).replace("LW:", "").strip(" ,") if lw_el else ""
        status, move, last = "", None, None
        if lw.lower().startswith("new"):
            status = "new"
        elif lw.lower().startswith("re"):
            status = "re"
        elif lw.isdigit():
            last = int(lw)
            move = last - pos
            status = "up" if move > 0 else "down" if move < 0 else "same"
        peak = item.select_one("li.peak span.font-bold")
        weeks = item.select_one("li.weeks span.font-bold")
        chart.rows.append(Row(pos, smart_title(title), smart_title(artist), status, move, last,
                              peak.get_text(strip=True) if peak else "", weeks.get_text(strip=True) if weeks else ""))
    if not chart.rows:
        raise ValueError("no chart entries found on the page")
    chart.rows.sort(key=lambda r: r.pos)
    m = re.search(r"(\d{1,2}) (January|February|March|April|May|June|July|August|September|October|November|December) (20\d\d)\s*-", soup.get_text(" "))
    if m:
        chart.date = dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))


PARSERS = {"kworb": parse_kworb, "officialcharts": parse_officialcharts}


def fetch_chart(c: dict) -> Chart:
    chart = Chart(c["id"], c["name"], c.get("group", "Charts"), c["url"], c.get("kind", "songs"),
                  bool(c.get("weekly")), int(c.get("top", 10)))
    parser = PARSERS.get(c.get("type", "kworb"))
    if not parser:
        raise ValueError(f"unknown chart type '{c.get('type')}'")
    parser(http_get(c["url"]).text, chart)
    if not chart.rows:
        raise ValueError("chart was empty")
    return chart


def collect_charts(cfg: dict, log=print):
    from news import SourceHealth
    wanted = [c for c in cfg.get("charts") or [] if c.get("enabled", True)]
    log(f"Checking {len(wanted)} charts...")
    charts, health = [], []

    def one(c):
        try:
            return fetch_chart(c), None
        except Exception as exc:
            return None, describe_error(exc)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, wanted))
    for c, (chart, err) in zip(wanted, results):
        if chart:
            charts.append(chart)
            health.append(SourceHealth(c["name"], ok=True, kind="chart", total=len(chart.rows)))
            log(f"  {c['name'][:44]:<45} {len(chart.rows)} entries")
        else:
            health.append(SourceHealth(c["name"], ok=False, kind="chart", error=err))
            log(f"  {c['name'][:44]:<45} FAILED ({err})")
    return charts, health


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #
SPLIT_RE = re.compile(r"\s*(?:,|&|\bx\b|\bfeat\.?|\bft\.?|\bfeaturing\b|\bwith\b|\bw/|/|\band\b|\()\s*", re.I)
NOT_NAMES = {"the", "various artists", "various", "soundtrack", "cast", "original", "remix", "jr", "tba"}


@dataclass
class Analysis:
    snapshot: list[dict] = field(default_factory=list)
    scoreboard: list[dict] = field(default_factory=list)
    breakouts: list[dict] = field(default_factory=list)
    breakout_names: list[tuple[str, NameMatcher]] = field(default_factory=list)


def short_chart_name(name: str) -> str:
    return (name.replace("Billboard Hot 100", "Hot 100").replace("Billboard 200", "BB200")
                .replace("UK Official ", "UK ").replace(" (daily)", "")
                .replace(" (weekly)", " wk").replace("Apple Music Worldwide", "Apple WW")
                .replace("Independent", "Indie").replace("Worldwide", "WW"))


def analyze(charts: list[Chart], artists, cfg: dict) -> Analysis:
    out = Analysis()
    rules = cfg.get("breakouts") or {}
    new_top = int(rules.get("new_entry_top", 100))
    jump_min = int(rules.get("jump_at_least", 15))
    shazam_top = int(rules.get("shazam_top", 25))
    known = [a for a in artists if a.tier in ("superstar", "pinned")]

    for ch in charts:
        if ch.rows:
            r = ch.rows[0]
            out.snapshot.append({"chart": ch, "row": r})

    # Superstar scoreboard: who is where, across every chart
    board: dict[str, dict] = {}
    for a in [a for a in artists]:
        for ch in charts:
            hits = [r for r in ch.rows if a.matcher.search(r.artist)]
            if hits:
                e = board.setdefault(a.name, {"artist": a, "charts": [], "entries": 0, "best": 999})
                best = min(h.pos for h in hits)
                e["charts"].append((ch, best, len(hits)))
                e["entries"] += len(hits)
                e["best"] = min(e["best"], best)
    out.scoreboard = sorted(board.values(), key=lambda e: (-len(e["charts"]), e["best"], -e["entries"]))

    # Breakouts: songs by artists outside the superstar list that are new, jumping, or being Shazamed
    found: dict[str, dict] = {}
    for ch in charts:
        is_shazam = "shazam" in ch.id
        for r in ch.rows:
            if any(a.matcher.search(r.artist) for a in known):
                continue
            reason = ""
            if r.status in ("new", "re") and r.pos <= new_top:
                reason = "NEW" if r.status == "new" else "RE-ENTRY"
            elif r.move is not None and r.move >= jump_min:
                reason = f"▲{r.move}"
            elif is_shazam and r.pos <= shazam_top:
                reason = "Shazam"
            if not reason:
                continue
            key = norm_title(r.title)[:40] + "|" + norm_title(SPLIT_RE.split(r.artist)[0])[:30]
            e = found.setdefault(key, {"title": r.title, "artist": r.artist, "evidence": [], "best": 999})
            e["evidence"].append(f"{short_chart_name(ch.name)} #{r.pos} {reason if reason != 'Shazam' else ''}".strip())
            e["best"] = min(e["best"], r.pos)
    out.breakouts = sorted(found.values(), key=lambda e: (-len(e["evidence"]), e["best"]))

    names: dict[str, NameMatcher] = {}
    for e in out.breakouts[:60]:
        for part in SPLIT_RE.split(e["artist"]):
            part = part.strip(" )")
            if len(part) >= 4 and part.lower() not in NOT_NAMES and not part.isdigit():
                key = part.lower()
                if key not in names:
                    names[key] = NameMatcher([part])
    out.breakout_names = list(names.items())
    return out
