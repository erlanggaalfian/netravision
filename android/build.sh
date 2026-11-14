#!/usr/bin/env bash
# Build APK release NetraVision TANPA Gradle.
# Alasan: Gradle tidak bisa jalan di VM ini karena sandbox memblokir
# koneksi TCP localhost antar proses Java (komunikasi client-daemon
# Gradle), sehingga daemon selalu gagal ("Unexpected type tag 109").
# Build ini hanya memakai aapt2 + javac + d8 + zipalign + apksigner
# (semua pemrosesan file lokal, tanpa jaringan dan tanpa daemon).
# Jalankan dari direktori android/ :  ./build.sh
# Hasil: app/build/outputs/apk/release/netravision-release.apk
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk-amd64}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Android/Sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
BT="$ANDROID_HOME/build-tools/34.0.0"
PLATFORM="$ANDROID_HOME/platforms/android-35"
APP_ID="id.mamura.netravision"
VERSION_NAME="1.0.0"
VERSION_CODE="1"

OUT="$SCRIPT_DIR/app/build/outputs/apk/release"
WORK="$SCRIPT_DIR/app/build/tmp-manual"
rm -rf "$WORK" "$OUT"
mkdir -p "$WORK/compiled" "$WORK/classes" "$WORK/dex" "$OUT"

echo "== 1. aapt2 compile resources =="
"$BT/aapt2" compile --dir app/src/main/res -o "$WORK/compiled.zip"

echo "== 2. aapt2 link (APK tanpa dex) =="
"$BT/aapt2" link -o "$WORK/base.apk" \
    --manifest app/src/main/AndroidManifest.xml \
    -I "$PLATFORM/android.jar" \
    --auto-add-overlay \
    --version-code "$VERSION_CODE" \
    --version-name "$VERSION_NAME" \
    --java "$WORK/gen" \
    "$WORK/compiled.zip"

echo "== 3. javac MainActivity =="
"$JAVA_HOME/bin/javac" -source 8 -target 8 -nowarn \
    -cp "$PLATFORM/android.jar" \
    -d "$WORK/classes" \
    app/src/main/java/id/mamura/netravision/MainActivity.java

echo "== 4. d8 -> classes.dex =="
(cd "$WORK/classes" && "$JAVA_HOME/bin/jar" --create --file "$WORK/app.jar" .)
"$BT/d8" --lib "$PLATFORM/android.jar" --output "$WORK/dex" "$WORK/app.jar"

echo "== 5. tambah classes.dex ke APK (tanpa kompresi) =="
python3 - "$WORK/base.apk" "$WORK/dex/classes.dex" <<'PYEOF'
import sys, zipfile
apk, dex = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(apk, "a", zipfile.ZIP_DEFLATED) as z:
    z.write(dex, "classes.dex", compress_type=zipfile.ZIP_STORED)
print("dex ditambahkan")
PYEOF

echo "== 6. zipalign =="
"$BT/zipalign" -v -p 4 "$WORK/base.apk" "$WORK/aligned.apk" >/dev/null

echo "== 7. apksigner sign =="
STORE_PASS="$(grep '^storePassword=' keystore.properties | cut -d= -f2-)"
KEY_PASS="$(grep '^keyPassword=' keystore.properties | cut -d= -f2-)"
KEY_ALIAS="$(grep '^keyAlias=' keystore.properties | cut -d= -f2-)"
PASSFILE="$(mktemp)"
printf '%s' "$STORE_PASS" > "$PASSFILE"
KEYPASSFILE="$(mktemp)"
printf '%s' "$KEY_PASS" > "$KEYPASSFILE"
trap 'rm -f "$PASSFILE" "$KEYPASSFILE"' EXIT
"$BT/apksigner" sign \
    --ks netravision-release.keystore \
    --ks-key-alias "$KEY_ALIAS" \
    --ks-pass "file:$PASSFILE" \
    --key-pass "file:$KEYPASSFILE" \
    --out "$OUT/netravision-release.apk" \
    "$WORK/aligned.apk"

echo "== 8. verifikasi =="
"$BT/apksigner" verify --verbose "$OUT/netravision-release.apk"
"$BT/aapt2" dump badging "$OUT/netravision-release.apk" | grep -E "^package:|^uses-permission:" || true
ls -la "$OUT/netravision-release.apk"
sha256sum "$OUT/netravision-release.apk"
echo "SELESAI: $OUT/netravision-release.apk"
