"""Skema recordings — cerminan packages/contracts/openapi.yaml."""

from pydantic import BaseModel


class TimelineEntry(BaseModel):
    start: str
    end: str
    has_event: bool = False


class TimelineOut(BaseModel):
    date: str
    entries: list[TimelineEntry]
    events: list[dict] = []  # diisi modul AI (Fase 6)


class SegmentOut(BaseModel):
    start: str
    end: str
    duration_sec: int
    size_bytes: int
    url: str


class DatesOut(BaseModel):
    dates: list[str]


class PlaybackUrlOut(BaseModel):
    url: str
    expires_at: None = None


class NextPlayableOut(BaseModel):
    available: bool
    time: str | None = None
