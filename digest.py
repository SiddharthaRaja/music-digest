#!/usr/bin/env python3
"""
Music Digest
============
Reads dozens of music news sources and charts, merges duplicate stories, sorts them into
detailed sections and emails you two digests: News, and Charts & Stats.

    python digest.py              build + email everything new since the last digest
    python digest.py --preview    build + open in your browser (no email, nothing remembered)
    python digest.py --hours 72   look back 72 hours, including stories you've already seen

Everything you'd want to change (artists, websites, sections, charts) lives in config.yaml.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import smtplib
import sys
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

try:  # keep Windows terminals from crashing on symbols in headlines
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import ai as ai_mod  # noqa: E402
import charts as charts_mod  # noqa: E402
import news  # noqa: E402
import render  # noqa: E402
import util  # noqa: E402
from util import UTC  # noqa: E402

STATE_FILE = ROOT / "state" / "seen.json"
OUTPUT_DIR = ROOT / "output"


# --------------------------------------------------------------------------- #
# Settings, memory, email
# --------------------------------------------------------------------------- #
def load_config(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        where = getattr(exc, "problem_mark", None)
        line = f" around line {where.line + 1}" if where else ""
        sys.exit(f"config.yaml has a typo{line}. Check the spacing and brackets there.\n({exc})")


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if not (os.environ.get(key) or "").strip():
            os.environ[key] = value


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict, items, now: dt.datetime, calendar: dict, charts, keep_days: int = 10) -> None:
    seen = dict(state.get("seen") or {})
    stamp = now.isoformat(timespec="seconds")
    for it in items:
        for i in it.ids:
            seen.setdefault(i, stamp)
    limit = now - dt.timedelta(days=keep_days)
    seen = {k: v for k, v in seen.items() if dt.datetime.fromisoformat(v) >= limit}
    chart_dates = dict(state.get("charts") or {})
    for ch in charts:
        if ch.date:
            chart_dates[ch.id] = ch.date.isoformat()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"last_run": stamp, "charts": chart_dates, "calendar": calendar,
                                      "seen": dict(sorted(seen.items()))}, indent=0, ensure_ascii=False),
                          encoding="utf-8")


def email_configured() -> bool:
    return bool((os.environ.get("EMAIL_ADDRESS") or "").strip() and (os.environ.get("EMAIL_APP_PASSWORD") or "").strip())


def send_email(subject: str, html_body: str, text_body: str, sender_name: str, attachments=()) -> None:
    user = (os.environ.get("EMAIL_ADDRESS") or "").strip()
    password = (os.environ.get("EMAIL_APP_PASSWORD") or "").replace(" ", "").strip()
    to = (os.environ.get("EMAIL_TO") or "").strip() or user
    host = (os.environ.get("SMTP_HOST") or "smtp.gmail.com").strip()
    port = int((os.environ.get("SMTP_PORT") or "465").strip())
    body = MIMEMultipart("alternative")
    body.attach(MIMEText(text_body, "plain", "utf-8"))
    body.attach(MIMEText(html_body, "html", "utf-8"))
    if attachments:
        msg = MIMEMultipart("mixed")
        msg.attach(body)
        for filename, content in attachments:
            part = MIMEText(content, "html", "utf-8")
            part.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(part)
    else:
        msg = body
    msg["Subject"] = subject
    msg["From"] = formataddr((sender_name, user))
    msg["To"] = to
    recipients = [a.strip() for a in to.split(",") if a.strip()]
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=60) as s:
            s.login(user, password)
            s.sendmail(user, recipients, msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=60) as s:
            s.starttls()
            s.login(user, password)
            s.sendmail(user, recipients, msg.as_string())


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build and email your music news digest.")
    p.add_argument("--preview", action="store_true", help="open the digest in your browser; don't email or remember anything")
    p.add_argument("--hours", type=float, help="look back this many hours, including stories you've already seen")
    p.add_argument("--no-open", action="store_true", help="never open a browser (used by the automatic run)")
    p.add_argument("--config", default="config.yaml", help="settings file (default: config.yaml)")
    return p.parse_args()


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #
def main() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env")
    cfg = load_config(ROOT / args.config)
    settings = cfg.get("settings") or {}
    util.set_user_agent(settings.get("user_agent"))
    tz = ZoneInfo(cfg.get("timezone", "Asia/Kolkata"))
    now = dt.datetime.now(UTC)
    state = load_state()

    ignore_seen = False
    if args.hours:
        since = now - dt.timedelta(hours=args.hours)
        ignore_seen = True
    elif state.get("last_run"):
        overlap = dt.timedelta(hours=float(settings.get("overlap_hours", 2)))
        since = max(dt.datetime.fromisoformat(state["last_run"]) - overlap, now - dt.timedelta(days=7))
    else:
        since = now - dt.timedelta(hours=float(settings.get("first_run_hours", 24)))
    days = max(1, math.ceil((now - since).total_seconds() / 86400))
    print(f"Looking for news since {since.astimezone(tz):%a %d %b %H:%M} ({tz.key})")

    artists = news.build_artists(cfg)
    with ThreadPoolExecutor(max_workers=2) as pool:
        news_job = pool.submit(news.collect, cfg, artists, since, days)
        charts_job = pool.submit(charts_mod.collect_charts, cfg)
        items, health = news_job.result()
        chart_list, chart_health = charts_job.result()

    if not any(h.ok for h in health + chart_health):
        print("Every source failed. Is the internet connection working? No digest sent.")
        return 1

    fetched = list(items)
    if not ignore_seen:
        seen = state.get("seen") or {}
        items = [i for i in items if not any(x in seen for x in i.ids)]

    # weekly charts: shown in full only when they've changed since the last digest
    old_dates = state.get("charts") or {}
    for ch in chart_list:
        ch.fresh = not (ch.weekly and ch.date and old_dates.get(ch.id) == ch.date.isoformat())

    stories = news.group_stories(items)
    news.rank_stories(stories, cfg, now)
    analysis = charts_mod.analyze(chart_list, artists, cfg)
    sections = news.place_stories(stories, cfg, artists, analysis.breakout_names)
    print(f"{len(items)} new articles -> {len(stories)} stories; "
          f"{len(analysis.breakouts)} chart breakouts spotted")

    followed = [a.name for a in artists if a.tier in ("pinned", "superstar")]
    ai = ai_mod.ai_summary(sections, cfg, followed)
    if ai:
        print(f"Added AI summary ({ai['headlines_used']} headlines read)")

    today = now.astimezone(tz).date()
    days_ahead = int(settings.get("calendar_days_ahead", 45))
    found_dates = news.extract_release_dates(stories, today, days_ahead, tz)
    for r in (ai or {}).get("releases", []):
        d = news.parse_loose_date(str(r.get("date", "")), today)
        if d and today <= d <= today + dt.timedelta(days=days_ahead):
            found_dates.append({"date": d.isoformat(), "title": f"{r.get('artist')} – {r.get('release')}",
                                "link": "", "source": "AI summary", "artists": [str(r.get("artist"))]})
    calendar = news.merge_calendar(state.get("calendar") or {}, found_dates, today, now.isoformat(timespec="seconds"))

    ctx = render.Ctx(cfg=cfg, now=now, since=since, tz=tz, sections=sections, charts=chart_list, analysis=analysis,
                     health=health, chart_health=chart_health, ai=ai, calendar=calendar,
                     numbers=news.extract_numbers(stories), total_items=len(items),
                     pinned_artists=[a for a in artists if a.tier == "pinned"])
    email_cfg = cfg.get("email") or {}
    separate = email_cfg.get("separate_charts_email", True)
    news_subject, news_html, news_text = render.news_email(ctx, include_charts=not separate)
    charts_out = render.charts_email(ctx) if separate else None
    full_html = render.full_digest(ctx)

    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = now.astimezone(tz).strftime("%Y-%m-%d-%H%M")
    paths = {"news": OUTPUT_DIR / f"news-{stamp}.html", "full": OUTPUT_DIR / f"full-digest-{stamp}.html"}
    paths["news"].write_text(news_html, encoding="utf-8")
    paths["full"].write_text(full_html, encoding="utf-8")
    if charts_out:
        paths["charts"] = OUTPUT_DIR / f"charts-{stamp}.html"
        paths["charts"].write_text(charts_out[1], encoding="utf-8")
    for name, p in paths.items():
        print(f"Saved {p.relative_to(ROOT)} ({p.stat().st_size / 1024:.0f} KB)")

    in_ci = bool(os.environ.get("CI")) or args.no_open
    if args.preview:
        print(f"Preview only. News subject: {news_subject}")
        if not in_ci:
            for key in ("news", "charts"):
                if key in paths:
                    webbrowser.open(paths[key].resolve().as_uri())
        return 0

    if not email_configured():
        print("No email settings found (EMAIL_ADDRESS / EMAIL_APP_PASSWORD), so the digest was only saved.")
        if os.environ.get("GITHUB_ACTIONS"):
            print("Add EMAIL_ADDRESS and EMAIL_APP_PASSWORD under Settings > Secrets and variables > Actions.")
        if in_ci:
            return 1
        webbrowser.open(paths["news"].resolve().as_uri())
    else:
        sender = ctx.title
        attachments = [(f"full-digest-{stamp}.html", full_html)] if email_cfg.get("attach_full_digest", True) else []
        try:
            send_email(news_subject, news_html, news_text, sender, attachments)
            print(f"Emailed: {news_subject}")
            if charts_out:
                send_email(charts_out[0], charts_out[1], charts_out[2], sender)
                print(f"Emailed: {charts_out[0]}")
        except smtplib.SMTPAuthenticationError:
            print("Email login failed. Check EMAIL_ADDRESS and EMAIL_APP_PASSWORD (it must be a Gmail *app password*).")
            return 1
        except Exception as exc:
            print(f"Couldn't send the email: {exc}")
            return 1

    save_state(state, fetched, now, calendar, chart_list)
    return 0


if __name__ == "__main__":
    sys.exit(main())
