"""LLM 요약이 원문에 근거하는지 LLM 없이 기계적으로 검사한다.

1. 근거 인용(quote)이 해당 기사 텍스트에 글자 그대로 있는지
2. 요약에 나온 숫자가 원문 어딘가에 있는지
검사에 실패한 항목은 버리지 않고 flag로 표시해 읽는 사람이 알 수 있게 한다.
"""
from __future__ import annotations

import re

from .models import Cluster, Evidence
from .prompts import CATEGORIES

_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in _NUM_RE.findall(text)}


def check_evidence(
    raw_evidence: list, cluster: Cluster
) -> tuple[list[Evidence], int]:
    """(검증된 근거 목록, 불일치 건수)"""
    valid: list[Evidence] = []
    bad = 0
    for item in raw_evidence or []:
        try:
            idx = int(item["source"]) - 1
            quote = str(item["quote"]).strip()
            article = cluster.articles[idx]
        except (KeyError, ValueError, TypeError, IndexError):
            bad += 1
            continue
        if idx < 0 or not quote or _squash(quote) not in _squash(article.text):
            bad += 1
            continue
        valid.append(Evidence(source=article.source, quote=quote, link=article.link))
    return valid, bad


def check_numbers(texts: list[str], cluster: Cluster) -> list[str]:
    """요약에 있지만 원문에는 없는 숫자 목록."""
    claimed = set().union(*(_numbers(t) for t in texts if t)) if texts else set()
    source_text = " ".join(a.text for a in cluster.articles).replace(",", "")
    return sorted(n for n in claimed if n not in source_text)


def normalize_category(value: object) -> str:
    return value if isinstance(value, str) and value in CATEGORIES else "기타"
