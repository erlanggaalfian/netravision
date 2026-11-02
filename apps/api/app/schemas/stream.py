"""Skema Pydantic: stream, grup, scan (Fase 1)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

StorageMode = Literal["local", "drive", "both"]


class StreamOut(BaseModel):
    id: int
    name: str
    brand: str | None
    is_online: bool
    last_seen_at: datetime | None
    whep_main_url: str
    whep_sub_url: str | None
    poster_url: str
    latitude: float | None = None
    longitude: float | None = None


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


class StreamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    is_active: bool | None = None
    storage_mode: StorageMode | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)


class GroupOut(BaseModel):
    id: int
    name: str
    description: str | None


class ScanRequest(BaseModel):
    brand: str | None = None  # None / "auto" = coba semua brand umum
    host: str = Field(min_length=1)
    user: str | None = None
    password: str | None = None
    port: int = Field(default=554, ge=1, le=65535)
    channel: int = Field(default=1, ge=1)


class ScanCandidate(BaseModel):
    main_url: str
    sub_url: str | None
    brand: str
    method: str  # explicit | onvif | brand | generic


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
