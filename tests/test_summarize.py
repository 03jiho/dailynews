import json

from briefing.cluster import cluster_articles
from briefing.summarize import parse_json_array, summarize_clusters
from briefing.verify import check_evidence, check_numbers

from .samples import ALL, RATE


def _clusters():
    return [c for c in cluster_articles(ALL) if len(c.sources) >= 2]


def _good_item(cluster_id: str, quote_src: int = 1, quote: str = "기준금리를 연 2.50%로 유지") -> dict:
    return {
        "cluster": cluster_id,
        "headline": "한국은행, 기준금리 연 2.50% 동결",
        "category": "경제",
        "summary": "한국은행이 기준금리를 연 2.50%로 동결했다.",
        "differences": None,
        "evidence": [{"source": quote_src, "quote": quote}],
    }


def test_parse_json_array_handles_code_fence_and_chatter():
    raw = '설명입니다\n```json\n[{"cluster": "C1"}]\n```\n끝'
    assert parse_json_array(raw) == [{"cluster": "C1"}]


def test_evidence_must_be_verbatim():
    cluster = cluster_articles(RATE)[0]
    ok, bad = check_evidence([{"source": 1, "quote": "기준금리를 연 2.50%로 유지"}], cluster)
    assert len(ok) == 1 and bad == 0
    ok, bad = check_evidence([{"source": 1, "quote": "기준금리를 3%로 인상"}, {"source": 9, "quote": "x"}], cluster)
    assert ok == [] and bad == 2


def test_number_check_flags_invented_numbers():
    cluster = cluster_articles(RATE)[0]
    assert check_numbers(["금리를 연 2.50%로 동결"], cluster) == []
    assert check_numbers(["금리를 연 3.25%로 인하"], cluster) == ["3.25"]


def test_summarize_happy_path_and_usage():
    clusters = _clusters()

    def fake_llm(system, user):
        items = [_good_item(f"C{i}") for i in range(1, len(clusters) + 1)]
        # 첫 클러스터가 금리 기사가 아닐 수 있으므로 근거는 실제 기사 텍스트에 맞춘다
        for item, cluster in zip(items, clusters):
            item["evidence"] = [{"source": 1, "quote": cluster.articles[0].title[:12]}]
            item["summary"] = cluster.articles[0].title
            item["headline"] = cluster.articles[0].title
        return json.dumps(items, ensure_ascii=False), {"input_tokens": 100, "output_tokens": 50}

    briefings, usage = summarize_clusters(clusters, fake_llm)
    assert len(briefings) == len(clusters)
    assert all(b.llm_ok and b.evidence for b in briefings)
    assert usage == {"input_tokens": 100, "output_tokens": 50, "llm_calls": 1}


def test_bad_json_retries_then_falls_back():
    clusters = _clusters()
    calls = []

    def broken_llm(system, user):
        calls.append(1)
        return "죄송합니다, 정리하지 못했어요", {"input_tokens": 10, "output_tokens": 5}

    briefings, usage = summarize_clusters(clusters, broken_llm, retries=1)
    assert len(calls) == 2  # 최초 + 재시도 1회
    assert all(not b.llm_ok and b.flags for b in briefings)
    assert briefings[0].headline == clusters[0].articles[0].title


def test_unverifiable_output_is_flagged_not_dropped():
    clusters = [cluster_articles(RATE)[0]]

    def sloppy_llm(system, user):
        item = _good_item("C1", quote="기준금리를 3%로 인상")
        item["summary"] = "한국은행이 기준금리를 연 3.25%로 인하했다."
        return json.dumps([item], ensure_ascii=False), {"input_tokens": 1, "output_tokens": 1}

    (b,), _ = summarize_clusters(clusters, sloppy_llm)
    assert b.llm_ok
    assert b.evidence == []
    assert any("검증된 근거 없음" in f for f in b.flags)
    assert any("3.25" in f for f in b.flags)
