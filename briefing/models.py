from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

INBOX_SOURCE = "내 수집함"


@dataclass(frozen=True)
class Article:
    source: str
    title: str
    summary: str
    link: str
    published: datetime | None = None

    @property
    def text(self) -> str:
        return f"{self.title} {self.summary}".strip()


@dataclass
class Cluster:
    """같은 사건을 다룬 기사 묶음."""

    articles: list[Article]

    @property
    def sources(self) -> list[str]:
        seen: list[str] = []
        for a in self.articles:
            if a.source not in seen:
                seen.append(a.source)
        return seen

    @property
    def has_inbox(self) -> bool:
        return any(a.source == INBOX_SOURCE for a in self.articles)

    @property
    def latest_ts(self) -> float:
        stamps = [a.published.timestamp() for a in self.articles if a.published]
        return max(stamps) if stamps else 0.0


@dataclass
class Evidence:
    source: str
    quote: str
    link: str


@dataclass
class Briefing:
    headline: str
    category: str
    summary: str
    differences: str | None = None
    evidence: list[Evidence] = field(default_factory=list)
    sources: list[tuple[str, str]] = field(default_factory=list)  # (매체명, 링크)
    flags: list[str] = field(default_factory=list)
    llm_ok: bool = True
