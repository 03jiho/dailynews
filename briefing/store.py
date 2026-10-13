"""SQLite에 실행 기록과 요약 결과를 남긴다. 비용 추적과 프롬프트 버전별 품질 비교에 쓴다."""
from __future__ import annotations

import csv
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .models import Briefing, Cluster

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    n_articles INTEGER NOT NULL,
    n_clusters INTEGER NOT NULL,
    n_briefed INTEGER NOT NULL,
    n_flagged INTEGER NOT NULL,
    llm_calls INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    duration_s REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    prompt_version TEXT NOT NULL,
    headline TEXT NOT NULL,
    category TEXT NOT NULL,
    summary TEXT NOT NULL,
    differences TEXT,
    source_text TEXT NOT NULL,
    flags_json TEXT NOT NULL,
    llm_ok INTEGER NOT NULL
);
"""

EVAL_COLUMNS = ["id", "prompt_version", "headline", "summary", "differences", "source_text", "faithful", "coverage", "notes"]


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def save_run(
    conn: sqlite3.Connection,
    *,
    model: str,
    prompt_version: str,
    n_articles: int,
    clusters: list[Cluster],
    briefings: list[Briefing],
    usage: dict,
    duration_s: float,
) -> int:
    cur = conn.execute(
        "INSERT INTO runs (run_at, model, prompt_version, n_articles, n_clusters, n_briefed,"
        " n_flagged, llm_calls, input_tokens, output_tokens, duration_s)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            model,
            prompt_version,
            n_articles,
            len(clusters),
            len(briefings),
            sum(1 for b in briefings if b.flags),
            usage.get("llm_calls", 0),
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
            round(duration_s, 2),
        ),
    )
    run_id = cur.lastrowid
    for cluster, b in zip(clusters, briefings):
        source_text = "\n".join(f"[{a.source}] {a.text}" for a in cluster.articles)
        conn.execute(
            "INSERT INTO summaries (run_id, prompt_version, headline, category, summary,"
            " differences, source_text, flags_json, llm_ok) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                prompt_version,
                b.headline,
                b.category,
                b.summary,
                b.differences,
                source_text,
                json.dumps(b.flags, ensure_ascii=False),
                int(b.llm_ok),
            ),
        )
    conn.commit()
    return run_id


def usage_stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0),"
        " COALESCE(SUM(n_briefed),0), COALESCE(SUM(n_flagged),0), COALESCE(AVG(duration_s),0)"
        " FROM runs"
    ).fetchone()
    runs, tin, tout, briefed, flagged, avg_dur = row
    return {
        "runs": runs,
        "input_tokens": tin,
        "output_tokens": tout,
        "avg_input_tokens_per_run": round(tin / runs) if runs else 0,
        "avg_output_tokens_per_run": round(tout / runs) if runs else 0,
        "briefings": briefed,
        "flagged_briefings": flagged,
        "flag_rate": round(flagged / briefed, 3) if briefed else 0.0,
        "avg_duration_s": round(avg_dur, 1),
    }


def export_eval_csv(conn: sqlite3.Connection, path: str, limit: int = 50) -> int:
    """사람이 채점할 CSV를 만든다. faithful/coverage 칸(1~5)을 직접 채우면 된다."""
    rows = conn.execute(
        "SELECT id, prompt_version, headline, summary, differences, source_text"
        " FROM summaries WHERE llm_ok = 1 ORDER BY RANDOM() LIMIT ?",
        (limit,),
    ).fetchall()
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(EVAL_COLUMNS)
        for r in rows:
            writer.writerow([*r, "", "", ""])
    return len(rows)


def eval_report(path: str) -> dict[str, dict]:
    """채점된 CSV를 프롬프트 버전별로 집계한다."""
    buckets: dict[str, list[tuple[int, int]]] = defaultdict(list)
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                faithful, coverage = int(row["faithful"]), int(row["coverage"])
            except (ValueError, TypeError):
                continue  # 아직 채점하지 않은 행
            buckets[row["prompt_version"]].append((faithful, coverage))

    report = {}
    for version, scores in buckets.items():
        n = len(scores)
        report[version] = {
            "n": n,
            "faithful_avg": round(sum(s[0] for s in scores) / n, 2),
            "coverage_avg": round(sum(s[1] for s in scores) / n, 2),
            "faithful_ge4_rate": round(sum(1 for s in scores if s[0] >= 4) / n, 2),
        }
    return report
