from __future__ import annotations

import json
import logging
from typing import Callable

from .models import Briefing, Cluster
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .verify import check_evidence, check_numbers, normalize_category

log = logging.getLogger(__name__)

# (system, user) -> (응답 텍스트, {"input_tokens": int, "output_tokens": int})
LLMCall = Callable[[str, str], tuple[str, dict]]


def parse_json_array(text: str) -> list[dict]:
    """{"items": [...]} (JSON 모드) 또는 맨 배열 [...] 응답에서 사건 목록을 꺼낸다."""
    starts = [i for i in (text.find("["), text.find("{")) if i != -1]
    if not starts:
        raise ValueError("JSON을 찾지 못했습니다")
    start = min(starts)
    end = text.rfind("]" if text[start] == "[" else "}")
    if end <= start:
        raise ValueError("JSON을 찾지 못했습니다")
    data = json.loads(text[start : end + 1])
    if isinstance(data, dict):
        data = data.get("items")
    if not isinstance(data, list):
        raise ValueError("JSON 최상위가 배열이 아닙니다")
    return [d for d in data if isinstance(d, dict)]


def _sources_of(cluster: Cluster) -> list[tuple[str, str]]:
    """매체별로 첫 기사 링크 하나씩."""
    out: dict[str, str] = {}
    for a in cluster.articles:
        out.setdefault(a.source, a.link)
    return list(out.items())


def fallback_briefing(cluster: Cluster, reason: str) -> Briefing:
    first = cluster.articles[0]
    return Briefing(
        headline=first.title,
        category="기타",
        summary=first.summary[:150],
        sources=_sources_of(cluster),
        flags=[reason],
        llm_ok=False,
    )


def extractive_briefing(cluster: Cluster) -> Briefing:
    """LLM 없이 만드는 브리핑: 매체별 제목을 나란히 보여준다 (제목 차이가 곧 관점 차이)."""
    seen: dict[str, str] = {}
    for a in cluster.articles:
        seen.setdefault(a.source, a.title)
    return Briefing(
        headline=cluster.articles[0].title,
        category="기타",
        summary="\n".join(f"• {src}: {title}" for src, title in seen.items()),
        sources=_sources_of(cluster),
        llm_ok=False,  # LLM 요약이 아니므로 품질 평가 대상에서 제외
    )


def build_briefing(item: dict, cluster: Cluster) -> Briefing:
    headline = str(item.get("headline") or cluster.articles[0].title).strip()
    summary = str(item.get("summary") or "").strip()
    differences = item.get("differences")
    differences = str(differences).strip() if differences else None

    evidence, bad = check_evidence(item.get("evidence"), cluster)
    flags: list[str] = []
    if bad:
        flags.append(f"근거 인용 {bad}건이 원문과 달라 제외")
    if not evidence:
        flags.append("검증된 근거 없음")
    missing = check_numbers([headline, summary, differences or ""], cluster)
    if missing:
        flags.append("원문에서 확인되지 않은 숫자: " + ", ".join(missing))

    return Briefing(
        headline=headline,
        category=normalize_category(item.get("category")),
        summary=summary,
        differences=differences,
        evidence=evidence,
        sources=_sources_of(cluster),
        flags=flags,
    )


def summarize_clusters(
    clusters: list[Cluster],
    call_llm: LLMCall | None,
    chunk_size: int = 5,
    retries: int = 1,
) -> tuple[list[Briefing], dict]:
    """클러스터를 chunk_size개씩 묶어 한 번에 요약한다. (브리핑 목록, 토큰 사용량)

    call_llm이 None이면 LLM 없이 매체별 제목 비교 브리핑을 만든다.
    """
    usage = {"input_tokens": 0, "output_tokens": 0, "llm_calls": 0}
    if call_llm is None:
        return [extractive_briefing(c) for c in clusters], usage
    briefings: list[Briefing] = []

    for start in range(0, len(clusters), chunk_size):
        chunk = clusters[start : start + chunk_size]
        user_prompt = build_user_prompt(chunk, start_index=start + 1)

        parsed: dict[str, dict] | None = None
        for attempt in range(retries + 1):
            try:
                text, used = call_llm(SYSTEM_PROMPT, user_prompt)
                usage["llm_calls"] += 1
                usage["input_tokens"] += used.get("input_tokens", 0)
                usage["output_tokens"] += used.get("output_tokens", 0)
                parsed = {
                    str(d.get("cluster")): d for d in parse_json_array(text)
                }
                break
            except Exception as exc:
                log.warning("요약 호출 실패 (시도 %d): %s", attempt + 1, exc)

        for offset, cluster in enumerate(chunk):
            item = (parsed or {}).get(f"C{start + offset + 1}")
            if item is None:
                briefings.append(fallback_briefing(cluster, "요약 실패: 원문 제목만 표시"))
            else:
                briefings.append(build_briefing(item, cluster))

    return briefings, usage
