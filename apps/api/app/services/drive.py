"""Uploader Google Drive (opsional, default nonaktif).

Multi-akun via streams.drive_account_id (NULL = akun default); token
terenkripsi di DB. Legacy token.json tetap didukung. Segmen selalu
ditulis lokal dulu lalu diunggah async (resumable + retry 3x).
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

log = logging.getLogger("netravision.drive")

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
FOLDER_MIME = "application/vnd.google-apps.folder"
CHUNK = 1024 * 1024


def _drive_list_all(svc, folder_id: str, fields: str) -> list[dict]:
    """List semua file di folder (sync, panggil via to_thread)."""
    out, token = [], None
    while True:
        res = svc.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields=fields + ",nextPageToken", pageSize=200, pageToken=token,
        ).execute()
        out.extend(res.get("files", []))
        token = res.get("nextPageToken")
        if not token:
            break
    return out


@dataclass
class AccountCreds:
    """Kredensial akun Drive (primitif, aman lintas sesi DB)."""

    id: str
    token: dict
    root_folder_id: str | None
    is_default: bool


class _TokenRefreshed(Exception):
    def __init__(self, token_json: str):
        super().__init__("token refreshed")
        self.token_json = token_json


class DriveUploader:
    def __init__(self, settings=None, service=None, account=None, save_token=None):
        from app.core.config import get_settings

        self.settings = settings or get_settings()
        self._service = service
        self._account: AccountCreds | None = account
        self._save_token = save_token
        self._queue: asyncio.Queue = asyncio.Queue()
        self._folder_cache: dict[str, str] = {}

    def _build_service(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as e:
            raise RuntimeError(
                "dependensi drive belum terinstal (pip install netravision-api[drive])"
            ) from e
        if self._account is not None:
            creds = Credentials.from_authorized_user_info(self._account.token, SCOPES)
            if creds.valid:
                return build("drive", "v3", credentials=creds)
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self._account.token = json.loads(creds.to_json())
                raise _TokenRefreshed(creds.to_json())
            raise RuntimeError(f"token Drive akun {self._account.id} tidak valid, reauth")
        s = self.settings  # legacy: token.json instalasi satu-akun lama
        if not os.path.exists(s.drive_token_file):
            raise RuntimeError(f"{s.drive_token_file} belum ada, lihat docs/GOOGLE-DRIVE.md")
        creds = Credentials.from_authorized_user_file(s.drive_token_file, SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(s.drive_token_file, "w") as f:
                    f.write(creds.to_json())
            else:
                raise RuntimeError("token Drive tak valid, ulangi docs/GOOGLE-DRIVE.md")
        return build("drive", "v3", credentials=creds)

    async def _svc(self):
        if self._service is None:
            try:
                self._service = await asyncio.to_thread(self._build_service)
            except _TokenRefreshed as e:
                log.info("drive: token akun di-refresh, disimpan ulang ke DB")
                if self._save_token is not None:
                    await self._save_token(e.token_json)
                self._service = await asyncio.to_thread(self._build_service)
        return self._service

    async def ensure_folder(self, stream_name: str, stream_id: int | None = None) -> str:
        """Folder Drive untuk satu kamera.

        B-R2: folder diidentifikasi dari ID kamera (nama tidak unik dan bisa
        berubah). Bila stream_id diisi, nama folder = `stream_{id}` (stabil
        walau kamera diganti nama; cache dikunci per ID). Tanpa stream_id
        (pemakaian legacy/test), perilaku lama berbasis nama dipertahankan.
        """
        if stream_id is not None:
            cache_key = f"id:{stream_id}"
            folder_name = f"stream_{stream_id}"
        else:
            cache_key = f"name:{stream_name}"
            folder_name = stream_name
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]
        svc = await self._svc()
        if self._account and self._account.root_folder_id:
            folder_id = await self._ensure_child(svc, self._account.root_folder_id, folder_name)
        else:
            root = await self._ensure_child(svc, None, self.settings.drive_folder_root)
            folder_id = await self._ensure_child(svc, root, folder_name)
        self._folder_cache[cache_key] = folder_id
        return folder_id

    def invalidate_folder_cache(
        self, stream_id: int | None = None, stream_name: str | None = None
    ) -> None:
        """Buang entri cache folder satu kamera (mis. setelah ganti nama).

        Folder berbasis ID tidak bergantung pada nama, jadi ganti nama tidak
        lagi membuat folder yatim; ini hanya membersihkan sisa entri legacy
        berbasis nama.
        """
        if stream_id is not None:
            self._folder_cache.pop(f"id:{stream_id}", None)
        if stream_name is not None:
            self._folder_cache.pop(f"name:{stream_name}", None)

    async def _ensure_child(self, svc, parent_id, name: str) -> str:
        def _find():
            q = f"name='{name}' and mimeType='{FOLDER_MIME}' and trashed=false"
            if parent_id:
                q += f" and '{parent_id}' in parents"
            res = svc.files().list(q=q, fields="files(id)", pageSize=1).execute()
            files = res.get("files", [])
            return files[0]["id"] if files else None

        def _create():
            body: dict = {"name": name, "mimeType": FOLDER_MIME}
            if parent_id:
                body["parents"] = [parent_id]
            return svc.files().create(body=body, fields="id").execute()["id"]

        return await asyncio.to_thread(_find) or await asyncio.to_thread(_create)

    async def find_file(self, folder_id: str, name: str) -> str | None:
        svc = await self._svc()

        def _find():
            res = svc.files().list(
                q=f"'{folder_id}' in parents and name='{name}' and trashed=false",
                fields="files(id)", pageSize=1,
            ).execute()
            files = res.get("files", [])
            return files[0]["id"] if files else None

        return await asyncio.to_thread(_find)

    async def upload_file(
        self, local_path: str, stream_name: str,
        stream_id: int | None = None, retries: int = 3,
    ):
        """Unggah satu segmen (resumable). Return file_id / None bila gagal."""
        svc = await self._svc()
        folder_id = await self.ensure_folder(stream_name, stream_id)
        name = os.path.basename(local_path)
        if await self.find_file(folder_id, name):
            return None

        def _do():
            try:
                from googleapiclient.http import MediaFileUpload

                media = MediaFileUpload(local_path, mimetype="video/mp4", resumable=True)
            except ImportError:
                media = None
            return svc.files().create(
                body={"name": name, "parents": [folder_id]},
                media_body=media, fields="id",
            ).execute()["id"]

        last: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                fid = await asyncio.to_thread(_do)
                log.info("drive: %s -> %s", name, fid)
                return fid
            except Exception as e:  # noqa: BLE001
                last = e
                log.warning("drive upload %s gagal (%d/%d): %s", name, attempt, retries, e)
                await asyncio.sleep(2 * attempt)
        log.error("drive upload %s gagal total: %s", name, last)
        return None

    async def queue_upload(
        self, local_path: str, stream_name: str, stream_id: int | None = None
    ) -> None:
        # Item 3-elemen bila stream_id diketahui (folder berbasis ID, B-R2);
        # 2-elemen untuk pemakaian legacy.
        await self._queue.put(
            (local_path, stream_name, stream_id)
            if stream_id is not None
            else (local_path, stream_name)
        )

    def _mine(self, drive_account_id, storage_mode: str) -> bool:
        if storage_mode not in ("drive", "both"):
            return False
        if self._account is None:
            return True  # legacy: hanya dipakai bila tak ada akun terhubung
        if str(drive_account_id or "") == self._account.id:
            return True
        return self._account.is_default and drive_account_id is None

    async def scan_and_enqueue(self, db=None) -> int:
        import re as _re

        s = self.settings
        names: dict[int, str] = {}
        mine: set[int] = set()
        if db is not None:
            from sqlalchemy import select

            from app.models.streams import Stream

            q = select(Stream.id, Stream.name, Stream.drive_account_id, Stream.storage_mode)
            rows = (await db.execute(q)).all()
            for r in rows:
                names[r.id] = r.name
                if self._mine(r.drive_account_id, r.storage_mode):
                    mine.add(r.id)
        try:
            entries = sorted(os.listdir(s.recordings_dir))
        except OSError:
            return 0
        count = 0
        for entry in entries:
            m = _re.match(r"^stream_(\d+)$", entry)
            if not m:
                continue
            sid = int(m.group(1))
            if db is not None and sid not in mine:
                continue
            d = os.path.join(s.recordings_dir, entry)
            if not os.path.isdir(d):
                continue
            stream_name = names.get(sid, entry)
            try:
                folder_id = await self.ensure_folder(stream_name, sid)
                files = sorted(os.listdir(d))
            except Exception as e:  # noqa: BLE001
                log.warning("drive scan %s gagal: %s", stream_name, e)
                continue
            for name in files:
                if not name.endswith(".mp4"):
                    continue
                try:
                    exists = await self.find_file(folder_id, name)
                except Exception as e:  # noqa: BLE001
                    # B-R3: kegagalan cek JANGAN dianggap "sudah ada". Catat
                    # dan lewati putaran ini; scan 5 menit berikut mencoba lagi.
                    log.warning(
                        "drive scan %s: cek %s gagal, dicoba lagi putaran berikut: %s",
                        stream_name, name, e,
                    )
                    continue
                if not exists:
                    await self.queue_upload(os.path.join(d, name), stream_name, sid)
                    count += 1
        return count

    async def run_upload_loop(self) -> None:
        try:
            while True:
                item = await self._queue.get()
                local_path, stream_name = item[0], item[1]
                stream_id = item[2] if len(item) > 2 else None
                try:
                    if os.path.exists(local_path):
                        await self.upload_file(local_path, stream_name, stream_id)
                except Exception as e:  # noqa: BLE001
                    log.warning("drive loop: %s: %s", local_path, e)
                finally:
                    self._queue.task_done()
        except asyncio.CancelledError:
            pass

    async def list_files(self, folder_id: str) -> list[dict]:
        svc = await self._svc()
        return await asyncio.to_thread(_drive_list_all, svc, folder_id, "files(id,name,size)")

    async def stream_drive_file(self, file_id: str, start: int, end=None) -> bytes:
        svc = await self._svc()

        def _get():
            req = svc.files().get_media(fileId=file_id)
            req.headers["Range"] = f"bytes={start}-{end}" if end is not None else f"bytes={start}-"
            return req.execute()

        data = await asyncio.to_thread(_get)
        return data if isinstance(data, bytes) else bytes(data)

    async def apply_drive_retention(self, days: int) -> int:
        svc = await self._svc()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        fields = "files(id,name,mimeType,createdTime)"

        async def _all(folder_id: str) -> list[dict]:
            return await asyncio.to_thread(_drive_list_all, svc, folder_id, fields)

        if self._account and self._account.root_folder_id:
            root_id = self._account.root_folder_id
        else:
            root_id = await self._ensure_child(svc, None, self.settings.drive_folder_root)
        deleted = 0
        for folder in await _all(root_id):
            if folder["mimeType"] != FOLDER_MIME:
                continue
            for f in await _all(folder["id"]):
                try:
                    ts = datetime.fromisoformat(f.get("createdTime", "").replace("Z", "+00:00"))
                except ValueError:
                    continue
                if ts < cutoff:
                    await asyncio.to_thread(svc.files().delete(fileId=f["id"]).execute)
                    deleted += 1
        if deleted:
            log.info("drive retensi: %d file dihapus", deleted)
        return deleted
