"""Test DriveUploader dengan fake Google Drive service (tanpa network)."""

import re
from types import SimpleNamespace

from app.services.drive import FOLDER_MIME, DriveUploader


class _Req:
    def __init__(self, fn):
        self._fn = fn
        self.headers = {}

    def execute(self):
        return self._fn(self)


class FakeDrive:
    """Meniru googleapiclient drive v3 secukupnya untuk test."""

    def __init__(self):
        self._folders: dict[tuple, str] = {}  # (parent_id, name) -> id
        self._files: dict[tuple, dict] = {}  # (folder_id, name) -> file
        self.fail_create = 0
        self._n = 0

    def _nid(self, prefix):
        self._n += 1
        return f"{prefix}{self._n}"

    def files(self):
        return self

    @staticmethod
    def _q_name(q):
        m = re.search(r"name='([^']+)'", q or "")
        return m.group(1) if m else None

    @staticmethod
    def _q_parent(q):
        m = re.search(r"'([^']+)' in parents", q or "")
        return m.group(1) if m else None

    def list(self, q="", fields=None, pageSize=None, pageToken=None):
        def run(req):
            parent, name = self._q_parent(q), self._q_name(q)
            only_folders = FOLDER_MIME in q
            out = []
            for (p, n), fid in self._folders.items():
                if p == parent and (name is None or n == name):
                    out.append(
                        {
                            "id": fid,
                            "name": n,
                            "mimeType": FOLDER_MIME,
                            "createdTime": "",
                        }
                    )
            if not only_folders:
                for (p, n), f in self._files.items():
                    if p == parent and (name is None or n == name):
                        out.append(
                            {
                                "id": f["id"],
                                "name": n,
                                "size": f.get("size", 0),
                                "createdTime": f.get("createdTime", ""),
                                "mimeType": "video/mp4",
                            }
                        )
            return {"files": out}

        return _Req(run)

    def create(self, body=None, media_body=None, fields=None):
        def run(req):
            is_folder = body.get("mimeType") == FOLDER_MIME
            # simulasi kegagalan hanya untuk upload file, bukan folder
            if not is_folder and self.fail_create > 0:
                self.fail_create -= 1
                raise RuntimeError("upload gagal (simulasi)")
            if is_folder:
                parent = (body.get("parents") or [None])[0]
                fid = self._nid("fld")
                self._folders[(parent, body["name"])] = fid
                return {"id": fid}
            parent = (body.get("parents") or [None])[0]
            fid = self._nid("file")
            self._files[(parent, body["name"])] = {
                "id": fid,
                "name": body["name"],
                "size": 16,
                "createdTime": "2026-11-02T10:00:00Z",
                "content": b"0123456789ABCDEF",
            }
            return {"id": fid}

        return _Req(run)

    def get_media(self, fileId=None):
        def run(req):
            for f in self._files.values():
                if f["id"] == fileId:
                    data = f.get("content", b"")
                    m = re.match(r"bytes=(\d+)-(\d*)", req.headers.get("Range", ""))
                    if m:
                        s = int(m.group(1))
                        e = int(m.group(2)) if m.group(2) else len(data) - 1
                        return data[s : e + 1]
                    return data
            raise RuntimeError("file tidak ada")

        return _Req(run)

    def delete(self, fileId=None):
        def run(req):
            for k, f in list(self._files.items()):
                if f["id"] == fileId:
                    del self._files[k]
            return {}

        return _Req(run)


def _settings(tmp_path=None):
    return SimpleNamespace(
        drive_enabled=True,
        drive_folder_root="NetraVision",
        recordings_dir=str(tmp_path) if tmp_path else "/none",
    )


async def test_folder_structure():
    up = DriveUploader(settings=_settings(), service=FakeDrive())
    fid = await up.ensure_folder("Cam A")
    svc = up._service
    root = svc._folders[(None, "NetraVision")]
    assert svc._folders[(root, "Cam A")] == fid
    # idempoten: panggil lagi tak membuat folder baru
    assert await up.ensure_folder("Cam A") == fid
    assert len(svc._folders) == 2


async def test_upload_retry_lalu_sukses(tmp_path):
    svc = FakeDrive()
    svc.fail_create = 1  # gagal sekali, lalu sukses
    up = DriveUploader(settings=_settings(), service=svc)
    p = tmp_path / "2026-11-02_10-00-00-000000.mp4"
    p.write_bytes(b"v" * 16)
    file_id = await up.upload_file(str(p), "Cam A", retries=3)
    assert file_id is not None
    # file tercatat di folder Cam A
    folder_id = await up.ensure_folder("Cam A")
    assert await up.find_file(folder_id, p.name) == file_id


async def test_upload_gagal_total_kembali_none(tmp_path):
    svc = FakeDrive()
    svc.fail_create = 99  # selalu gagal
    up = DriveUploader(settings=_settings(), service=svc)
    p = tmp_path / "seg.mp4"
    p.write_bytes(b"v")
    assert await up.upload_file(str(p), "Cam A", retries=2) is None


async def test_stream_drive_file_range():
    svc = FakeDrive()
    up = DriveUploader(settings=_settings(), service=svc)
    file_id = await up.upload_file("/tmp/x.mp4", "Cam A")
    assert file_id is not None
    data = await up.stream_drive_file(file_id, 2, 5)
    assert data == b"2345"
    data2 = await up.stream_drive_file(file_id, 10, None)
    assert data2 == b"ABCDEF"


async def test_scan_and_enqueue_lewati_yang_sudah_ada(tmp_path):
    svc = FakeDrive()
    up = DriveUploader(settings=_settings(tmp_path), service=svc)
    d = tmp_path / "stream_7"
    d.mkdir()
    (d / "a.mp4").write_bytes(b"1")
    (d / "b.mp4").write_bytes(b"2")
    # b.mp4 sudah ada di Drive
    folder_id = await up.ensure_folder("stream_7")
    svc._files[(folder_id, "b.mp4")] = {
        "id": "f1",
        "name": "b.mp4",
        "size": 1,
        "createdTime": "",
        "content": b"2",
    }
    n = await up.scan_and_enqueue()
    assert n == 1
    item = await up._queue.get()
    assert item[0].endswith("a.mp4")


async def test_apply_drive_retention():
    svc = FakeDrive()
    up = DriveUploader(settings=_settings(), service=svc)
    folder_id = await up.ensure_folder("Cam A")
    svc._files[(folder_id, "lama.mp4")] = {
        "id": "old1",
        "name": "lama.mp4",
        "size": 1,
        "createdTime": "2020-01-01T00:00:00Z",
        "content": b"x",
    }
    svc._files[(folder_id, "baru.mp4")] = {
        "id": "new1",
        "name": "baru.mp4",
        "size": 1,
        "createdTime": "2026-11-02T00:00:00Z",
        "content": b"x",
    }
    n = await up.apply_drive_retention(days=30)
    assert n == 1
    assert await up.find_file(folder_id, "lama.mp4") is None
    assert await up.find_file(folder_id, "baru.mp4") == "new1"


async def test_queue_upload_dan_loop(tmp_path):
    svc = FakeDrive()
    up = DriveUploader(settings=_settings(), service=svc)
    p = tmp_path / "q.mp4"
    p.write_bytes(b"v" * 8)
    await up.queue_upload(str(p), "Cam A")
    # proses satu item manual (tanpa loop abadi)
    local_path, stream_name = await up._queue.get()
    fid = await up.upload_file(local_path, stream_name)
    up._queue.task_done()
    assert fid is not None
