"""Skema Pydantic: stream, grup, scan (Fase 1)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

StorageMode = Literal["local", "drive", "both"]


class StreamOut(BaseModel):
    id: int
    name: str
    brand: str | None
    is_online: bool
    is_active: bool = True
    last_seen_at: datetime | None
    whep_main_url: str
    whep_sub_url: str | None
    poster_url: str
    latitude: float | None = None
    longitude: float | None = None
    storage_mode: str = "local"
    drive_account_id: uuid.UUID | None = None
    recording_enabled: bool = False
    retention_days: int = 7
    # Kredensial RTSP: hanya diisi endpoint admin (sudah di-masking per v2.0).
    rtsp_url: str | None = None
    drive_folder_id: int | None = None


class StreamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    brand: str | None = None
    rtsp_url: str | None = None
    onvif: dict | None = None  # TODO Fase 2: teruskan profile token ke resolver
    user: str | None = None
    password: str | None = None
    host: str | None = None
    port: int = Field(default=554, ge=1, le=65535)
    channel: int = Field(default=1, ge=1)
    storage_mode: StorageMode = "local"
    recording_enabled: bool = False
    retention_days: int = Field(default=7, ge=1, le=365)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class StreamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    is_active: bool | None = None
    storage_mode: StorageMode | None = None
    drive_account_id: uuid.UUID | None = None  # null eksplisit = kembali ke default
    drive_folder_id: int | None = None  # folder Drive tujuan (multi-tautan); null = default
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    recording_enabled: bool | None = None
    retention_days: int | None = Field(default=None, ge=1, le=365)


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)


class GroupOut(BaseModel):
    id: int
    name: str
    description: str | None


class ScanRequest(BaseModel):
    brand: str | None = None  # None / "auto" = coba semua brand umum
    host: str | None = Field(default=None, min_length=1)
    rtsp_url: str | None = None  # mode URL RTSP langsung (tanpa host)
    user: str | None = None
    password: str | None = None
    port: int = Field(default=554, ge=1, le=65535)
    channel: int = Field(default=1, ge=1)
    probe: bool = True  # tes koneksi RTSP tiap kandidat via DESCRIBE


class ScanCandidate(BaseModel):
    main_url: str
    sub_url: str | None
    brand: str
    method: str  # explicit | onvif | brand | generic
    main_ok: bool | None = None   # hasil probe RTSP (None = tidak di-probe)
    sub_ok: bool | None = None
    probe_status: str | None = None


class ScanResult(BaseModel):
    candidates: list[ScanCandidate]


class UserIdsIn(BaseModel):
    user_ids: list[int]


class StreamIdsIn(BaseModel):
    stream_ids: list[int]


class OwnerIn(BaseModel):
    user_id: int


class PreviewIn(BaseModel):
    rtsp_url: str = Field(min_length=1)
