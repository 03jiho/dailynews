from __future__ import annotations

import html
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from .models import Briefing

KST = ZoneInfo("Asia/Seoul")
_WEEKDAYS = "월화수목금토일"
TG_LIMIT = 4000  # 텔레그램 한도 4096자보다 여유를 둔다


def format_header(now: datetime | None = None) -> str:
    now = (now or datetime.now(KST)).astimezone(KST)
    return f"📰 <b>{now.month}월 {now.day}일({_WEEKDAYS[now.weekday()]}) 아침 브리핑</b>"


def _source_links(b: Briefing) -> str:
    parts = []
    for name, link in b.sources:
        if link:
            parts.append(f'<a href="{html.escape(link, quote=True)}">{html.escape(name)}</a>')
        else:
            parts.append(html.escape(name))
    return " · ".join(parts)


def format_briefing(index: int, b: Briefing) -> str:
    lines = [f"<b>{index}. {html.escape(b.headline)}</b>  <i>[{html.escape(b.category)}]</i>"]
    if b.summary:
        lines.append(html.escape(b.summary))
    if b.differences:
        lines.append(f"↔ {html.escape(b.differences)}")
    if b.evidence:
        ev = b.evidence[0]
        lines.append(f"🔎 “{html.escape(ev.quote)}” — {html.escape(ev.source)}")
    if b.flags:
        lines.append("⚠️ " + html.escape(" / ".join(b.flags)))
    lines.append("🔗 " + _source_links(b))
    return "\n".join(lines)


def split_messages(blocks: list[str], limit: int = TG_LIMIT) -> list[str]:
    """블록 경계를 지키면서 limit 이하로 메시지를 나눈다."""
    messages: list[str] = []
    current = ""
    for block in blocks:
        if len(block) > limit:
            block = block[: limit - 1] + "…"
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > limit:
            messages.append(current)
            current = block
        else:
            current = candidate
    if current:
        messages.append(current)
    return messages


def send_message(token: str, chat_id: str, text: str) -> None:
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=15,
    )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"텔레그램 전송 실패: {data.get('description')}")


def send_all(token: str, chat_id: str, blocks: list[str]) -> int:
    messages = split_messages(blocks)
    for i, text in enumerate(messages):
        if i:
            time.sleep(0.5)
        send_message(token, chat_id, text)
    return len(messages)
