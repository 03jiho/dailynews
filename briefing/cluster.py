from __future__ import annotations

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .models import Article, Cluster


def cluster_articles(articles: list[Article], threshold: float = 0.30) -> list[Cluster]:
    """제목+요약 앞부분의 글자 n-gram TF-IDF로 같은 사건 기사를 묶는다.

    별도 임베딩 API 없이 한국어에서 충분히 동작하고 비용이 0원이다.
    클러스터 내 평균 유사도(average linkage)를 써서 연쇄적으로 엉뚱한 기사가 붙는 걸 막는다.
    """
    if not articles:
        return []
    if len(articles) == 1:
        return [Cluster(list(articles))]

    texts = [f"{a.title} {a.summary[:80]}" for a in articles]
    matrix = TfidfVectorizer(
        analyzer="char_wb", ngram_range=(2, 3), sublinear_tf=True
    ).fit_transform(texts)
    sim = (matrix @ matrix.T).toarray()

    groups: list[list[int]] = []
    for i in range(len(articles)):
        best, best_score = -1, 0.0
        for gi, members in enumerate(groups):
            score = float(np.mean(sim[i, members]))
            if score > best_score:
                best, best_score = gi, score
        if best >= 0 and best_score >= threshold:
            groups[best].append(i)
        else:
            groups.append([i])
    return [Cluster([articles[i] for i in g]) for g in groups]


def rank_clusters(
    clusters: list[Cluster], min_sources: int = 2, max_clusters: int = 8
) -> list[Cluster]:
    """여러 매체가 다룬 사건을 중요도 순으로 고른다. 수집함 항목은 단독이어도 포함한다."""
    eligible = [c for c in clusters if len(c.sources) >= min_sources or c.has_inbox]
    eligible.sort(
        key=lambda c: (c.has_inbox, len(c.sources), len(c.articles), c.latest_ts),
        reverse=True,
    )
    return eligible[:max_clusters]
