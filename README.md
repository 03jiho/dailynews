# 아침 뉴스 브리핑 봇

매일 아침 7시, 여러 언론사 기사를 모아 **같은 사건끼리 묶고**, LLM으로 요약해서 **텔레그램**으로 보내주는 봇입니다.
단순 요약이 아니라 "이 요약을 믿어도 되는가"를 코드로 검증하는 데 초점을 맞췄습니다.

## 동작 흐름

```
RSS(여러 언론사) ─┐
                  ├─► 24시간 필터·중복 제거 ─► 사건별 클러스터링 ─► 상위 N개 선택
내 수집함(텔레그램)┘                                                     │
                                                                          ▼
            텔레그램 전송 ◄─ 기계적 검증(근거 인용·숫자) ◄─ LLM 요약 (JSON)
                                         │
                                         ▼
                          SQLite 기록 (토큰·플래그·요약 → 평가용 CSV)
```

| 단계 | 파일 | 핵심 |
|---|---|---|
| 수집 | `fetch.py` | RSS 파싱, 매체 하나가 죽어도 계속 진행 |
| 수집함 | `inbox.py` | 봇 채팅에 보낸 메시지(인스타 소식 등)를 기사로 취급 |
| 클러스터링 | `cluster.py` | 글자 n-gram TF-IDF, 추가 API 비용 0원 |
| 요약 | `summarize.py`, `prompts.py` | 5개 사건씩 1회 호출, JSON 파싱 실패 시 재시도 후 제목만 표시 |
| 검증 | `verify.py` | 근거 인용이 원문에 글자 그대로 있는지, 요약 속 숫자가 원문에 있는지 |
| 전송 | `telegram.py` | HTML 이스케이프, 4000자 단위 분할 |
| 기록 | `store.py` | 토큰 사용량, 검증 플래그 비율, 프롬프트 버전별 품질 비교 |

## 시작하기

### 1. 키 준비
- **Gemini API 키 (무료)**: Google AI Studio(aistudio.google.com)에서 발급. 기본 설정이 Gemini 무료 티어입니다. (아래 "무료로 쓰기" 참고)
- **텔레그램 봇**: 텔레그램에서 `@BotFather` → `/newbot` → 토큰 받기
- **채팅 ID**: 만든 봇에게 아무 메시지나 보낸 뒤, 브라우저에서
  `https://api.telegram.org/bot<토큰>/getUpdates` 를 열어 `"chat":{"id": 숫자}` 의 숫자를 확인

### 2. 로컬 실행
```bash
pip install -r requirements.txt
cp .env.example .env        # GEMINI_API_KEY, 텔레그램 토큰·채팅 ID 채우기
python -m briefing check-feeds   # 피드가 수집되는지 확인 (실패한 매체는 config.yaml에서 주소 수정/삭제)
python -m briefing run --dry-run # 텔레그램 전송 없이 결과를 화면에 출력
python -m briefing run           # 실제 전송
```

### 3. 매일 자동 실행 (GitHub Actions)
1. 이 폴더를 GitHub 저장소로 올리기
2. Settings → Secrets and variables → Actions에 `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 등록
3. Actions 탭에서 `morning-briefing`을 **Run workflow**로 한 번 수동 실행해 확인
4. 이후 매일 한국시간 7시경 자동 실행 (GitHub 사정으로 몇 분~수십 분 늦을 수 있어요)

## 무료로 쓰기

`config.yaml`의 `llm` 항목으로 요약 엔진을 고릅니다.

| 선택 | 비용 | 설정 |
|---|---|---|
| **Gemini 무료 티어 (기본)** | 무료 | `GEMINI_API_KEY`만 넣으면 됨. 모델은 `gemini-3.8-flash` |
| **LLM 없이** | 완전 무료, 키 불필요 | `provider: none`. 요약 대신 사건별로 매체마다의 제목을 나란히 보여줌 |
| Groq 등 OpenAI 호환 서비스 | 서비스별 무료 한도 | `base_url`, `api_key_env`, `model`만 바꾸면 됨 |
| 내 PC의 Ollama | 무료 | `base_url: http://localhost:11434/v1` (내 PC에서 직접 실행할 때만) |
| Claude API | 유료 | `provider: anthropic`, `pip install anthropic` |

알아둘 점:
- 무료 티어는 Google이 입력 내용을 서비스 개선에 쓸 수 있습니다 (2026년 10월 공식 가격표 기준). 공개 뉴스는 괜찮지만, **수집함에 보낸 개인적인 내용**이 걱정되면 `use_inbox: false`로 끄거나 `provider: none`을 쓰세요.
- 무료 한도와 제공 모델은 자주 바뀝니다. 요청이 거절되면 [Gemini 가격 페이지](https://ai.google.dev/gemini-api/docs/pricing)에서 현재 무료 모델을 확인하고 `model`을 바꾸세요.
- 분당 한도에 걸리면(429) 자동으로 기다렸다 재시도합니다. 그래도 자주 걸리면 `chunk_size`를 줄이세요.
- GitHub Actions는 하루 1분 안팎이라 개인 계정의 무료 사용량 안에서 충분합니다.
- 작은 모델은 JSON 형식이나 원문 그대로 인용하는 규칙을 가끔 어깁니다. 이럴 때는 검증 단계가 `⚠️`로 표시해 주고, 심하면 제목만 보여주는 방식으로 대체됩니다.

## 인스타·SNS 소식 넣기 ("내 수집함")

인스타그램 게시물은 공식 API로 자동 수집할 수 없고, 비공식 스크래핑은 약관 위반이라 계정 차단 위험이 큽니다.
대신 **본 소식을 봇 채팅에 공유**하면 다음 브리핑에 포함됩니다.

- 캡션이나 본문을 **복사해서** 보내고 링크를 같이 붙이세요. (링크만 보내면 읽을 내용이 없어 제외됩니다)
- 이미지(카드뉴스)만 보내면 글자를 읽지 못해 제외됩니다. 캡션이 있으면 캡션을 사용합니다.
- 수집함 항목은 언론사 1곳뿐인 단독 소식이어도 브리핑에 들어가고, 같은 사건을 다룬 기사가 있으면 자동으로 묶입니다.
- 텔레그램은 최근 24시간 메시지만 보관하므로, 하루 단위 브리핑과 잘 맞습니다.

## 검증 방식 (이 프로젝트의 핵심)

LLM이 틀렸는지 LLM에게 다시 묻지 않고 **코드로** 확인합니다.

1. 요약마다 근거 문장(`evidence`)을 원문에서 그대로 복사하게 하고, 실제로 그 기사에 있는 문장인지 문자열로 대조합니다. 불일치하면 제외하고 `⚠️`로 표시합니다.
2. 요약에 나온 숫자가 원문 어디에도 없으면 `⚠️ 원문에서 확인되지 않은 숫자`로 표시합니다.
3. 검증에 실패해도 요약을 버리지 않고 **표시**해서, 읽는 사람이 판단할 수 있게 합니다.

## 품질·비용 측정

```bash
python -m briefing stats          # 누적 토큰, 실행당 평균 토큰, 검증 플래그 비율
python -m briefing eval-export    # 무작위 50건을 data/eval.csv로 내보내기
#  → CSV의 faithful(원문 충실도 1~5), coverage(핵심 포함도 1~5)를 직접 채점
python -m briefing eval-report    # 프롬프트 버전별 평균 점수
```

프롬프트를 고칠 때는 `prompts.py`의 `PROMPT_VERSION`을 올리세요. 그러면 버전별로 점수가 따로 집계돼서
"v1 → v2에서 충실도가 얼마나 올랐다"를 숫자로 보여줄 수 있습니다. (포트폴리오에는 직접 측정한 수치만 쓰세요.)

## 설정과 튜닝

`config.yaml`에서 조정합니다.
- `cluster_threshold`: 서로 다른 사건이 한 덩어리가 되면 올리고, 같은 사건이 갈라지면 내리세요 (기본 0.30).
- `min_sources`: 몇 개 매체가 다룬 사건만 보낼지.
- `llm.model`: 요약 품질이 아쉬우면 더 큰 모델로 바꿔 보세요 (무료 한도 안에서).

## 한계

- 요약은 RSS의 제목과 요약문 기반입니다. 기사 본문 전체를 읽지 않습니다 (저작권과 비용 때문).
- 클러스터링은 글자 겹침 기반이라, 표현이 완전히 다른 같은 사건은 못 묶을 수 있습니다. 필요하면 임베딩으로 교체하세요 (`cluster.py`만 바꾸면 됩니다).
- 검증은 "원문과 일치하는가"를 보는 것이지, 원문 자체가 맞는지는 판단하지 않습니다.
- RSS 주소는 언론사 사정으로 바뀔 수 있습니다. 제작 환경에서는 실제 언론사 사이트에 접속할 수 없어 `check-feeds`로 주소를 직접 확인하지 못했습니다. 처음 실행할 때 꼭 확인하세요.

## 테스트

```bash
pip install -r requirements-dev.txt
pytest
```
