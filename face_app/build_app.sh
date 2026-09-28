#!/bin/bash
# Builds "Face ID Unlock.app" in the project folder. Re-run after moving the project.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(dirname "$HERE")"
APP="$PROJECT/Face ID Unlock.app"
VENV_PY="$PROJECT/.venv/bin/python"
BASE=$("$VENV_PY" -c 'import sys; print(sys.base_prefix)')

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

clang -O2 -Wall -o "$APP/Contents/MacOS/FaceIDUnlock" "$HERE/launcher.c" \
    -I"$BASE/include/python3.11" -L"$BASE/lib" -lpython3.11 -Wl,-rpath,"$BASE/lib" -framework CoreFoundation \
    -DAPP_SCRIPT="\"$HERE/app.py\"" -DVENV_PYTHON="\"$VENV_PY\""

QT_QPA_PLATFORM=offscreen "$VENV_PY" "$HERE/make_icon.py"
ICONSET=$(mktemp -d)/AppIcon.iconset
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
    sips -z $size $size "$HERE/AppIcon.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    sips -z $((size * 2)) $((size * 2)) "$HERE/AppIcon.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Face ID Unlock</string>
    <key>CFBundleDisplayName</key><string>Face ID Unlock</string>
    <key>CFBundleIdentifier</key><string>local.faceidunlock.app</string>
    <key>CFBundleExecutable</key><string>FaceIDUnlock</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSCameraUsageDescription</key><string>Face ID Unlock uses the camera to recognise your face.</string>
    <key>NSAppleEventsUsageDescription</key><string>Face ID Unlock asks macOS for your password to change sudo settings.</string>
</dict>
</plist>
PLIST

codesign --force --sign - "$APP"
echo "Built: $APP"
