"""Konfigurasi aplikasi dari environment (pydantic-settings).

Tanpa nilai rahasia di repo — lihat .env.example.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "NetraVision API"
    app_env: str = "dev"  # dev | prod
    app_version: str = "3.0.0a0"

    database_url: str = (
        "postgresql+asyncpg://netravision:netravision@127.0.0.1:5432/netravision"
    )

    jwt_secret: str = "CHANGE-ME-IN-PROD"
    jwt_algorithm: str = "HS256"
    jwt_access_minutes: int = 15
    jwt_refresh_days: int = 7

    guest_enabled: bool = False
    guest_password: str = ""

    mediamtx_api_url: str = "http://127.0.0.1:9997"
    mediamtx_whep_base: str = "http://127.0.0.1:8889"

    # Basis URL publik untuk WHEP (relatif; Apache mem-proxy /whep/ -> MediaMTX).
    public_whep_base: str = "/whep"

    posters_dir: str = "data/posters"
    recordings_dir: str = "data/recordings"

    cors_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
