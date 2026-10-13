from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import yaml

from .cluster import cluster_articles, rank_clusters
from .fetch import fetch_all
from .inbox import fetch_inbox
from .prompts import PROMPT_VERSION
from .store import connect, eval_report, export_eval_csv, save_run, usage_stats
from .llm import api_key_env, build_llm, resolve_llm_config
from .summarize import summarize_clusters
from .telegram import format_briefing, format_header, send_all

log = logging.getLogger("briefing")

DEFAULTS = {
    "window_hours": 24,
    "per_feed_limit": 40,
    "cluster_threshold": 0.30,
    "min_sources": 2,
    "max_clusters": 8,
    "chunk_size": 5,
    "db_path": "data/briefing.db",
    "use_inbox": True,
}


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = {**DEFAULTS, **(yaml.safe_load(f) or {})}
    cfg["llm"] = resolve_llm_config(cfg.get("llm"))
    return cfg


def _require_env(*names: str) -> list[str]:
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        sys.exit(f"환경변수가 없습니다: {', '.join(missing)} (.env 또는 Actions secrets 확인)")
    return [os.environ[n] for n in names]


def run(cfg: dict, dry_run: bool) -> None:
    started = time.time()
    token = chat_id = None
    llm_cfg = cfg["llm"]
    needed = [n for n in [api_key_env(llm_cfg)] if n]
    if not dry_run:
        needed += ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    values = _require_env(*needed) if needed else []
    if not dry_run:
        token, chat_id = values[-2], values[-1]

    articles, failed = fetch_all(cfg["feeds"], cfg["window_hours"], cfg["per_feed_limit"])
    if failed and len(failed) == len(cfg["feeds"]):
        sys.exit("모든 피드 수집에 실패했습니다. 네트워크와 피드 주소를 확인하세요.")

    if cfg["use_inbox"] and os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        try:
            articles += fetch_inbox(
                os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"], cfg["window_hours"]
            )
        except Exception as exc:  # 수집함은 선택 기능이라 실패해도 브리핑은 보낸다
            log.warning("수집함 읽기 실패: %s", exc)

    clusters_all = cluster_articles(articles, cfg["cluster_threshold"])
    clusters = rank_clusters(clusters_all, cfg["min_sources"], cfg["max_clusters"])
    log.info("기사 %d건 → 사건 %d개 → 브리핑 대상 %d개", len(articles), len(clusters_all), len(clusters))

    header = format_header()
    if not clusters:
        blocks = [header, "오늘은 여러 매체가 함께 다룬 주요 사건이 아직 없어요."]
        briefings, usage = [], {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
    else:
        briefings, usage = summarize_clusters(clusters, build_llm(llm_cfg), cfg["chunk_size"])
        blocks = [header] + [format_briefing(i, b) for i, b in enumerate(briefings, start=1)]
        if failed:
            blocks.append("수집 실패한 매체: " + ", ".join(failed))

    conn = connect(cfg["db_path"])
    save_run(
        conn,
        model="none" if llm_cfg["provider"] == "none" else llm_cfg["model"],
        prompt_version=PROMPT_VERSION,
        n_articles=len(articles),
        clusters=clusters,
        briefings=briefings,
        usage=usage,
        duration_s=time.time() - started,
    )

    if dry_run:
        print("\n\n".join(blocks))
    else:
        sent = send_all(token, chat_id, blocks)
        log.info("텔레그램 메시지 %d개 전송", sent)
    log.info("토큰 사용: 입력 %s / 출력 %s", usage["input_tokens"], usage["output_tokens"])


def check_feeds(cfg: dict) -> None:
    articles, failed = fetch_all(cfg["feeds"], window_hours=cfg["window_hours"])
    counts: dict[str, int] = {}
    for a in articles:
        counts[a.source] = counts.get(a.source, 0) + 1
    for feed in cfg["feeds"]:
        name = feed["name"]
        status = "실패" if name in failed else f"{counts.get(name, 0)}건"
        print(f"{name:<12} {status}")


def cli() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(prog="briefing", description="아침 뉴스 브리핑 텔레그램 봇")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="수집 → 요약 → 텔레그램 전송 (기본 동작)")
    p_run.add_argument("--dry-run", action="store_true", help="전송 대신 화면에 출력")
    sub.add_parser("check-feeds", help="피드별 수집 건수 확인")
    sub.add_parser("stats", help="누적 토큰 사용량과 검증 플래그 비율")
    p_exp = sub.add_parser("eval-export", help="사람이 채점할 CSV 내보내기")
    p_exp.add_argument("--out", default="data/eval.csv")
    p_exp.add_argument("--limit", type=int, default=50)
    p_rep = sub.add_parser("eval-report", help="채점된 CSV를 프롬프트 버전별로 집계")
    p_rep.add_argument("--file", default="data/eval.csv")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg = load_config(args.config)
    command = args.command or "run"

    if command == "run":
        run(cfg, dry_run=getattr(args, "dry_run", False))
    elif command == "check-feeds":
        check_feeds(cfg)
    elif command == "stats":
        print(json.dumps(usage_stats(connect(cfg["db_path"])), ensure_ascii=False, indent=2))
    elif command == "eval-export":
        n = export_eval_csv(connect(cfg["db_path"]), args.out, args.limit)
        print(f"{n}건을 {args.out}에 저장했습니다. faithful/coverage(1~5)를 채운 뒤 eval-report를 실행하세요.")
    elif command == "eval-report":
        if not Path(args.file).exists():
            sys.exit(f"파일이 없습니다: {args.file}")
        print(json.dumps(eval_report(args.file), ensure_ascii=False, indent=2))
