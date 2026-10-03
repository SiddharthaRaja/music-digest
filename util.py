"""Small shared helpers: text cleaning, word matching, polite web requests, formatting."""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import re
import threading
import time
import unicodedata
import warnings
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)
UTC = dt.timezone.utc

# --------------------------------------------------------------------------- #
# Web requests
# --------------------------------------------------------------------------- #
USER_AGENT = "MusicDigest/2.0 (personal music news digest; RSS reader)"
_host_locks: dict[str, threading.Lock] = {}
_host_last: dict[str, float] = {}
_registry_lock = threading.Lock()
# Seconds to wait between requests to the same site, so we never hammer anyone.
HOST_GAP = {"news.google.com": 1.2, "kworb.net": 0.5, "www.officialcharts.com": 0.8}


def set_user_agent(ua: str | None) -> None:
    global USER_AGENT
    if ua:
        USER_AGENT = ua


def _wait_turn(host: str) -> None:
    gap = HOST_GAP.get(host, 0)
    if not gap:
        return
    with _registry_lock:
        lock = _host_locks.setdefault(host, threading.Lock())
    with lock:
        wait = _host_last.get(host, 0) + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _host_last[host] = time.monotonic()


def http_get(url: str, timeout: int = 25, tries: int = 3) -> requests.Response:
    host = urlsplit(url).netloc
    headers = {"User-Agent": USER_AGENT,
               "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html;q=0.9, */*;q=0.8"}
    last_exc: Exception | None = None
    for attempt in range(tries):
        _wait_turn(host)
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            if attempt < tries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    if last_exc:
        raise last_exc
    resp.raise_for_status()
    return resp


def describe_error(exc: Exception) -> str:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        code = exc.response.status_code
        extra = {402: " (asks bots to pay)", 403: " (blocked)", 404: " (not found)", 429: " (too many requests)"}
        return f"website said {code}{extra.get(code, '')}"
    if isinstance(exc, requests.Timeout):
        return "timed out"
    if isinstance(exc, requests.ConnectionError):
        return "couldn't connect"
    return (str(exc)[:80] or exc.__class__.__name__)


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #
STOPWORDS = set(
    """a an the and or of to in on at for with from by as is are was were be been being it its this that
    these those his her their them they he she you your our we i me my new news says say said after before
    over into out up about amid than then just more most first last will would can could has have had not no
    how why what who when where here there all one two get gets got make makes made via""".split()
)


def clean_title(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def clean_summary(raw: str, title: str = "", limit: int = 240) -> str:
    text = BeautifulSoup(raw or "", "html.parser").get_text(" ")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"The post .{0,400}? appeared first on .{0,80}?\.?$", "", text).strip()  # WordPress footer
    text = re.sub(r"\[(?:…|\.\.\.)\]$", "…", text).strip()
    text = re.sub(r"\s*(Continue reading|Read more)\.*\s*$", "", text, flags=re.I).strip()
    if not text or (title and text.lower().startswith(title.lower()[:60])):
        return ""
    if len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:-–— ")
        text = cut + "…"
    return text


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def norm_title(title: str) -> str:
    t = strip_accents(title.lower()).replace("’", "'").replace("‘", "'")
    t = re.sub(r"'s\b", "", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def title_tokens(title: str) -> set[str]:
    return {w for w in norm_title(title).split() if (len(w) >= 3 or w.isdigit()) and w not in STOPWORDS}


def canonical_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
        query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(("utm_", "ref", "fbclid"))]
        host = parts.netloc.lower().removeprefix("www.")
        return urlunsplit(("https", host, parts.path.rstrip("/"), urlencode(query), ""))
    except Exception:
        return url


def short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def esc(text) -> str:
    return html.escape(str(text or ""), quote=True)


# --------------------------------------------------------------------------- #
# Word & name matching
# --------------------------------------------------------------------------- #
def keyword_pattern(kw: str) -> re.Pattern:
    """'tour' also matches tours/touring; 'nominat*' is a prefix; '=EP' is an exact, case-sensitive word."""
    kw = str(kw).strip()
    if kw.startswith("="):
        return re.compile(r"(?<![\w])" + re.escape(kw[1:]) + r"(?![\w])")
    if kw.endswith("*"):
        return re.compile(r"(?<![\w])" + re.escape(kw[:-1]), re.I)
    return re.compile(r"(?<![\w])" + re.escape(kw) + r"(?:s|es|d|ed|ing|ings)?(?![\w])", re.I)


class NameMatcher:
    """Matches an artist's names in text. Names starting with '=' are case-sensitive."""

    def __init__(self, names: list[str]):
        loose, exact = set(), set()
        for raw in names:
            raw = str(raw).strip()
            if not raw:
                continue
            if raw.startswith("="):
                exact.add(raw[1:])
                continue
            loose.add(raw)
            plain = strip_accents(raw)
            if plain != raw and len(plain) >= 6:   # Beyoncé -> Beyonce (but not ROSÉ -> ROSE)
                loose.add(plain)
        tail = r"(?:'s|’s)?(?![\w])"
        self.loose = re.compile(r"(?<![\w])(?:" + "|".join(map(re.escape, sorted(loose, key=len, reverse=True))) + ")" + tail, re.I) if loose else None
        self.exact = re.compile(r"(?<![\w])(?:" + "|".join(map(re.escape, sorted(exact, key=len, reverse=True))) + ")" + tail) if exact else None

    def search(self, text: str):
        if not text:
            return None
        return (self.loose.search(text) if self.loose else None) or (self.exact.search(text) if self.exact else None)


def display_name(raw: str) -> str:
    return str(raw).lstrip("=").strip()


# --------------------------------------------------------------------------- #
# Time formatting
# --------------------------------------------------------------------------- #
def ago(t: dt.datetime | None, now: dt.datetime) -> str:
    if not t:
        return ""
    s = max(0, (now - t).total_seconds())
    if s < 3600:
        return f"{max(1, int(s // 60))}m ago"
    if s < 86400:
        return f"{int(s // 3600)}h ago"
    days = int(s // 86400)
    return "yesterday" if days == 1 else f"{days}d ago"


def nice_day(d) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def nice_time(d: dt.datetime) -> str:
    return d.strftime("%I:%M %p").lstrip("0")
