#!/usr/bin/env python3
"""Preflight check NetraVision v3.0 - dijalankan SEBELUM install.sh di server.

Hanya memakai stdlib. Setiap cek mencetak OK / GAGAL / PERINGATAN + pesan
perbaikan. Exit 0 bila tidak ada yang GAGAL (peringatan tidak menggagalkan).

Cek:
  1. biner docker
  2. plugin docker compose
  3. biner apache2
  4. port 80 & 443 di-listen oleh apache2 (bukan docker / proses lain);
     Apache yang terinstal tapi belum jalan harus dinyalakan dulu
     (`sudo systemctl enable --now apache2`) - install.sh melakukannya
     sebelum preflight
  5. disk kosong >= 10 GB di /
  6. python3 tersedia
  7. UDP 8189 (WebRTC MediaMTX): GAGAL bila sudah dipakai (biasanya
     mediamtx v2.0 - harus dihentikan sebelum `compose up` v3;
     install.sh menghentikannya di langkah 3, preflight memastikan
     port benar-benar bebas)
  8. DRIVE_TOKEN_KEY: GAGAL bila DRIVE_ENABLED=true di deploy/.env tapi
     kunci kosong/placeholder/tidak valid (aktivasi Drive akan crash
     RuntimeError tanpa kunci Fernet yang sah)
  9. WEBRTC_ADDITIONAL_HOST (D1): GAGAL bila deploy/.env ada tapi variabel
     ini kosong/placeholder, docker-compose memakai ${...:?} dan akan
     gagal di `docker compose up`. Bila .env belum ada (install.sh
     membuatnya di langkah 2), cek dilewati di sini dan install.sh
     yang mengisinya dari DOMAIN.
 10. APP_ENV / JWT_SECRET (K1): GAGAL bila APP_ENV=prod tapi JWT_SECRET
     masih placeholder/pendek (<32 karakter); PERINGATAN bila APP_ENV
     bukan prod (guard secret default tidak aktif di server publik).
 11. Sertifikat TLS: GAGAL bila sertifikat Let's Encrypt sudah kedaluwarsa;
     PERINGATAN bila <30 hari lagi. Pengecekan via openssl (cepat).
     `certbot renew --dry-run` hanya dijalankan bila
     PREFLIGHT_CERTBOT_DRY_RUN=1 (lambat + butuh jaringan).
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys

MIN_DISK_FREE_GB = 10
WEBRTC_UDP_PORT = 8189

results: list[tuple[str, str, str]] = []  # (nama, status, pesan)
# status: "OK" | "GAGAL" | "PERINGATAN"


def report(nama: str, status: str, pesan: str = "") -> None:
    results.append((nama, status, pesan))
    tag = {"OK": "[  OK  ]", "GAGAL": "[ GAGAL ]", "PERINGATAN": "[ WARN ]"}[status]
    print(f"{tag} {nama}" + (f" - {pesan}" if pesan else ""))


def hex_port(port: int) -> str:
    """22 -> '0016' (format /proc/net/tcp)."""
    return f"{port:04X}"


def find_listening_inodes(proc_net_text: str, ports: set[int]) -> dict[int, list[str]]:
    """Parse isi /proc/net/tcp[/6]; kembalikan {port: [inode, ...]} yang LISTEN (0A)."""
    wanted = {hex_port(p) for p in ports}
    found: dict[int, list[str]] = {p: [] for p in ports}
    for line in proc_net_text.splitlines():
        parts = line.split()
        if len(parts) < 10 or parts[0] == "sl":
            continue
        local, _rem, state = parts[1], parts[2], parts[3]
        if state != "0A":  # LISTEN
            continue
        try:
            port_hex = local.rsplit(":", 1)[1].upper()
            inode = parts[9]
        except IndexError:
            continue
        for p in ports:
            if port_hex == hex_port(p):
                found[p].append(inode)
    return found


def owner_of_inodes(inodes: set[str]) -> dict[str, str]:
    """Cari proses pemilik socket inode -> {inode: comm}. Butuh akses baca /proc."""
    owners: dict[str, str] = {}
    for pid in filter(str.isdigit, os.listdir("/proc")):
        fd_dir = f"/proc/{pid}/fd"
        try:
            fds = os.listdir(fd_dir)
        except (PermissionError, FileNotFoundError):
            continue
        hit = False
        for fd in fds:
            try:
                target = os.readlink(os.path.join(fd_dir, fd))
            except OSError:
                continue
            m = re.fullmatch(r"socket:\[(\d+)\]", target)
            if m and m.group(1) in inodes and m.group(1) not in owners:
                try:
                    with open(f"/proc/{pid}/comm") as f:
                        owners[m.group(1)] = f.read().strip()
                except OSError:
                    owners[m.group(1)] = f"pid-{pid}"
                hit = True
        _ = hit
    return owners


def check_port_listener_ss(port: int) -> tuple[bool, str]:
    """Coba via `ss -tlnp`; kembalikan (ditemukan, pemilik)."""
    ss = shutil.which("ss")
    if not ss:
        return False, ""
    try:
        out = subprocess.run(
            [ss, "-tlnp"], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False, ""
    for line in out.splitlines():
        m = re.search(rf"[:.]({port})\s", line)
        if not m or "LISTEN" not in line:
            continue
        pm = re.search(r'users:\(\("([^"]+)"', line)
        return True, pm.group(1) if pm else "tak-dikenal"
    return False, ""


def check_port_listener_proc(port: int) -> tuple[bool, str]:
    """Fallback tanpa `ss`: parse /proc/net/tcp + /proc/net/tcp6."""
    texts = []
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path) as f:
                texts.append(f.read())
        except OSError:
            continue
    if not texts:
        return False, ""
    inodes: set[str] = set()
    for text in texts:
        for inode in find_listening_inodes(text, {port})[port]:
            inodes.add(inode)
    if not inodes:
        return False, ""
    owners = owner_of_inodes(inodes)
    names = sorted(set(owners.values())) or ["tak-dikenal"]
    return True, ",".join(names)


def port_listener(port: int) -> tuple[bool, str]:
    found, owner = check_port_listener_ss(port)
    if found or shutil.which("ss"):
        return found, owner
    return check_port_listener_proc(port)


def check_docker() -> None:
    if shutil.which("docker"):
        report("docker terinstal", "OK")
    else:
        report(
            "docker terinstal",
            "GAGAL",
            "instal dulu: https://docs.docker.com/engine/install/",
        )


def check_compose() -> None:
    try:
        r = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            timeout=15,
        )
        if r.returncode == 0:
            report("plugin docker compose", "OK")
            return
    except (OSError, subprocess.SubprocessError):
        pass
    report(
        "plugin docker compose",
        "GAGAL",
        "instal paket 'docker-compose-plugin'.",
    )


def check_apache() -> None:
    if shutil.which("apache2"):
        report("apache2 terinstal", "OK")
    else:
        report("apache2 terinstal", "GAGAL", "server ini memakai Apache multi-virtualhost.")


def check_web_ports() -> None:
    for port in (80, 443):
        found, owner = port_listener(port)
        if not found:
            report(
                f"port {port} di-listen",
                "GAGAL",
                f"tidak ada proses listen di port {port}; pastikan Apache berjalan "
                f"(`sudo systemctl enable --now apache2`).",
            )
        elif "apache2" in owner or "httpd" in owner:
            report(f"port {port} milik apache2", "OK", f"pemilik: {owner}")
        else:
            report(
                f"port {port} milik apache2",
                "GAGAL",
                f"port {port} dipegang '{owner}' - v3.0 butuh 80/443 tetap milik Apache.",
            )


def check_disk() -> None:
    try:
        free_gb = shutil.disk_usage("/").free / (1024**3)
    except OSError as e:
        report("disk kosong >= 10 GB di /", "GAGAL", str(e))
        return
    if free_gb >= MIN_DISK_FREE_GB:
        report("disk kosong >= 10 GB di /", "OK", f"{free_gb:.1f} GB tersedia")
    else:
        report(
            "disk kosong >= 10 GB di /",
            "GAGAL",
            f"hanya {free_gb:.1f} GB tersedia; bebaskan ruang dulu.",
        )


def check_python() -> None:
    if shutil.which("python3"):
        report("python3 tersedia", "OK")
    else:
        report("python3 tersedia", "GAGAL", "instal python3 (dibutuhkan skrip deploy).")


def check_udp_webrtc() -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("0.0.0.0", WEBRTC_UDP_PORT))
        report(f"UDP {WEBRTC_UDP_PORT} bebas", "OK")
    except OSError:
        # GAGAL, bukan peringatan: `docker compose up` v3 pasti gagal
        # (port already allocated) bila mediamtx v2.0 masih memegang port ini.
        report(
            f"UDP {WEBRTC_UDP_PORT} bebas",
            "GAGAL",
            f"port sudah dipakai (kemungkinan mediamtx v2.0) - "
            f"hentikan dulu: `sudo systemctl stop mediamtx`, lalu jalankan ulang.",
        )
    finally:
        s.close()


def _read_deploy_env() -> dict[str, str]:
    """Baca deploy/.env (bila ada) sebagai dict sederhana."""
    env_path = os.path.join(os.path.dirname(__file__), "..", "deploy", ".env")
    values: dict[str, str] = {}
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
    except OSError:
        pass
    return values


def _valid_fernet_key(key: str) -> bool:
    """Kunci Fernet sah = 32 byte dalam base64 urlsafe (44 karakter)."""
    import base64

    if len(key) != 44:
        return False
    try:
        raw = base64.urlsafe_b64decode(key.encode())
    except Exception:
        return False
    return len(raw) == 32


def check_drive_token_key() -> None:
    env = _read_deploy_env()
    if not env:
        # .env belum dibuat (install.sh membuatnya di langkah 2) - lewati.
        report("DRIVE_TOKEN_KEY (bila Drive aktif)", "OK", "deploy/.env belum ada - dicek lagi setelah install.sh membuatnya")
        return
    if env.get("DRIVE_ENABLED", "false").strip().lower() != "true":
        report("DRIVE_TOKEN_KEY (bila Drive aktif)", "OK", "DRIVE_ENABLED=false - kunci tidak dibutuhkan")
        return
    key = env.get("DRIVE_TOKEN_KEY", "").strip()
    if not key or key == "CHANGE_ME_GENERATED_BY_INSTALL_SH":
        report(
            "DRIVE_TOKEN_KEY (bila Drive aktif)",
            "GAGAL",
            "DRIVE_ENABLED=true tapi DRIVE_TOKEN_KEY kosong - jalankan install.sh "
            "(ia membuatnya otomatis) atau generate manual, lihat deploy/.env.example.",
        )
    elif not _valid_fernet_key(key):
        report(
            "DRIVE_TOKEN_KEY (bila Drive aktif)",
            "GAGAL",
            "DRIVE_TOKEN_KEY tidak valid (harus base64 urlsafe 32-byte dari "
            "Fernet.generate_key()) - aktivasi Drive akan crash RuntimeError.",
        )
    else:
        report("DRIVE_TOKEN_KEY (bila Drive aktif)", "OK")


def check_webrtc_host() -> None:
    env = _read_deploy_env()
    if not env:
        # .env belum dibuat (install.sh membuatnya di langkah 2 dan
        # mengisinya dari DOMAIN) - lewati di sini.
        report("WEBRTC_ADDITIONAL_HOST terisi", "OK", "deploy/.env belum ada - diisi install.sh dari DOMAIN")
        return
    val = env.get("WEBRTC_ADDITIONAL_HOST", "").strip()
    val = val.removeprefix("https://").removeprefix("http://").rstrip("/")
    if not val or val == "CHANGE_ME_GENERATED_BY_INSTALL_SH":
        report(
            "WEBRTC_ADDITIONAL_HOST terisi",
            "GAGAL",
            "kosong di deploy/.env - docker-compose memakai ${WEBRTC_ADDITIONAL_HOST:?} "
            "dan `docker compose up` akan gagal. Isi IP/domain publik server "
            "(atau jalankan install.sh: ia mengisinya dari DOMAIN).",
        )
    elif any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-:" for c in val):
        report(
            "WEBRTC_ADDITIONAL_HOST terisi",
            "GAGAL",
            f"nilai tidak valid: '{val}' (isi IP/domain publik tanpa skema, contoh: netra.mamura.net.id).",
        )
    else:
        report("WEBRTC_ADDITIONAL_HOST terisi", "OK", val)


def check_app_env_jwt() -> None:
    env = _read_deploy_env()
    if not env:
        report("APP_ENV/JWT_SECRET", "OK", "deploy/.env belum ada - dicek lagi setelah install.sh membuatnya")
        return
    app_env = env.get("APP_ENV", "").strip() or "dev"
    secret = env.get("JWT_SECRET", "").strip()
    if app_env == "prod":
        if not secret or secret == "CHANGE_ME_GENERATED_BY_INSTALL_SH" or len(secret) < 32:
            report(
                "APP_ENV/JWT_SECRET",
                "GAGAL",
                "APP_ENV=prod tapi JWT_SECRET masih placeholder/pendek (<32 karakter) - "
                "secret default yang diketahui publik akan dipakai. Isi JWT_SECRET acak.",
            )
        else:
            report("APP_ENV/JWT_SECRET", "OK", "APP_ENV=prod, JWT_SECRET terisi (>=32 karakter)")
    else:
        report(
            "APP_ENV/JWT_SECRET",
            "PERINGATAN",
            f"APP_ENV={app_env} (bukan prod) - guard JWT_SECRET tidak aktif; "
            "jangan pakai setting ini di server publik.",
        )


def check_cert_expiry() -> None:
    """Sertifikat Let's Encrypt: gagal bila kedaluwarsa, warning bila <30 hari."""
    import datetime

    live_dir = "/etc/letsencrypt/live"
    try:
        domains = sorted(
            d for d in os.listdir(live_dir)
            if os.path.isfile(os.path.join(live_dir, d, "fullchain.pem"))
        )
    except OSError:
        domains = []
    if not domains:
        report(
            "sertifikat TLS belum kedaluwarsa",
            "PERINGATAN",
            "tidak ada sertifikat di /etc/letsencrypt/live - install.sh akan gagal "
            "dengan pesan jelas bila sertifikat domain belum dibuat (certbot).",
        )
        return
    now = datetime.datetime.now(datetime.timezone.utc)
    worst = None
    for domain in domains:
        cert = os.path.join(live_dir, domain, "fullchain.pem")
        try:
            out = subprocess.run(
                ["openssl", "x509", "-in", cert, "-noout", "-enddate"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            # Format: notAfter=Nov 18 12:00:00 2026 GMT
            end = datetime.datetime.strptime(
                out.split("=", 1)[1].strip(), "%b %d %H:%M:%S %Y %Z"
            ).replace(tzinfo=datetime.timezone.utc)
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            report("sertifikat TLS belum kedaluwarsa", "PERINGATAN",
                   f"tidak bisa membaca masa berlaku {cert} (openssl).")
            return
        days = (end - now).days
        if worst is None or days < worst[1]:
            worst = (domain, days)
    domain, days = worst
    if days < 0:
        report("sertifikat TLS belum kedaluwarsa", "GAGAL",
               f"sertifikat {domain} SUDAH kedaluwarsa ({-days} hari lalu) - perbarui: certbot renew.")
    elif days < 30:
        report("sertifikat TLS belum kedaluwarsa", "PERINGATAN",
               f"sertifikat {domain} kedaluwarsa dalam {days} hari - jalankan: certbot renew.")
    else:
        report("sertifikat TLS belum kedaluwarsa", "OK", f"{domain}: {days} hari lagi")
    # Dry-run certbot hanya bila diminta eksplisit (lambat + butuh jaringan).
    if os.environ.get("PREFLIGHT_CERTBOT_DRY_RUN") == "1" and shutil.which("certbot"):
        try:
            r = subprocess.run(
                ["certbot", "renew", "--dry-run"],
                capture_output=True, text=True, timeout=300,
            )
            report("certbot renew --dry-run", "OK" if r.returncode == 0 else "PERINGATAN",
                   "lolos" if r.returncode == 0 else "gagal - periksa output certbot manual.")
        except (OSError, subprocess.SubprocessError) as e:
            report("certbot renew --dry-run", "PERINGATAN", str(e))


def main() -> int:
    print("NetraVision v3.0 - preflight check\n")
    check_docker()
    check_compose()
    check_apache()
    check_web_ports()
    check_disk()
    check_python()
    check_udp_webrtc()
    check_drive_token_key()
    check_webrtc_host()
    check_app_env_jwt()
    check_cert_expiry()

    gagal = sum(1 for _, st, _ in results if st == "GAGAL")
    print()
    if gagal:
        print(f"HASIL: {gagal} cek GAGAL - perbaiki dulu sebelum install.sh.")
        return 1
    print("HASIL: semua cek penting OK - aman lanjut ke install.sh.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
