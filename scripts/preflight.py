#!/usr/bin/env python3
"""Preflight check NetraVision v3.0 — dijalankan SEBELUM install.sh di server.

Hanya memakai stdlib. Setiap cek mencetak OK / GAGAL / PERINGATAN + pesan
perbaikan. Exit 0 bila tidak ada yang GAGAL (peringatan tidak menggagalkan).

Cek:
  1. biner docker
  2. plugin docker compose
  3. biner apache2
  4. port 80 & 443 di-listen oleh apache2 (bukan docker / proses lain)
  5. disk kosong >= 10 GB di /
  6. python3 tersedia
  7. UDP 8189 (WebRTC MediaMTX): PERINGATAN bila sudah dipakai
     (biasanya mediamtx v2.0 — harus dihentikan sebelum `compose up` v3)
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
    print(f"{tag} {nama}" + (f" — {pesan}" if pesan else ""))


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
                f"tidak ada proses listen di port {port}; pastikan Apache berjalan.",
            )
        elif "apache2" in owner or "httpd" in owner:
            report(f"port {port} milik apache2", "OK", f"pemilik: {owner}")
        else:
            report(
                f"port {port} milik apache2",
                "GAGAL",
                f"port {port} dipegang '{owner}' — v3.0 butuh 80/443 tetap milik Apache.",
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
        report(
            f"UDP {WEBRTC_UDP_PORT} bebas",
            "PERINGATAN",
            f"port sudah dipakai (kemungkinan mediamtx v2.0) — "
            f"hentikan mediamtx v2.0 sebelum 'docker compose up' v3.",
        )
    finally:
        s.close()


def main() -> int:
    print("NetraVision v3.0 — preflight check\n")
    check_docker()
    check_compose()
    check_apache()
    check_web_ports()
    check_disk()
    check_python()
    check_udp_webrtc()

    gagal = sum(1 for _, st, _ in results if st == "GAGAL")
    print()
    if gagal:
        print(f"HASIL: {gagal} cek GAGAL — perbaiki dulu sebelum install.sh.")
        return 1
    print("HASIL: semua cek penting OK — aman lanjut ke install.sh.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
