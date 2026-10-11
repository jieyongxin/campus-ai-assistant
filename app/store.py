"""SQLite 日志：问答记录、反馈、统计。"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional


class LogStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS answers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    session_id TEXT,
                    question TEXT,
                    answer TEXT,
                    mode TEXT,
                    top_score REAL,
                    sources TEXT,
                    latency_ms INTEGER,
                    client TEXT
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    session_id TEXT,
                    question TEXT,
                    answer TEXT,
                    rating TEXT,
                    comment TEXT
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_answers_ts ON answers(ts)")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def log_answer(
        self,
        session_id: str,
        question: str,
        answer: str,
        mode: str,
        sources: List[Dict],
        latency_ms: int,
        client: str = "",
    ) -> None:
        top = sources[0]["score"] if sources else 0.0
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO answers (ts, session_id, question, answer, mode, top_score,"
                " sources, latency_ms, client) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    self._now(),
                    session_id,
                    question[:1000],
                    answer[:4000],
                    mode,
                    float(top),
                    json.dumps(sources, ensure_ascii=False)[:4000],
                    int(latency_ms),
                    client[:200],
                ),
            )

    def log_feedback(
        self,
        session_id: str,
        question: str,
        answer: str,
        rating: str,
        comment: str = "",
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO feedback (ts, session_id, question, answer, rating, comment)"
                " VALUES (?,?,?,?,?,?)",
                (
                    self._now(),
                    session_id,
                    question[:1000],
                    answer[:4000],
                    rating,
                    comment[:1000],
                ),
            )

    def summary(self, days: int = 7) -> Dict:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        with self._lock:
            total = self._conn.execute(
                "SELECT COUNT(*) c FROM answers WHERE ts >= ?", (since,)
            ).fetchone()["c"]
            modes = {
                r["mode"]: r["c"]
                for r in self._conn.execute(
                    "SELECT mode, COUNT(*) c FROM answers WHERE ts >= ? GROUP BY mode", (since,)
                )
            }
            avg_latency = self._conn.execute(
                "SELECT AVG(latency_ms) a FROM answers WHERE ts >= ?", (since,)
            ).fetchone()["a"]
            feedback = {
                r["rating"]: r["c"]
                for r in self._conn.execute(
                    "SELECT rating, COUNT(*) c FROM feedback WHERE ts >= ? GROUP BY rating",
                    (since,),
                )
            }
        return {
            "days": days,
            "questions": total,
            "modes": modes,
            "avg_latency_ms": round(avg_latency or 0, 1),
            "feedback": feedback,
            "hit_rate": round(
                (modes.get("rag", 0) + modes.get("retrieval", 0)) / total, 4
            )
            if total
            else 0.0,
        }

    def top_questions(self, days: int = 7, limit: int = 30) -> List[Dict]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        with self._lock:
            rows = self._conn.execute(
                "SELECT question, COUNT(*) c, MAX(mode) mode FROM answers WHERE ts >= ?"
                " GROUP BY question ORDER BY c DESC LIMIT ?",
                (since, limit),
            ).fetchall()
        return [{"question": r["question"], "count": r["c"], "mode": r["mode"]} for r in rows]

    def misses(self, days: int = 7, limit: int = 50) -> List[Dict]:
        """没有命中的问题，是补充知识库的清单。"""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, question FROM answers WHERE ts >= ? AND mode IN ('no_hit','llm_error')"
                " ORDER BY id DESC LIMIT ?",
                (since, limit),
            ).fetchall()
        return [{"ts": r["ts"], "question": r["question"]} for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
