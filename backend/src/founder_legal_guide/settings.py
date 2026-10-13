"""Runtime settings, read from the environment (see .env.example at the repo root)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    app_title: str = "Founder Legal Guide"
    app_url: str = "http://localhost:3000"

    database_url: str = "postgresql://flg:flg@localhost:5432/flg"
    qdrant_url: str = "http://localhost:6333"
    chroma_host: str = "localhost"
    chroma_port: int = 8001

    config_dir: Path = REPO_ROOT / "config"
    admin_token: str = ""
    # Cron expression for the daily update run, e.g. "0 3 * * *". Empty: no schedule.
    update_cron: str = ""
    cors_origins: list[str] = ["http://localhost:3000"]

    # Runs without OpenRouter: no language model, sample Corpus in memory (see demo.py).
    demo_mode: bool = False

    max_question_chars: int = 2000
    # Questions per client per window; 0 switches the limit off.
    rate_limit_requests: int = 20
    rate_limit_window_seconds: int = 600
    agentic_max_searches: int = 4


@lru_cache
def get_settings() -> Settings:
    return Settings()
