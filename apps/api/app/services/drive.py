"""Uploader Google Drive (MODUL OPSIONAL, default NONAKTIF).

Desain (§3.8 blueprint):
- Auth OAuth2 akun Google milik user (setup sekali; lihat docs/GOOGLE-DRIVE.md).
- Segmen SELALU ditulis lokal dulu; uploader async memindahkan salinan ke Drive.
- Struktur folder: NetraVision/<nama-kamera>/<nama-file-segmen>.
- Retry 3x per file; gagal = tetap aman di lokal, dicoba lagi putaran berikut.
- Playback segmen Drive di-proxy backend via download parsial (Range).

Import google-api dilakukan LAZY di dalam method agar modul ini bisa
diimpor tanpa dependensi drive terinstal (dependensi = extras "drive").
Untuk test, service Drive bisa di-inject via konstruktor.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

log = logging.getLogger("netravision.drive")

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
FOLDER_MIME = "application/vnd.google-apps.folder"
CHUNK = 1024 * 1024  # 1 MB per potongan unduh proxy


class DriveUploader:
    def __init__(self, settings=None, service=None):
        from app.core.config import get_settings

        self.settings = settings or get_settings()
        self._service = service  # di-inject pada test
        self._queue: asyncio.Queue = asyncio.Queue()
        self._folder_cache: dict[str, str] = {}

    # ---------- koneksi ----------

    def _build_service(self):
        """Bangun client Drive dari token.json (refresh otomatis bila perlu)."""
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as e:
            raise RuntimeError(
                "dependensi drive belum terinstal "
                "(pip install netravision-api[drive])"
            ) from e

        s = self.settings
        token_file = s.drive_token_file
        if not os.path.exists(token_file):
            raise RuntimeError(
                f"{token_file} belum ada — ikuti docs/GOOGLE-DRIVE.md untuk setup OAuth2"
            )
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(token_file, "w") as f:
                    f.write(creds.to_json())
            else:
                raise RuntimeError(
                    "token Drive tidak valid dan tak bisa di-refresh — "
                    "ulangi setup docs/GOOGLE-DRIVE.md"
                )
        return build("drive", "v3", credentials=creds)

    async def _svc(self):
        if self._service is None:
            self._service = await asyncio.to_thread(self._build_service)
        return self._service

    # ---------- folder ----------

    async def ensure_folder(self, stream_name: str) -> str:
        """Kembalikan id folder NetraVision/<stream_name> (buat bila belum ada)."""
        if stream_name in self._folder_cache:
            return self._folder_cache[stream_name]
        svc = await self._svc()
        root_id = await self._ensure_child(svc, None, self.settings.drive_folder_root)
        folder_id = await self._ensure_child(svc, root_id, stream_name)
        self._folder_cache[stream_name] = folder_id
        return folder_id

    async def _ensure_child(
        self, svc, parent_id: str | None, name: str
    ) -> str:
        def _find():
            q = (
                f"name='{name}' and mimeType='{FOLDER_MIME}' and trashed=false"
            )
            if parent_id:
                q += f" and '{parent_id}' in parents"
            res = (
                svc.files()
                .list(q=q, fields="files(id)", pageSize=1)
                .execute()
            )
            files = res.get("files", [])
            return files[0]["id"] if files else None

        found = await asyncio.to_thread(_find)
        if found:
            return found

        def _create():
            body: dict = {"name": name, "mimeType": FOLDER_MIME}
            if parent_id:
                body["parents"] = [parent_id]
            return (
                svc.files().create(body=body, fields="id").execute()["id"]
            )

        return await asyncio.to_thread(_create)

    async def find_file(self, folder_id: str, name: str) -> str | None:
        """Cari file_id berdasarkan nama di folder (None bila tak ada)."""
        svc = await self._svc()

        def _find():
            res = (
                svc.files()
                .list(
                    q=f"'{folder_id}' in parents and name='{name}' "
                    "and trashed=false",
                    fields="files(id)",
                    pageSize=1,
                )
                .execute()
            )
            files = res.get("files", [])
            return files[0]["id"] if files else None

        return await asyncio.to_thread(_find)

    # ---------- upload ----------

    async def upload_file(
        self, local_path: str, stream_name: str, retries: int = 3
    ) -> str | None:
        """Unggah satu segmen (resumable). Return file_id atau None bila gagal."""
        svc = await self._svc()
        folder_id = await self.ensure_folder(stream_name)
        name = os.path.basename(local_path)
        if await self.find_file(folder_id, name):
            return None  # sudah ada — anggap sukses, tak perlu file_id baru

        def _do():
            try:
                from googleapiclient.http import MediaFileUpload

                media = MediaFileUpload(
                    local_path, mimetype="video/mp4", resumable=True
                )
            except ImportError:
                media = None  # test memakai fake service (media_body diabaikan)
            return (
                svc.files()
                .create(
                    body={"name": name, "parents": [folder_id]},
                    media_body=media,
                    fields="id",
                )
                .execute()["id"]
            )

        last: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                file_id = await asyncio.to_thread(_do)
                log.info("drive: %s -> %s", name, file_id)
                return file_id
            except Exception as e:  # noqa: BLE001 — retry apa pun kegagalannya
                last = e
                log.warning(
                    "drive upload %s gagal (percobaan %d/%d): %s",
                    name, attempt, retries, e,
                )
                await asyncio.sleep(2 * attempt)
        log.error("drive upload %s gagal total: %s", name, last)
        return None

    async def queue_upload(self, local_path: str, stream_name: str) -> None:
        await self._queue.put((local_path, stream_name))

    async def scan_and_enqueue(self, db=None) -> int:
        """Enqueue segmen lokal yang belum ada di Drive. Return jumlah antrean.

        Nama folder memakai nama kamera dari DB bila `db` diberikan,
        fallback ke nama direktori (stream_{id}).
        """
        import re as _re

        s = self.settings
        names: dict[int, str] = {}
        if db is not None:
            from sqlalchemy import select

            from app.models.streams import Stream

            result = await db.execute(select(Stream.id, Stream.name))
            names = dict(result.all())
        try:
            entries = os.listdir(s.recordings_dir)
        except OSError:
            return 0
        count = 0
        for entry in sorted(entries):
            m = _re.match(r"^stream_(\d+)$", entry)
            if not m:
                continue
            d = os.path.join(s.recordings_dir, entry)
            if not os.path.isdir(d):
                continue
            stream_name = names.get(int(m.group(1)), entry)
            try:
                folder_id = await self.ensure_folder(stream_name)
            except Exception as e:  # noqa: BLE001
                log.warning("drive scan: folder %s gagal: %s", stream_name, e)
                continue
            try:
                files = sorted(os.listdir(d))
            except OSError:
                continue
            for name in files:
                if not name.endswith(".mp4"):
                    continue
                try:
                    exists = await self.find_file(folder_id, name)
                except Exception:  # noqa: BLE001
                    exists = True  # aman: jangan enqueue bila tak bisa cek
                if not exists:
                    await self.queue_upload(os.path.join(d, name), stream_name)
                    count += 1
        return count

    async def run_upload_loop(self) -> None:
        """Loop abadi: proses antrean upload."""
        try:
            while True:
                local_path, stream_name = await self._queue.get()
                try:
                    if os.path.exists(local_path):
                        await self.upload_file(local_path, stream_name)
                except Exception as e:  # noqa: BLE001
                    log.warning("drive loop: %s: %s", local_path, e)
                finally:
                    self._queue.task_done()
        except asyncio.CancelledError:
            pass

    # ---------- unduh parsial (proxy playback) ----------

    async def list_files(self, folder_id: str) -> list[dict]:
        """Daftar file (id, name, size) di folder — untuk sintetis segmen remote."""
        svc = await self._svc()

        def _list():
            out, token = [], None
            while True:
                res = (
                    svc.files()
                    .list(
                        q=f"'{folder_id}' in parents and trashed=false",
                        fields="files(id,name,size),nextPageToken",
                        pageSize=200,
                        pageToken=token,
                    )
                    .execute()
                )
                out.extend(res.get("files", []))
                token = res.get("nextPageToken")
                if not token:
                    break
            return out

        return await asyncio.to_thread(_list)

    async def stream_drive_file(
        self, file_id: str, start: int, end: int | None = None
    ) -> bytes:
        """Unduh rentang byte dari file Drive (Range request)."""
        svc = await self._svc()

        def _get():
            req = svc.files().get_media(fileId=file_id)
            req.headers["Range"] = (
                f"bytes={start}-{end}" if end is not None else f"bytes={start}-"
            )
            return req.execute()

        data = await asyncio.to_thread(_get)
        return data if isinstance(data, bytes) else bytes(data)

    # ---------- retensi Drive ----------

    async def apply_drive_retention(self, days: int) -> int:
        """Hapus file Drive lebih tua dari `days` di bawah folder root."""
        svc = await self._svc()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        def _list_all(folder_id: str) -> list[dict]:
            out, token = [], None
            while True:
                res = (
                    svc.files()
                    .list(
                        q=f"'{folder_id}' in parents and trashed=false",
                        fields="files(id,name,mimeType,createdTime),"
                        "nextPageToken",
                        pageSize=100,
                        pageToken=token,
                    )
                    .execute()
                )
                out.extend(res.get("files", []))
                token = res.get("nextPageToken")
                if not token:
                    break
            return out

        def _delete(file_id: str):
            svc.files().delete(fileId=file_id).execute()

        root_id = await self._ensure_child(svc, None, self.settings.drive_folder_root)
        deleted = 0
        for folder in await asyncio.to_thread(_list_all, root_id):
            if folder["mimeType"] != FOLDER_MIME:
                continue
            for f in await asyncio.to_thread(_list_all, folder["id"]):
                created = f.get("createdTime", "")
                try:
                    ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if ts < cutoff:
                    await asyncio.to_thread(_delete, f["id"])
                    deleted += 1
        if deleted:
            log.info("drive retensi: %d file dihapus", deleted)
        return deleted
