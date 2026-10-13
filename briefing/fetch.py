from __future__ import annotations

import calendar
import html
import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from .models import Article

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_UA = "Mozilla/5.0 (compatible; news-briefing-bot/1.0)"


def clean_text(raw: str | None, limit: int = 300) -> str:
    text = html.unescape(_TAG_RE.sub(" ", raw or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _published(entry) -> datetime | None:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if not t:
        return None
    return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)


def fetch_feed(name: str, url: str, timeout: int = 10) -> list[Article]:
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": _UA})
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    articles = []
    for e in parsed.entries:
        title = clean_text(e.get("title"), 200)
        link = e.get("link", "")
        if not title or not link:
            continue
        articles.append(
            Article(
                source=name,
                title=title,
                summary=clean_text(e.get("summary") or e.get("description")),
                link=link,
                published=_published(e),
            )
        )
    return articles


def _norm_title(title: str) -> str:
    return re.sub(r"[\W_]+", "", title).lower()


def fetch_all(
    feeds: list[dict],
    window_hours: int = 24,
    per_feed_limit: int = 40,
    now: datetime | None = None,
) -> tuple[list[Article], list[str]]:
    """모든 피드를 수집한다. 실패한 피드는 건너뛰고 이름을 돌려준다."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window_hours)
    collected: list[Article] = []
    failed: list[str] = []
    seen_links: set[str] = set()
    seen_titles: set[tuple[str, str]] = set()

    for feed in feeds:
        name, url = feed["name"], feed["url"]
        try:
            items = fetch_feed(name, url)
        except Exception as exc:  # 한 매체가 죽어도 브리핑은 계속
            log.warning("피드 실패: %s (%s)", name, exc)
            failed.append(name)
            continue

        kept = 0
        for a in items:
            if a.published and a.published < cutoff:
                continue
            key = (a.source, _norm_title(a.title))
            if a.link in seen_links or key in seen_titles:
                continue
            seen_links.add(a.link)
            seen_titles.add(key)
            collected.append(a)
            kept += 1
            if kept >= per_feed_limit:
                break
        log.info("%s: %d건", name, kept)

    return collected, failed
