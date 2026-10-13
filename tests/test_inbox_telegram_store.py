from datetime import datetime, timedelta, timezone

from briefing.inbox import parse_updates
from briefing.models import Briefing, Evidence
from briefing.store import connect, eval_report, export_eval_csv, save_run, usage_stats
from briefing.telegram import format_briefing, split_messages

NOW = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
CUTOFF = NOW - timedelta(hours=24)


def _upd(text=None, caption=None, chat=1, age_h=1):
    msg = {"chat": {"id": chat}, "date": int((NOW - timedelta(hours=age_h)).timestamp())}
    if text is not None:
        msg["text"] = text
    if caption is not None:
        msg["caption"] = caption
    return {"message": msg}


def test_inbox_parses_caption_and_link():
    updates = [_upd(text="서울 지하철 파업 예고\n노조가 다음 주 파업을 예고했다 https://instagram.com/p/abc")]
    (a,), skipped = parse_updates(updates, "1", CUTOFF)
    assert a.title == "서울 지하철 파업 예고"
    assert a.summary == "노조가 다음 주 파업을 예고했다"
    assert a.link == "https://instagram.com/p/abc"
    assert skipped == 0


def test_inbox_skips_unreadable_old_and_other_chats():
    updates = [
        _upd(text="https://instagram.com/p/only-link"),  # 링크만
        _upd(),  # 이미지만 (텍스트 없음)
        _upd(text="/start"),
        _upd(text="hi"),  # 인사·시험 메시지
        _upd(text="너무 오래된 소식", age_h=30),
        _upd(text="다른 채팅", chat=2),
        _upd(caption="이미지에 붙은 캡션 소식"),
    ]
    articles, skipped = parse_updates(updates, "1", CUTOFF)
    assert [a.title for a in articles] == ["이미지에 붙은 캡션 소식"]
    assert skipped == 4


def test_format_escapes_html_and_splits_on_block_boundaries():
    b = Briefing(
        headline="A <b>& B",
        category="경제",
        summary="x < y",
        evidence=[Evidence("연합뉴스", "인용", "https://e.com/?a=1&b=2")],
        sources=[("연합뉴스", "https://e.com/?a=1&b=2")],
        flags=["숫자 확인 필요"],
    )
    text = format_briefing(1, b)
    assert "A &lt;b&gt;&amp; B" in text and "x &lt; y" in text
    assert 'href="https://e.com/?a=1&amp;b=2"' in text

    blocks = ["가" * 1500, "나" * 1500, "다" * 1500]
    messages = split_messages(blocks, limit=4000)
    assert len(messages) == 2
    assert all(len(m) <= 4000 for m in messages)
    assert messages[0].startswith("가") and messages[1].endswith("다")


def test_store_stats_and_eval_roundtrip(tmp_path):
    from briefing.cluster import cluster_articles

    from .samples import RATE

    conn = connect(str(tmp_path / "t.db"))
    cluster = cluster_articles(RATE)[0]
    briefing = Briefing("헤드라인", "경제", "요약", sources=[("연합뉴스", "u")], flags=["숫자 미확인"])
    save_run(
        conn, model="m", prompt_version="v1", n_articles=3, clusters=[cluster],
        briefings=[briefing], usage={"llm_calls": 1, "input_tokens": 1000, "output_tokens": 200},
        duration_s=1.2,
    )
    stats = usage_stats(conn)
    assert stats["runs"] == 1 and stats["input_tokens"] == 1000 and stats["flag_rate"] == 1.0

    csv_path = str(tmp_path / "eval.csv")
    assert export_eval_csv(conn, csv_path) == 1
    import csv

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))  # source_text에 줄바꿈이 있어 csv 모듈로 읽어야 한다
    header, row = rows[0], rows[1]
    assert header[-3:] == ["faithful", "coverage", "notes"]
    # 채점 전에는 집계에서 제외, 채점 후에는 버전별 평균이 나온다
    assert eval_report(csv_path) == {}
    row[-3:] = ["5", "4", ""]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows([header, row])
    assert eval_report(csv_path)["v1"] == {"n": 1, "faithful_avg": 5.0, "coverage_avg": 4.0, "faithful_ge4_rate": 1.0}
