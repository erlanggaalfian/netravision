"""Skema auth: login, refresh, guest, token."""

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=1)


class GuestIn(BaseModel):
    """Body kosong — guest login tanpa password/autentikasi (2026-11-06)."""


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int  # detik, umur access token
