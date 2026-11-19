"""Skema Pydantic: diagnostik tambah kamera (admin)."""

from datetime import datetime

from pydantic import BaseModel


class CameraFailureOut(BaseModel):
    """Satu penyebab kegagalan yang bisa dibaca + langkah perbaikan."""

    code: str
    judul: str
    penyebab: str
    langkah: list[str] = []


class MediamtxStatusOut(BaseModel):
    api_url: str
    reachable: bool
    status: str  # ok | redirect | auth | unreachable | error
    status_code: int | None = None
    version: str | None = None
    failure: CameraFailureOut | None = None


class PathStatusOut(BaseModel):
    stream_id: int
    name: str
    path: str
    terdaftar: bool


class ProbeRowOut(BaseModel):
    stream_id: int
    name: str
    main_status: str | None = None  # None = belum pernah diprobe
    sub_status: str | None = None
    checked_at: datetime | None = None


class FailureRowOut(BaseModel):
    id: int
    stream_id: int | None
    camera_name: str
    code: str
    judul: str
    penyebab: str
    langkah: list[str] = []
    created_at: datetime


class DiagnosticsOut(BaseModel):
    mediamtx: MediamtxStatusOut
    paths_total: int
    paths_terdaftar: int
    paths_hilang: list[PathStatusOut] = []
    rtsp: list[ProbeRowOut] = []
    riwayat: list[FailureRowOut] = []


class ProbeRequest(BaseModel):
    stream_id: int


class ProbeRoleOut(BaseModel):
    status: str
    failure: CameraFailureOut | None = None


class ProbeOut(BaseModel):
    stream_id: int
    name: str
    main: ProbeRoleOut
    sub: ProbeRoleOut | None = None
