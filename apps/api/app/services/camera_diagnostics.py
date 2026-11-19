"""Klasifikasi kegagalan tambah kamera + riwayat kegagalan dan hasil probe.

Setiap kegagalan dipetakan ke satu envelope yang bisa dibaca manusia:
    {"code", "judul", "penyebab", "langkah": [...]}

Copy memakai Bahasa Indonesia, tanpa em dash dan tanpa en dash.
Tidak pernah memuat kredensial: URL di-redact sebelum masuk envelope
atau riwayat (lihat app.core.security.redact_url_credentials).

Dipakai di dua tempat:
- admin_create_stream: tiap titik gagal (probe RTSP, discovery,
  resolver, registrasi MediaMTX) mengembalikan envelope ini, bukan
  HTTP 500 kosong dan bukan pesan mentah.
- admin_diagnostics: halaman diagnostik menampilkan envelope yang sama
  untuk control API MediaMTX dan riwayat kegagalan terakhir.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import redact_url_credentials
from app.models.diagnostics import CameraAddFailure, CameraProbeResult
from app.services.mediamtx import MediaMTXError

# Status probe RTSP yang berarti video (sukses), sisanya gagal.
PROBE_OK = "video"

# Status probe yang dikenal dari rtsp_discovery.verify_url.
PROBE_STATUSES = ("video", "no_video", "auth_failed", "not_found", "timeout", "error")

# Label peran stream untuk copy.
_PERAN = {"main": "Stream utama", "sub": "Substream"}


def failure_envelope(
    code: str, judul: str, penyebab: str, langkah: list[str]
) -> dict:
    """Satu envelope kegagalan yang bisa dibaca manusia."""
    return {
        "code": code,
        "judul": judul,
        "penyebab": penyebab,
        "langkah": list(langkah),
    }


def classify_mediamtx_error(exc: Exception) -> dict:
    """Klasifikasikan error MediaMTX menjadi envelope.

    Kasus nyata dari sesi debug: endpoint salah (redirect 307),
    auth control API 401 karena hanya localhost, dan MediaMTX tidak
    terjangkau (service mati / port tertutup).
    """
    kind = getattr(exc, "kind", None)
    status = getattr(exc, "status_code", None)
    if isinstance(exc, MediaMTXError):
        if kind == "redirect":
            return failure_envelope(
                "mediamtx_redirect",
                "Alamat control API MediaMTX salah",
                "MediaMTX mengalihkan permintaan ke alamat lain "
                f"(HTTP {status or 307}). Biasanya alamat control API "
                "menunjuk ke port yang salah, misalnya port WHEP 8889 "
                "atau HLS 8888, bukan port control API 9997.",
                [
                    "Buka konfigurasi API dan periksa MEDIAMTX_API_URL, "
                    "pastikan mengarah ke port control API 9997.",
                    "Hapus path tambahan di akhir URL, cukup alamat dan "
                    "port saja.",
                    "Simpan perubahan lalu restart service API.",
                    "Buka lagi halaman Diagnostik dan pastikan status "
                    "control API menjadi Terhubung.",
                ],
            )
        if kind == "auth":
            return failure_envelope(
                "mediamtx_auth",
                "Control API MediaMTX menolak kredensial",
                "Control API MediaMTX mengembalikan HTTP 401. Kredensial "
                "control API tidak cocok, atau API berjalan di mesin yang "
                "berbeda sehingga MediaMTX menolaknya karena control API "
                "hanya menerima koneksi dari localhost.",
                [
                    "Pastikan API dan MediaMTX berjalan di mesin yang sama.",
                    "Periksa password control API di pengaturan sistem, "
                    "samakan dengan yang ada di konfigurasi MediaMTX.",
                    "Periksa file mediamtx.yml, bagian api harus "
                    "mengizinkan akses dari alamat API.",
                    "Restart MediaMTX bila konfigurasi diubah, lalu "
                    "periksa lagi di halaman Diagnostik.",
                ],
            )
        if kind == "unreachable":
            return failure_envelope(
                "mediamtx_unreachable",
                "MediaMTX tidak bisa dihubungi",
                "Koneksi ke control API MediaMTX gagal atau kehabisan "
                "waktu. Service MediaMTX mungkin berhenti, atau port "
                "control API tidak terbuka.",
                [
                    "Periksa service MediaMTX sedang berjalan.",
                    "Periksa port control API 9997 terbuka di localhost.",
                    "Periksa log MediaMTX untuk error saat startup.",
                    "Jalankan ulang service MediaMTX bila perlu, lalu "
                    "periksa lagi di halaman Diagnostik.",
                ],
            )
        return failure_envelope(
            "mediamtx_http",
            "Control API MediaMTX mengembalikan error",
            f"MediaMTX mengembalikan HTTP {status or 'tidak diketahui'} "
            "saat pendaftaran path.",
            [
                "Periksa log API dan log MediaMTX untuk detail error.",
                "Periksa konfigurasi MediaMTX masih benar.",
                "Coba lagi setelah memastikan MediaMTX berjalan normal.",
            ],
        )
    # Error non-MediaMTXError (mis. dari FakeMediaMTX di test atau
    # RuntimeError lama): perlakukan sebagai tidak terjangkau, dengan
    # pesan yang sudah di-redact.
    return failure_envelope(
        "mediamtx_unreachable",
        "MediaMTX tidak bisa dihubungi",
        "Pendaftaran path ke MediaMTX gagal: "
        f"{redact_url_credentials(str(exc)) or 'error tidak diketahui'}.",
        [
            "Periksa service MediaMTX sedang berjalan.",
            "Periksa port control API 9997 terbuka di localhost.",
            "Periksa log API di server untuk detail error.",
        ],
    )


def classify_probe(status: str, peran: str = "main") -> dict | None:
    """Klasifikasikan hasil probe RTSP satu peran (main/sub).

    Mengembalikan None bila status "video" (sukses). `peran` adalah
    "main" atau "sub".
    """
    label = _PERAN.get(peran, "Stream utama")
    if status == "video":
        return None
    if status == "auth_failed":
        return failure_envelope(
            "rtsp_auth",
            f"{label} kamera menolak kredensial",
            f"{label} mengembalikan auth gagal saat probe RTSP. Username "
            "atau password salah, atau akun tidak diizinkan mengakses "
            "stream ini.",
            [
                "Periksa username dan password kamera di form Tambah Kamera.",
                "Coba login ke antarmuka web kamera dengan kredensial "
                "yang sama.",
                "Pastikan akun kamera diizinkan mengakses RTSP.",
                "Simpan ulang kamera dengan kredensial yang benar.",
            ],
        )
    if status == "not_found":
        return failure_envelope(
            "rtsp_not_found",
            "Path RTSP tidak ditemukan di kamera",
            f"{label} menjawab, tetapi path RTSP yang diminta tidak ada. "
            "Channel atau path stream salah.",
            [
                "Periksa nomor channel dan path RTSP di form Tambah Kamera.",
                "Gunakan Scanner untuk menemukan path yang benar dari "
                "kamera ini.",
                "Periksa pengaturan RTSP di antarmuka web kamera.",
                "Simpan ulang kamera dengan path yang benar.",
            ],
        )
    if status == "timeout":
        return failure_envelope(
            "rtsp_timeout",
            "Kamera tidak merespons tepat waktu",
            f"Probe RTSP {label.lower()} kehabisan waktu. Kamera mungkin "
            "mati, jaringan ke kamera putus, atau kamera membatasi jumlah "
            "sesi RTSP.",
            [
                "Periksa kamera menyala dan terhubung ke jaringan.",
                "Coba ping alamat IP kamera dari server.",
                "Tutup sesi RTSP lain ke kamera ini bila sudah penuh.",
                "Coba lagi beberapa saat kemudian.",
            ],
        )
    if status == "no_video":
        return failure_envelope(
            "rtsp_no_video",
            f"{label} tidak mengirim video",
            f"Koneksi RTSP {label.lower()} terbuka, tetapi tidak ada frame "
            "video yang diterima. Stream mungkin nonaktif di kamera atau "
            "codec tidak didukung.",
            [
                "Periksa stream sudah diaktifkan di pengaturan kamera.",
                "Periksa codec video kamera, gunakan H.264 bila tersedia.",
                "Coba path stream lain dari kamera yang sama.",
                "Simpan ulang kamera dengan URL yang mengirim video.",
            ],
        )
    return failure_envelope(
        "rtsp_error",
        "Probe RTSP gagal",
        f"Probe RTSP {label.lower()} gagal karena error yang tidak "
        "dikenal. Periksa detail di log server.",
        [
            "Periksa alamat IP, port, dan path RTSP sudah benar.",
            "Periksa log API di server untuk detail error.",
            "Coba lagi setelah memastikan kamera dapat dijangkau.",
        ],
    )


def classify_discovery(ringkasan: str) -> dict:
    """Klasifikasikan discovery yang tidak menemukan path video."""
    return failure_envelope(
        "rtsp_discovery",
        "Tidak ada path yang mengirim video",
        "Discovery mencoba semua path yang dikenal untuk brand ini, "
        f"tetapi tidak ada yang mengirim video ({ringkasan}).",
        [
            "Periksa kredensial kamera sudah benar.",
            "Pastikan RTSP diaktifkan di pengaturan kamera.",
            "Isi URL RTSP secara manual bila path kamera tidak standar.",
            "Kirim force=true beserta brand untuk tetap mendaftar tanpa "
            "verifikasi video.",
        ],
    )


def classify_resolver(message: str) -> dict:
    """Klasifikasikan ValueError dari resolver stream."""
    return failure_envelope(
        "resolve_error",
        "URL kamera tidak valid",
        redact_url_credentials(message) or "Input kamera tidak cukup.",
        [
            "Periksa format URL RTSP sudah benar.",
            "Pastikan brand yang dipilih sesuai dengan kamera.",
            "Perbaiki input lalu coba lagi.",
        ],
    )


async def record_failure(
    db: AsyncSession,
    *,
    stream_id: int | None,
    camera_name: str,
    failure: dict,
) -> CameraAddFailure:
    """Simpan satu kegagalan ke riwayat (commit sendiri).

    Dipanggil sebelum HTTPException dilempar supaya baris tetap
    tersimpan walau request berakhir 400. Tidak pernah menyimpan
    kredensial: judul/penyebab/langkah sudah di-redact di classifier.
    """
    row = CameraAddFailure(
        stream_id=stream_id,
        camera_name=(camera_name or "Tanpa nama")[:128],
        code=failure.get("code", "unknown"),
        judul=failure.get("judul", "Gagal menambah kamera")[:256],
        penyebab=failure.get("penyebab", ""),
        langkah=failure.get("langkah") or [],
    )
    db.add(row)
    await db.commit()
    return row


async def record_probe_result(
    db: AsyncSession,
    *,
    stream_id: int,
    camera_name: str,
    main_status: str,
    sub_status: str | None,
) -> CameraProbeResult:
    """Simpan (upsert) hasil probe RTSP terakhir satu kamera."""
    row = await db.get(CameraProbeResult, stream_id)
    if row is None:
        row = CameraProbeResult(
            stream_id=stream_id,
            camera_name=(camera_name or "Tanpa nama")[:128],
            main_status=main_status,
            sub_status=sub_status,
        )
        db.add(row)
    else:
        row.camera_name = (camera_name or "Tanpa nama")[:128]
        row.main_status = main_status
        row.sub_status = sub_status
    await db.commit()
    await db.refresh(row)
    return row
