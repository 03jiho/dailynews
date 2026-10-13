"""'내 수집함': 사용자가 봇 채팅에 보낸 메시지(인스타 소식 등)를 기사로 취급한다.

인스타그램 게시물은 공식 API로 자동 수집할 수 없으므로,
사용자가 본 소식을 봇에게 공유(캡션 복사 + 링크)하면 그걸 모아서 브리핑에 넣는다.
getUpdates는 텔레그램이 최근 24시간 분량만 보관한다.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import requests

from .fetch import clean_text
from .models import INBOX_SOURCE, Article

log = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+")
_MIN_CHARS = 10  # "hi", "테스트" 같은 인사·시험 메시지를 소식으로 착각하지 않도록


def parse_updates(
    updates: list[dict], chat_id: str, cutoff: datetime
) -> tuple[list[Article], int]:
    """텔레그램 업데이트 목록을 Article로 바꾼다. (기사 목록, 건너뛴 메시지 수)"""
    articles: list[Article] = []
    skipped = 0
    for upd in updates:
        msg = upd.get("message")
        if not msg or str(msg.get("chat", {}).get("id")) != str(chat_id):
            continue
        sent = datetime.fromtimestamp(msg.get("date", 0), tz=timezone.utc)
        if sent < cutoff:
            continue

        raw = (msg.get("text") or msg.get("caption") or "").strip()
        if not raw or raw.startswith("/"):
            skipped += 1  # 이미지만 보냈거나 명령어
            continue

        urls = _URL_RE.findall(raw)
        body = _URL_RE.sub(" ", raw)
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        if len(" ".join(lines)) < _MIN_CHARS:
            skipped += 1  # 링크만 보냈거나 인사처럼 너무 짧아 소식이 아니다
            continue

        title = clean_text(lines[0], 200)
        summary = clean_text(" ".join(lines[1:]), 300)
        articles.append(
            Article(
                source=INBOX_SOURCE,
                title=title,
                summary=summary,
                link=urls[0] if urls else "",
                published=sent,
            )
        )
    return articles, skipped


def fetch_inbox(
    token: str, chat_id: str, window_hours: int = 24, now: datetime | None = None
) -> list[Article]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window_hours)
    resp = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params={"timeout": 0, "allowed_updates": '["message"]'},
        timeout=15,
    )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"getUpdates 실패: {data.get('description')}")
    articles, skipped = parse_updates(data.get("result", []), chat_id, cutoff)
    if skipped:
        log.info("수집함: 읽을 수 없는 메시지 %d건 건너뜀 (이미지만/링크만/명령어)", skipped)
    log.info("수집함: %d건", len(articles))
    return articles
