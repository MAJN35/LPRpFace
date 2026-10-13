"""Backend settings from the environment (see deploy/.env.example)."""
from __future__ import annotations

from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=True, extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://lpr:lpr@db:5432/lpr"
    SECRET_KEY: str = "change-me"                 # JWT signing key; must be set in deployment
    ACCESS_TOKEN_MINUTES: int = 480
    AUTH_ENABLED: bool = True                     # A.7: authentication when exposed beyond a trusted LAN
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = ""                      # bootstrap admin on first start (empty = no bootstrap)
    INGEST_KEY: str = ""                          # shared secret for the consumer's ingest endpoint
    CORS_ORIGINS: str = ""                        # comma list; empty = same-origin only
    INFERENCE_URL: str = "http://deepstream:8090" # DeepStream control API (internal network)
    CROPS_DIR: str = "/data/crops"
    RETENTION_DAYS: int = 30                      # events + crops older than this are deleted
    RETENTION_INTERVAL_S: int = 3600
    MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
