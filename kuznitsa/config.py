from dataclasses import dataclass, field
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
WEIGHTS = dict(rel=.50, pop=.20, margin=.15, pers=.15)


def path(name, default):
    return field(default_factory=lambda: Path(os.getenv(name, ROOT / default)))


@dataclass
class Config:
    data: Path = path("KZ_DATA_DIR", "var/data")
    kb: Path = path("KZ_KB_DIR", "kb")
    models: Path = path("KZ_MODEL_DIR", "var/models")
    cache: Path = path("KZ_CACHE_DIR", "var/cache")
    embed: str = field(default_factory=lambda: os.getenv("KZ_EMBED_MODEL", MODEL))
    mode: str = field(default_factory=lambda: os.getenv("KZ_DEFAULT_MODE", "smart"))
    rate_limit: int = field(default_factory=lambda: int(os.getenv("KZ_RATE_LIMIT", "120")))
    jev_model: str = field(default_factory=lambda: os.getenv("KZ_JEV_MODEL","typesafe/jev-1.13"))
    jev_url: str = field(default_factory=lambda: os.getenv("KZ_JEV_URL","https://openrouter.ai/api/alpha/decisions"))
