# NetraVision Android (APK)

APK Android asli untuk NetraVision. Aplikasi ini hanya sebuah WebView
yang memuat situs live https://netra.mamura.net.id/, jadi update web
langsung terpikul tanpa rebuild APK.

- appId: `id.mamura.netravision`
- Versi: 1.0.0 (versionCode 1)
- Ikon launcher: dari `apps/web/public/icons/icon-512.png`

## Kenapa native WebView, bukan Capacitor/Gradle

Proyek Capacitor sempat dibuat di `apps/android/`, tetapi Gradle tidak
bisa jalan di VM ini: sandbox memblokir koneksi TCP localhost antar
proses Java, sehingga komunikasi client-daemon Gradle selalu gagal
("Could not receive a message from the daemon", "Unexpected type tag
109"). Proyek Capacitor itu sudah dihapus. Proyek native ini tidak
memakai Gradle dan tidak punya dependensi eksternal (tanpa androidx),
sehingga bisa dibangun hanya dengan aapt2 + javac + d8 + zipalign +
apksigner.

## Build

Butuh OpenJDK 17 dan Android SDK (platform-tools, platform android-35,
build-tools 34.0.0). SDK dicari di `$ANDROID_HOME` (default
`~/Android/Sdk`).

```sh
./build.sh
```

Hasil: `app/build/outputs/apk/release/netravision-release.apk`
(disertai verifikasi `apksigner verify` dan `aapt2 dump badging`).

## Signing

Keystore release: `netravision-release.keystore` (alias `netravision`,
RSA 2048, berlaku 10000 hari). Kata sandi ada di `keystore.properties`
(izin 600, TIDAK di-commit). Jangan pernah commit keystore maupun
`keystore.properties`; keduanya sudah di `.gitignore`.

## Download

APK hasil build disalin ke `apps/web/public/netravision.apk` supaya
ikut ter-deploy bersama frontend dan bisa diunduh dari
https://netra.mamura.net.id/netravision.apk. Tombol "Download APK"
ada di halaman login (di bawah tombol Masuk/Guest).
