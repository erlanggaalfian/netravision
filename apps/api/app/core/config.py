"""Konfigurasi aplikasi dari environment (pydantic-settings).

Tanpa nilai rahasia di repo, lihat .env.example.
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

    mediamtx_api_url: str = "http://127.0.0.1:9997"
    mediamtx_whep_base: str = "http://127.0.0.1:8889"

    # Basis URL publik untuk WHEP (relatif; Apache mem-proxy /whep/ -> MediaMTX).
    public_whep_base: str = "/whep"

    # Basis URL publik absolut (mis. https://netra.mamura.net.id).
    # Dipakai membangun URL embed untuk pihak ketiga; bila kosong,
    # diturunkan dari request yang masuk.
    public_base_url: str = ""

    posters_dir: str = "data/posters"
    # Jalur rekaman HARUS sama dengan yang ditulis MediaMTX. Di deploy Docker
    # di-override compose (RECORDINGS_DIR=/recordings, volume recordings);
    # default relatif ini hanya untuk jalan native (CWD = apps/api).
    recordings_dir: str = "data/recordings"

    # Worker poster (ffmpeg). Mati otomatis bila ffmpeg tak ada (warning sekali).
    posters_enabled: bool = True
    poster_interval_sec: int = 60

    # Retensi lokal harian (per stream: retention_days di DB).
    retention_enabled: bool = True

    # Google Drive, MODUL OPSIONAL, default nonaktif.
    drive_enabled: bool = False
    drive_credentials_file: str = "data/drive/credentials.json"
    drive_token_file: str = "data/drive/token.json"
    drive_folder_root: str = "NetraVision"
    drive_retention_days: int = 30
    # Kunci Fernet untuk mengenkripsi token OAuth akun Drive di DB.
    # Generate: lihat docs/GOOGLE-DRIVE.md §5.
    drive_token_key: str = ""

    # Mode folder-link + rclone (ala fieriindra): folder penampung lokal
    # yang di-mount ke Google Drive via `rclone mount`. Background mirror
    # copier menyalin segmen stabil ke sini untuk kamera dengan
    # storage_mode "both". Kosong = mode ini nonaktif.
    gdrive_record_path: str = ""
    # Mirror staging: bila True, staging lokal hanya ditulis bila path-nya
    # mount rclone yang masih hidup (atau berisi sentinel .netravision-mount-ok).
    # False = izinkan direktori lokal biasa (dev/test saja).
    drive_mirror_require_mount: bool = True
    # Kuota tampilan untuk entri Google Drive di /api/admin/disks (TB).
    gdrive_quota_tb: float = 5.0

    cors_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
