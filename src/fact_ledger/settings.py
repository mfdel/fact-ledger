"""Runtime configuration. Read from environment variables with the FACT_LEDGER_ prefix."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FACT_LEDGER_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "sqlite:///./data/fact_ledger.db"
    log_level: str = "INFO"
    dictionary_dir: Path = Path("data/dictionary")
    llm_model: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
