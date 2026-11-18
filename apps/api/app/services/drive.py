"""Uploader Google Drive (opsional, default nonaktif).

Multi-akun via streams.drive_account_id (NULL = akun default); token
terenkripsi di DB. Legacy token.json tetap didukung. Segmen selalu
ditulis lokal dulu lalu diunggah async (resumable + retry 3x).
"""

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

log = logging.getLogger("netravision.drive")

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
FOLDER_MIME = "application/vnd.google-apps.folder"
CHUNK = 1024 * 1024

def _atomic_write_text(path: str, content: str) -> None:
    """Tulis file teks secara atomik (temp + os.replace, 0600).

    Temuan 3.12: tulis token langsung `open(path, "w")` bisa
    meninggalkan token.json terpotong bila crash di tengah tulis.
    """
    import tempfile

    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".token.", dir=d)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise

# Area 5, temuan 5.2: antrean upload dibatasi + dedup, dan semua
# pemanggilan Google API punya timeout supaya scan tidak menggantung.
_QUEUE_MAXSIZE = 1000
_DRIVE_API_TIMEOUT_SEC = 120.0
# Area 5, temuan 5.10: cache folder kedaluwarsa (TTL 1 jam) dan dibatasi.
_FOLDER_CACHE_TTL_SEC = 3600.0
_FOLDER_CACHE_MAX = 512
# P1 (code review 2026-11-18): batas unduh Drive + konkurensi unduhan.
_MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
_DOWNLOAD_CONCURRENCY = 4
# P1: ID Drive (file/folder) hanya karakter ini (dipakai validasi
# sebelum ID masuk ke query Drive API atau argv).
_DRIVE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _escape_drive_query_value(value: str) -> str:
    """Escape nilai string untuk query Drive API (P1).

    Sintaks query Drive: string diapit kutip tunggal; kutip tunggal
    di-escape `\\'` dan backslash `\\\\`. Urutan penting: backslash
    dulu, supaya backslash yang ditambahkan untuk kutip tidak ikut
    di-escape. Tanpa ini, nama folder/file berisi `'` memutus query
    (atau menyuntikkan kondisi tambahan).
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _validate_drive_id(value: str) -> str:
    """Validasi ID Drive (file/folder); raise ValueError bila tidak cocok
    pola [A-Za-z0-9_-]+. Dipakai sebelum ID masuk ke query Drive API."""
    v = (value or "").strip()
    if not _DRIVE_ID_RE.match(v):
        raise ValueError("ID Drive tidak valid")
    return v


def _listdir_sorted(path: str) -> list[str]:
    """sorted(os.listdir(path)), [] bila direktori tak terbaca.

    Helper sinkron untuk asyncio.to_thread (scan tidak boleh memblokir
    event loop, P1); OSError ditelan di sini seperti perilaku lama.
    """
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


async def _drive_call(fn, *args, timeout: float = _DRIVE_API_TIMEOUT_SEC):
    """Jalankan pemanggilan Google API (sync) di thread dengan timeout.

    Timeout hanya membatalkan penantian di sisi asyncio; thread-nya
    dibiarkan selesai sendiri (googleapiclient tidak bisa diinterupsi),
    tapi scan/loop tidak lagi menggantung tanpa batas (temuan 5.2/5.8).
    """
    return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout)


def _build_upload_request(svc, folder_id: str, name: str, local_path: str):
    """Bangun SATU request upload resumable (MediaFileUpload + create).

    Temuan 3.11: request ini dipakai ulang di semua percobaan upload
    file yang sama. Chunk 1 MB (CHUNK) supaya timeout per chunk
    bermakna; chunk default googleapiclient 100 MB membuat satu
    panggilan next_chunk bisa menggantung lama. Bila googleapiclient
    tidak terinstal, media None dan request tetap bisa dijalankan
    lewat execute() (dipakai mock/fake di tes).
    """
    try:
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(
            local_path, mimetype="video/mp4", chunksize=CHUNK, resumable=True
        )
    except ImportError:
        media = None
    return svc.files().create(
        body={"name": name, "parents": [folder_id]},
        media_body=media, fields="id",
    )


def _drive_list_all(svc, folder_id: str, fields: str) -> list[dict]:
    """List semua file di folder (sync, panggil via to_thread)."""
    folder_id = _validate_drive_id(folder_id)
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


def _delete_local(local_path: str, name: str) -> None:
    """Hapus file lokal setelah ter-upload ke Drive (perintah user
    2026-11-17). Gagal hapus hanya dicatat, bukan kegagalan upload."""
    try:
        if os.path.isfile(local_path):
            os.remove(local_path)
            log.info("drive: lokal dihapus %s (%s)", local_path, name)
    except OSError as e:  # noqa: BLE001
        log.warning("drive: gagal hapus lokal %s: %s", local_path, e)


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
        # Area 5, 5.2: antrean BERBATAS (dulu tanpa maxsize, tumbuh tanpa
        # batas berisi duplikat dari scan berulang). queue_upload memakai
        # put_nowait + dedup lewat _queued, jadi scan tidak pernah
        # tertahan menunggu antrean penuh.
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._queued: set[str] = set()
        # _folder_cache: cache_key -> (folder_id, monotonic). Entri
        # kedaluwarsa setelah _FOLDER_CACHE_TTL_SEC (temuan 5.10).
        self._folder_cache: dict[str, tuple[str, float]] = {}
        # Area 5, 5.2: scan yang belum selesai tidak boleh ditumpuk scan
        # berikutnya (satu putaran scan bisa lebih lama dari interval).
        self._scan_lock = asyncio.Lock()
        # P1: batas unduhan Drive bersamaan (download_drive_file_to).
        self._download_sem = asyncio.Semaphore(_DOWNLOAD_CONCURRENCY)
        # Temuan 3.12: lock per instance untuk pembangunan service
        # (refresh token ganda) dan find-or-create folder (duplikat).
        self._svc_lock = asyncio.Lock()
        self._folder_lock = asyncio.Lock()
        # 6.7: cache list_files per folder (TTL 60 dtk, seperti lsjson
        # rclone yang di-cache 120 dtk). Satu alur putar (timeline +
        # playback-url + file) sebelumnya memanggil list_files segar
        # 3x untuk folder yang sama.
        self._list_cache: dict[str, tuple[float, list[dict]]] = {}

    _LIST_TTL_SEC = 60.0

    def invalidate_list_cache(self, folder_id: str | None = None) -> None:
        """Buang cache list_files (satu folder, atau semua)."""
        if folder_id is None:
            self._list_cache.clear()
        else:
            self._list_cache.pop(folder_id, None)

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
                # Temuan 3.12: tulis token hasil refresh secara atomik.
                _atomic_write_text(s.drive_token_file, creds.to_json())
            else:
                raise RuntimeError("token Drive tak valid, ulangi docs/GOOGLE-DRIVE.md")
        return build("drive", "v3", credentials=creds)

    async def _svc(self):
        if self._service is not None:
            return self._service
        # Temuan 3.12: tanpa lock, dua coroutine yang bersamaan saat
        # `_service is None` sama-sama refresh token dan hasilnya
        # saling menimpa.
        async with self._svc_lock:
            if self._service is not None:
                return self._service
            try:
                self._service = await _drive_call(self._build_service)
            except _TokenRefreshed as e:
                log.info("drive: token akun di-refresh, disimpan ulang ke DB")
                if self._save_token is not None:
                    await self._save_token(e.token_json)
                self._service = await _drive_call(self._build_service)
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
        # Area 5, 5.10: entri cache kedaluwarsa dibuang saat diakses.
        hit = self._folder_cache_get(cache_key)
        if hit is not None:
            return hit
        # Temuan 3.12: find-or-create tanpa lock bisa membuat dua folder
        # bernama sama bila dua pemanggil bersamaan sama-sama menemukan
        # tidak ada. Serialkan per uploader; cache dicek ulang di dalam
        # lock supaya pemanggil kedua tidak membuat folder lagi.
        async with self._folder_lock:
            hit = self._folder_cache_get(cache_key)
            if hit is not None:
                return hit
            svc = await self._svc()
            if self._account and self._account.root_folder_id:
                folder_id = await self._ensure_child(svc, self._account.root_folder_id, folder_name)
            else:
                root = await self._ensure_child(svc, None, self.settings.drive_folder_root)
                folder_id = await self._ensure_child(svc, root, folder_name)
            if len(self._folder_cache) >= _FOLDER_CACHE_MAX:
                oldest = min(
                    self._folder_cache,
                    key=lambda k: self._folder_cache[k][1],
                )
                del self._folder_cache[oldest]
            self._folder_cache[cache_key] = (folder_id, time.monotonic())
            return folder_id

    def _folder_cache_get(self, cache_key: str) -> str | None:
        """Folder dari cache, atau None bila belum ada/kedaluwarsa."""
        hit = self._folder_cache.get(cache_key)
        if hit is None:
            return None
        folder_id, at = hit
        if time.monotonic() - at < _FOLDER_CACHE_TTL_SEC:
            return folder_id
        del self._folder_cache[cache_key]
        return None

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
        # P1: nama di-escape untuk query Drive API, parent_id divalidasi
        # polanya sebelum masuk query (nama/body create tetap mentah:
        # body JSON tidak butuh escape query).
        if parent_id is not None:
            parent_id = _validate_drive_id(parent_id)
        name_q = _escape_drive_query_value(name)

        def _find():
            q = f"name='{name_q}' and mimeType='{FOLDER_MIME}' and trashed=false"
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

        return await _drive_call(_find) or await _drive_call(_create)

    async def find_file(self, folder_id: str, name: str) -> str | None:
        # P1: folder_id divalidasi polanya, nama di-escape untuk query.
        folder_id = _validate_drive_id(folder_id)
        name_q = _escape_drive_query_value(name)
        svc = await self._svc()

        def _find():
            res = svc.files().list(
                q=f"'{folder_id}' in parents and name='{name_q}' and trashed=false",
                fields="files(id)", pageSize=1,
            ).execute()
            files = res.get("files", [])
            return files[0]["id"] if files else None

        return await _drive_call(_find)

    async def upload_file(
        self, local_path: str, stream_name: str,
        stream_id: int | None = None, retries: int = 3,
    ):
        """Unggah satu segmen (resumable). Return file_id / None bila gagal."""
        svc = await self._svc()
        name = os.path.basename(local_path)
        # Temuan 3.2: klaim segmen selama upload supaya jalur uploader
        # rclone / mirror tidak memproses (dan menghapus) file yang
        # sama bersamaan. Tanpa stream_id (pemakaian legacy/test) klaim
        # dilewati karena tidak ada kunci kamera yang stabil.
        claimed = False
        if stream_id is not None:
            from app.services.upload_claims import try_claim

            if not try_claim(stream_id, name, "oauth"):
                log.info("drive: %s sedang diproses jalur lain, dilewati", name)
                return None
            claimed = True
        try:
            return await self._upload_file_claimed(
                svc, local_path, stream_name, stream_id, retries
            )
        finally:
            if claimed:
                from app.services.upload_claims import release_claim

                release_claim(stream_id, name, "oauth")

    async def _drive_upload_request(self, request) -> str:
        """Jalankan satu request upload sampai selesai, kembalikan file id.

        Temuan 3.11 (resume sejati): request resumable googleapiclient
        digerakkan per chunk lewat next_chunk(), masing-masing dengan
        timeout _DRIVE_API_TIMEOUT_SEC. Bila satu chunk gagal (timeout
        atau koneksi putus), percobaan berikut memanggil next_chunk()
        lagi pada request YANG SAMA, dan googleapiclient melanjutkan
        dari resumable_progress (bila perlu, next_chunk menanyakan dulu
        progres server lewat PUT kosong, jadi chunk yang responsnya
        hilang tidak dikirim ulang). Request tanpa next_chunk (mock di
        tes, atau media non-resumable bila googleapiclient tidak
        terinstal) dijalankan sekali lewat execute().
        """
        next_chunk = getattr(request, "next_chunk", None)
        if next_chunk is None:
            result = await _drive_call(
                request.execute, timeout=_DRIVE_API_TIMEOUT_SEC
            )
            if isinstance(result, dict):
                return result["id"]
            return result
        body = None
        while body is None:
            _status, body = await _drive_call(
                next_chunk, timeout=_DRIVE_API_TIMEOUT_SEC
            )
        return body["id"]

    async def _upload_file_claimed(
        self, svc, local_path: str, stream_name: str,
        stream_id: int | None, retries: int,
    ):
        folder_id = await self.ensure_folder(stream_name, stream_id)
        name = os.path.basename(local_path)
        if await self.find_file(folder_id, name):
            # Sudah ada di Drive: hapus lokal (perintah user 2026-11-17).
            self.invalidate_list_cache(folder_id)
            _delete_local(local_path, name)
            return None

        # Temuan 3.11: SATU request resumable untuk seluruh percobaan.
        # HttpRequest googleapiclient menyimpan resumable_uri dan
        # resumable_progress, jadi next_chunk() berikutnya melanjutkan
        # dari byte yang sudah diterima server. Membuat MediaFileUpload
        # baru per percobaan berarti upload mengulang dari byte 0.
        request = None
        last: Exception | None = None
        for attempt in range(1, retries + 1):
            if attempt > 1:
                # Temuan 3.11: respons upload bisa hilang padahal file
                # sudah sampai di Drive; cek lagi sebelum retry supaya
                # tidak membuat duplikat.
                try:
                    existing = await self.find_file(folder_id, name)
                except Exception:  # noqa: BLE001
                    existing = None
                if existing:
                    log.info(
                        "drive: %s ternyata sudah ada di Drive (retry %d), "
                        "hapus lokal tanpa upload ulang", name, attempt,
                    )
                    self.invalidate_list_cache(folder_id)
                    _delete_local(local_path, name)
                    return existing
            try:
                if request is None:
                    request = _build_upload_request(
                        svc, folder_id, name, local_path
                    )
                fid = await self._drive_upload_request(request)
                log.info("drive: %s -> %s", name, fid)
                # Ter-upload: hapus lokal (perintah user 2026-11-17).
                self.invalidate_list_cache(folder_id)
                _delete_local(local_path, name)
                return fid
            except Exception as e:  # noqa: BLE001
                last = e
                log.warning("drive upload %s gagal (%d/%d): %s", name, attempt, retries, e)
                await asyncio.sleep(2 * attempt)
        log.error("drive upload %s gagal total: %s", name, last)
        return None

    async def queue_upload(
        self, local_path: str, stream_name: str, stream_id: int | None = None
    ) -> bool:
        """Antrekan satu segmen. Return False bila sudah diantrekan
        (dedup) atau antrean penuh (temuan 5.2); segmen yang ditolak
        dicoba lagi oleh scan 5 menit berikut, jadi tidak ada yang hilang.

        Item 3-elemen bila stream_id diketahui (folder berbasis ID, B-R2);
        2-elemen untuk pemakaian legacy.
        """
        if local_path in self._queued:
            return False
        item = (
            (local_path, stream_name, stream_id)
            if stream_id is not None
            else (local_path, stream_name)
        )
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            log.warning(
                "drive: antrean upload penuh (%d), %s ditunda ke scan berikut",
                _QUEUE_MAXSIZE, local_path,
            )
            return False
        self._queued.add(local_path)
        return True

    def queue_size(self) -> int:
        """Jumlah segmen menunggu di antrean (untuk /api/health, 5.8)."""
        return self._queue.qsize()

    def _mine(self, drive_account_id, storage_mode: str) -> bool:
        if storage_mode not in ("drive", "both"):
            return False
        if self._account is None:
            return True  # legacy: hanya dipakai bila tak ada akun terhubung
        if str(drive_account_id or "") == self._account.id:
            return True
        return self._account.is_default and drive_account_id is None

    async def scan_and_enqueue(self, db=None) -> int:
        """Pindai segmen lokal yang belum ada di Drive, antrekan upload.

        Area 5, 5.2: bila scan sebelumnya belum selesai, putaran ini
        dilewati supaya scan tidak menumpuk (satu putaran scan bisa
        lebih lama dari interval 5 menit saat backlog besar).
        """
        if self._scan_lock.locked():
            log.warning("drive scan dilewati: scan sebelumnya belum selesai")
            return 0
        async with self._scan_lock:
            return await self._scan_and_enqueue_locked(db)

    async def _scan_and_enqueue_locked(self, db=None) -> int:
        import re as _re

        s = self.settings
        names: dict[int, str] = {}
        mine: set[int] = set()
        if db is not None:
            from sqlalchemy import select

            from app.models.streams import Stream

            q = select(Stream.id, Stream.name, Stream.drive_account_id, Stream.storage_mode, Stream.record_disk, Stream.group_name)
            rows = (await db.execute(q)).all()
            for r in rows:
                names[r.id] = r.name
                if self._mine(r.drive_account_id, r.storage_mode):
                    mine.add(r.id)
        # Direktori yang dipindai: legacy recordings_dir/stream_{id} plus
        # stream_{id}_sub (rekaman dari substream bila kamera punya sub,
        # perintah user 2026-11-14) plus direktori multi-disk
        # (camera_rec_dir) untuk kamera yang record_disk-nya terisi
        # (segmennya tidak ada di recordings_dir).
        targets: list[tuple[int, str, str]] = []
        # P1: os.listdir di thread (direktori rekaman bisa berisi ribuan
        # entri; pemindaian sinkron memblokir event loop).
        entries = await asyncio.to_thread(_listdir_sorted, s.recordings_dir)
        for entry in entries:
            m = _re.match(r"^stream_(\d+)(?:_sub)?$", entry)
            if not m:
                continue
            sid = int(m.group(1))
            if db is not None and sid not in mine:
                continue
            d = os.path.join(s.recordings_dir, entry)
            if not os.path.isdir(d):
                continue
            targets.append((sid, names.get(sid, entry), d))
        if db is not None:
            from types import SimpleNamespace

            from app.services.disks import camera_rec_dirs

            for r in rows:
                if not getattr(r, "record_disk", None):
                    continue
                if r.id not in mine:
                    continue
                fake = SimpleNamespace(
                    id=r.id,
                    name=r.name,
                    group_name=getattr(r, "group_name", None),
                    record_disk=r.record_disk,
                )
                for d in camera_rec_dirs(fake, s.recordings_dir):
                    if not os.path.isdir(d):
                        continue
                    if any(t[2] == d for t in targets):
                        continue
                    targets.append((r.id, r.name, d))
        count = 0
        for sid, stream_name, d in targets:
            try:
                folder_id = await self.ensure_folder(stream_name, sid)
                files = await asyncio.to_thread(_listdir_sorted, d)
            except Exception as e:  # noqa: BLE001
                log.warning("drive scan %s gagal: %s", stream_name, e)
                continue
            # 6.2: SATU list_files per folder lalu cocokkan di memori,
            # bukan satu files.list per segmen. Sebelumnya tiap segmen
            # memanggil find_file (satu panggilan Drive API) secara
            # berurutan; backlog besar (Drive mati berjam-jam) berarti
            # ribuan panggilan API per putaran scan 5 menit.
            try:
                existing = {
                    f.get("name")
                    for f in await self.list_files(folder_id)
                }
            except Exception as e:  # noqa: BLE001
                # B-R3 (diadaptasi): kegagalan cek JANGAN dianggap
                # "sudah ada". Lewati folder ini putaran ini; scan
                # 5 menit berikut mencoba lagi.
                log.warning(
                    "drive scan %s: list folder gagal, dicoba lagi "
                    "putaran berikut: %s",
                    stream_name, e,
                )
                continue
            for name in files:
                if not name.endswith(".mp4"):
                    continue
                # Temuan 3.2: segmen yang sedang diproses jalur uploader
                # rclone / mirror dilewati; scan 5 menit berikut mencoba
                # lagi bila segmen itu ternyata tidak jadi ter-upload.
                from app.services.upload_claims import is_claimed

                if is_claimed(sid, name):
                    continue
                if name not in existing:
                    # Area 5, 5.2: queue_upload False = duplikat/antrean
                    # penuh; jangan hitung sebagai "diantrekan".
                    if await self.queue_upload(
                        os.path.join(d, name), stream_name, sid
                    ):
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
                    # Area 5, 5.2: keluarkan dari set dedup supaya scan
                    # berikut boleh mengantrekan ulang bila upload gagal
                    # (file masih ada) atau selesai (file sudah dihapus).
                    self._queued.discard(local_path)
                    self._queue.task_done()
        except asyncio.CancelledError:
            pass

    async def list_files(self, folder_id: str) -> list[dict]:
        # 6.7: cache TTL 60 dtk per folder (lihat __init__).
        now = time.monotonic()
        hit = self._list_cache.get(folder_id)
        if hit is not None and now - hit[0] < self._LIST_TTL_SEC:
            return [dict(f) for f in hit[1]]
        svc = await self._svc()
        items = await _drive_call(_drive_list_all, svc, folder_id, "files(id,name,size)")
        self._list_cache[folder_id] = (now, [dict(f) for f in items])
        return items

    async def download_drive_file_to(
        self, file_id: str, dest_path: str,
        max_bytes: int = _MAX_DOWNLOAD_BYTES,
    ) -> int:
        """Unduh satu file Drive langsung ke `dest_path` secara streaming.

        P1: `download_drive_file` lama menampung seluruh file di RAM
        (satu `get_media().execute()`). Di sini `MediaIoBaseDownload`
        mengunduh per chunk (CHUNK, 1 MB), masing-masing lewat
        `_drive_call` (timeout per chunk), jadi segmen besar tidak
        pernah menumpuk di memori. Konkurensi dibatasi semaphore
        (4 unduhan bersamaan). Bila file melebihi `max_bytes`
        (default 2 GiB) unduhan dibatalkan dan file sebagian dihapus.
        Bila googleapiclient tidak terinstal (mock di tes), fallback
        ke `get_media().execute()` sekali, tetap dengan batas ukuran.
        Return ukuran byte yang tertulis. Dipakai pemutar di
        routers/recordings.py sebagai pengganti `download_drive_file`
        bila RAM jadi soal; wrapper lama di bawah tetap ada.
        """
        file_id = _validate_drive_id(file_id)
        if max_bytes <= 0:
            raise ValueError("max_bytes harus > 0")
        async with self._download_sem:
            svc = await self._svc()
            try:
                from googleapiclient.http import MediaIoBaseDownload
            except ImportError:
                def _get():
                    return svc.files().get_media(fileId=file_id).execute()

                data = await _drive_call(_get)
                data = data if isinstance(data, bytes) else bytes(data)
                if len(data) > max_bytes:
                    raise RuntimeError(
                        f"file Drive {file_id} ({len(data)} byte) melebihi "
                        f"batas unduh {max_bytes} byte"
                    )

                def _write():
                    with open(dest_path, "wb") as f:
                        f.write(data)

                await asyncio.to_thread(_write)
                return len(data)
            fh = None
            try:
                fh = open(dest_path, "wb")
                request = svc.files().get_media(fileId=file_id)
                downloader = MediaIoBaseDownload(fh, request, chunksize=CHUNK)
                done = False
                while not done:
                    status, done = await _drive_call(downloader.next_chunk)
                    progress = getattr(status, "resumable_progress", None)
                    if progress is not None and progress > max_bytes:
                        raise RuntimeError(
                            f"file Drive {file_id} melebihi batas unduh "
                            f"{max_bytes} byte"
                        )
            except BaseException:
                if fh is not None:
                    try:
                        fh.close()
                    except OSError:
                        pass
                try:
                    os.remove(dest_path)
                except OSError:
                    pass
                raise
            fh.close()
            return await asyncio.to_thread(os.path.getsize, dest_path)

    async def download_drive_file(self, file_id: str) -> bytes:
        """Unduh utuh satu file Drive via SATU get_media (tanpa Range).

        6.1: cerminan perbaikan rclone 7cbf088. Sebelumnya pemutar
        memanggil stream_drive_file per potongan 1 MB (satu HTTPS
        request + auth + seek per MB); segmen 20 MB berarti 20
        panggilan API berurutan. Kini unduh sekali, Range dilayani
        dari memori oleh pemanggil.

        P1: kini diimplementasikan di atas `download_drive_file_to`
        (streaming ke file temp lalu dibaca), jadi ada batas ukuran
        2 GiB + semaphore konkurensi; pemanggil yang melayani
        playback sebaiknya memakai `download_drive_file_to` langsung
        supaya RAM tidak menampung segmen utuh.
        """
        import tempfile

        fd, tmp = tempfile.mkstemp(prefix="drive-dl-")
        os.close(fd)
        try:
            await self.download_drive_file_to(file_id, tmp)

            def _read():
                with open(tmp, "rb") as f:
                    return f.read()

            return await asyncio.to_thread(_read)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    async def stream_drive_file(self, file_id: str, start: int, end=None) -> bytes:
        svc = await self._svc()

        def _get():
            req = svc.files().get_media(fileId=file_id)
            req.headers["Range"] = f"bytes={start}-{end}" if end is not None else f"bytes={start}-"
            return req.execute()

        data = await _drive_call(_get)
        return data if isinstance(data, bytes) else bytes(data)

    async def apply_drive_retention(self, days: int, max_files: int = 1000) -> int:
        """Retensi Drive: hapus segmen rekaman lama di Drive.

        Temuan 3.4: HANYA file segmen rekaman yang dihapus, yaitu nama
        `.mp4` yang cocok pola nama segmen MediaMTX (`SEGMENT_RE`,
        `YYYY-MM-DD_HH-MM-SS-ffffff.mp4`). Sebelumnya SEMUA file lama
        di folder kamera dihapus, termasuk dokumen/foto/backup yang
        ditaruh manual. Nama file yang akan dihapus dicatat di log
        sebelum dihapus (bukan dry-run penuh, tapi jejak audit).
        """
        from app.services.recording import SEGMENT_RE

        svc = await self._svc()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        fields = "files(id,name,mimeType,createdTime)"

        async def _all(folder_id: str) -> list[dict]:
            return await _drive_call(_drive_list_all, svc, folder_id, fields)

        if self._account and self._account.root_folder_id:
            root_id = self._account.root_folder_id
        else:
            root_id = await self._ensure_child(svc, None, self.settings.drive_folder_root)
        deleted = 0
        for folder in await _all(root_id):
            if folder["mimeType"] != FOLDER_MIME:
                continue
            for f in await _all(folder["id"]):
                fname = f.get("name", "") or ""
                if not fname.lower().endswith(".mp4"):
                    continue
                if not SEGMENT_RE.match(fname):
                    continue
                try:
                    ts = datetime.fromisoformat(f.get("createdTime", "").replace("Z", "+00:00"))
                except ValueError:
                    continue
                if ts < cutoff:
                    log.info("drive retensi: hapus %s (%s)", fname, f["id"])
                    await _drive_call(
                        svc.files().delete(fileId=f["id"]).execute
                    )
                    deleted += 1
                    if deleted >= max_files:
                        # Area 5, 5.7: dibatasi per putaran supaya satu
                        # putaran tidak me-list dan menghapus tanpa batas;
                        # sisa file dihapus putaran berikut.
                        log.warning(
                            "drive retensi: batas %d file per putaran "
                            "tercapai, sisa dihapus putaran berikut",
                            max_files,
                        )
                        return deleted
        if deleted:
            log.info("drive retensi: %d file dihapus", deleted)
        return deleted
