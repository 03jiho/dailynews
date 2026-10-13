import random

from briefing.cluster import cluster_articles, rank_clusters
from briefing.models import INBOX_SOURCE, Article

from .samples import ALL, BUDGET, FESTIVAL, RATE, art


def _titles(cluster):
    return {a.title for a in cluster.articles}


def test_groups_same_event_regardless_of_order():
    shuffled = ALL[:]
    random.Random(0).shuffle(shuffled)
    clusters = cluster_articles(shuffled)
    groups = [_titles(c) for c in clusters]
    assert {a.title for a in RATE} in groups
    assert {a.title for a in BUDGET} in groups
    assert {a.title for a in FESTIVAL} in groups
    assert len(clusters) == 3


def test_rank_prefers_more_sources_and_drops_singletons():
    ranked = rank_clusters(cluster_articles(ALL), min_sources=2, max_clusters=8)
    assert len(ranked) == 2
    assert len(ranked[0].sources) == 3  # 금리 기사가 먼저


def test_inbox_item_is_kept_even_if_single_source():
    inbox = Article(INBOX_SOURCE, "서울 지하철 파업 예고", "노조가 다음 주 파업을 예고했다", "https://example.com/post")
    ranked = rank_clusters(cluster_articles(ALL + [inbox]), min_sources=2, max_clusters=8)
    assert ranked[0].has_inbox  # 수집함 항목이 맨 앞
    assert len(ranked) == 3


def test_empty_and_single():
    assert cluster_articles([]) == []
    assert len(cluster_articles([art("A", "제목")])) == 1
