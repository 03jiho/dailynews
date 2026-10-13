"""테스트용 가상 기사 (실제 기사 아님)."""
from briefing.models import Article


def art(source: str, title: str, summary: str = "", link: str | None = None) -> Article:
    return Article(source=source, title=title, summary=summary, link=link or f"https://example.com/{source}/{abs(hash(title))}")


RATE = [
    art("연합뉴스", "한국은행 기준금리 연 2.50%로 동결", "한국은행 금융통화위원회는 기준금리를 연 2.50%로 유지하기로 결정했다."),
    art("한겨레", "한은, 기준금리 2.50% 동결…가계부채·환율 부담", "금융통화위원회가 기준금리를 연 2.50%로 동결했다. 가계부채와 환율 변동성을 고려한 결정이다."),
    art("매일경제", "금통위 기준금리 동결…연 2.50% 유지", "한국은행 금융통화위원회가 기준금리를 동결하며 연 2.50% 수준을 유지했다."),
]

BUDGET = [
    art("동아일보", "여야, 내년도 예산안 처리 놓고 공방", "예산안 처리 시한을 앞두고 여야가 증액 규모를 두고 맞섰다."),
    art("경향신문", "예산안 처리 시한 앞두고 여야 대립 격화", "내년도 예산안 증액 규모를 두고 여야가 공방을 벌였다."),
]

FESTIVAL = [
    art("조선일보", "부산 해운대 불꽃축제 주말 개최, 교통 통제 예정", "주말 해운대 일대에서 불꽃축제가 열려 교통이 통제된다."),
]

ALL = RATE + BUDGET + FESTIVAL
