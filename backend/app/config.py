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
    VIDEOS_DIR: str = "/data/videos"              # uploaded videos for file sources (shared data volume)
    VIDEOS_SOURCE_PREFIX: str = "/data/videos"    # the same folder as the inference container sees it
    VIDEO_MAX_MB: int = 2048                      # per video
    VIDEO_MIN_FREE_MB: int = 4096                 # never fill the SD card: keep this much free after an upload
    # Face recognition (ArcFace R50 cosine similarity of L2-normalized embeddings)
    FACE_MATCH_THRESHOLD: float = 0.45            # same person at or above this
    FACE_NEW_PERSON_MIN_PX: int = 48              # an unmatched face starts a new person only if this wide (source px)
    FACE_NEW_PERSON_MIN_SCORE: float = 0.6        # ... and the landmark detector is this confident
    FACE_MAX_ANCHORS: int = 30                    # reference faces kept per person
    FACE_SERVICE_URL: str = "http://face:8095"    # face service: embeddings of registration photos (internal)

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
