"""配置加载：config.yaml + .env + 环境变量。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_dotenv(ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


class SchoolCfg(BaseModel):
    name: str = "云南大学滇池学院"
    short_name: str = "滇池学院"
    assistant_name: str = "滇小答"
    city: str = ""
    website: str = ""
    hotline: str = ""
    admissions_phone: str = ""
    admissions_site: str = ""
    campuses: List[str] = Field(default_factory=list)
    service_hours: str = ""


class BrandCfg(BaseModel):
    primary_color: str = "#0B4F9E"
    accent_color: str = "#F2A100"
    disclaimer: str = ""


class LLMCfg(BaseModel):
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    temperature: float = 0.2
    max_tokens: int = 1200
    timeout: float = 60.0
    stream: bool = True


class EmbeddingCfg(BaseModel):
    provider: str = "local"
    dim: int = 256
    base_url: str = ""
    model: str = ""


class RetrievalCfg(BaseModel):
    top_k: int = 5
    candidate_k: int = 12
    rrf_k: int = 60
    min_score: float = 0.18
    # 查询关键词的 IDF 加权覆盖率下限，低于此值视为"没有相关资料"
    min_coverage: float = 0.42
    chunk_size: int = 450
    chunk_overlap: int = 80
    embedding: EmbeddingCfg = Field(default_factory=EmbeddingCfg)


class ChatCfg(BaseModel):
    history_turns: int = 4
    max_question_chars: int = 800
    rate_limit_per_minute: int = 30
    session_ttl: int = 3600


class ServerCfg(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: List[str] = Field(default_factory=lambda: ["*"])


class Settings(BaseModel):
    school: SchoolCfg = Field(default_factory=SchoolCfg)
    brand: BrandCfg = Field(default_factory=BrandCfg)
    quick_questions: List[str] = Field(default_factory=list)
    llm: LLMCfg = Field(default_factory=LLMCfg)
    retrieval: RetrievalCfg = Field(default_factory=RetrievalCfg)
    chat: ChatCfg = Field(default_factory=ChatCfg)
    server: ServerCfg = Field(default_factory=ServerCfg)

    llm_api_key: str = ""
    embedding_api_key: str = ""
    admin_token: str = ""

    root: Path = ROOT
    knowledge_dir: Path = ROOT / "data" / "knowledge"
    index_dir: Path = ROOT / "data" / "index"
    db_path: Path = ROOT / "data" / "logs" / "chat.db"
    web_dir: Path = ROOT / "web"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def embedding_api_enabled(self) -> bool:
        e = self.retrieval.embedding
        return (
            e.provider.lower() == "api"
            and bool(self.embedding_api_key)
            and bool(e.base_url)
            and bool(e.model)
        )

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or (ROOT / "config.yaml")
        raw: Dict[str, Any] = {}
        if path.exists():
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                raw = loaded

        s = cls(**raw)

        if _env("LLM_BASE_URL"):
            s.llm.base_url = _env("LLM_BASE_URL")
        if _env("LLM_MODEL"):
            s.llm.model = _env("LLM_MODEL")
        if _env("EMBEDDING_PROVIDER"):
            s.retrieval.embedding.provider = _env("EMBEDDING_PROVIDER")
        if _env("EMBEDDING_BASE_URL"):
            s.retrieval.embedding.base_url = _env("EMBEDDING_BASE_URL")
        if _env("EMBEDDING_MODEL"):
            s.retrieval.embedding.model = _env("EMBEDDING_MODEL")

        s.llm_api_key = _env("LLM_API_KEY")
        # 大模型总开关：LLM_ENABLED=0 时强制走纯检索模式（不调用大模型、不消耗任何额度），
        # 适合对外演示或开放局域网访问；改回 1 或留空即恢复。
        if _env("LLM_ENABLED").lower() in ("0", "false", "no", "off"):
            s.llm_api_key = ""
        s.embedding_api_key = _env("EMBEDDING_API_KEY") or s.llm_api_key
        s.admin_token = _env("ADMIN_TOKEN", "change-me-please")
        return s


_cached: Settings | None = None


def get_settings() -> Settings:
    global _cached
    if _cached is None:
        _cached = Settings.load()
    return _cached


def reload_settings() -> Settings:
    global _cached
    _cached = Settings.load()
    return _cached
