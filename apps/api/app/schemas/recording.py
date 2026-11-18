"""Skema recordings, cerminan packages/contracts/openapi.yaml."""

from datetime import datetime

from pydantic import BaseModel, Field


class TimelineEntry(BaseModel):
    # datetime (bukan str bebas): di JSON tetap string ISO date-time,
    # sesuai kontrak openapi.yaml (`format: date-time`) dan tipe TS
    # frontend (`start: string`), jadi format kabel tidak berubah -
    # hanya divalidasi sebagai datetime.
    start: datetime
    end: datetime
    has_event: bool = False


class TimelineOut(BaseModel):
    date: str
    # Batas selaras paginasi endpoint timeline (limit maks 500).
    entries: list[TimelineEntry] = Field(max_length=500)
    events: list[dict] = Field(default=[], max_length=1000)  # diisi modul AI (Fase 6)


class SegmentOut(BaseModel):
    start: str
    end: str
    duration_sec: int
    size_bytes: int
    url: str


class DatesOut(BaseModel):
    dates: list[str] = Field(max_length=3660)


class PlaybackUrlOut(BaseModel):
    url: str
    expires_at: None = None


class NextPlayableOut(BaseModel):
    available: bool
    time: str | None = None
