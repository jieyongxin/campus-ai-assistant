"""内存会话存储：多轮上下文 + TTL 清理。"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Dict, List, Optional


class SessionStore:
    def __init__(self, ttl: int = 3600, max_turns: int = 20):
        self.ttl = ttl
        self.max_turns = max_turns
        self._data: Dict[str, Dict] = {}
        self._lock = threading.Lock()

    def _gc(self) -> None:
        now = time.time()
        dead = [k for k, v in self._data.items() if now - v["touched"] > self.ttl]
        for k in dead:
            self._data.pop(k, None)

    def ensure(self, session_id: Optional[str]) -> str:
        with self._lock:
            self._gc()
            sid = (session_id or "").strip() or uuid.uuid4().hex
            entry = self._data.get(sid)
            if entry is None:
                self._data[sid] = {"touched": time.time(), "history": []}
            else:
                entry["touched"] = time.time()
            return sid

    def history(self, session_id: str) -> List[Dict[str, str]]:
        with self._lock:
            entry = self._data.get(session_id)
            return list(entry["history"]) if entry else []

    def append(self, session_id: str, user: str, assistant: str) -> None:
        with self._lock:
            entry = self._data.setdefault(
                session_id, {"touched": time.time(), "history": []}
            )
            entry["touched"] = time.time()
            entry["history"].extend(
                [
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": assistant},
                ]
            )
            if len(entry["history"]) > self.max_turns * 2:
                entry["history"] = entry["history"][-self.max_turns * 2 :]

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._data.pop(session_id, None)

    @property
    def active(self) -> int:
        with self._lock:
            return len(self._data)
