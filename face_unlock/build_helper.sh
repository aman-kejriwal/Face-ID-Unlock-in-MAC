#!/bin/bash
# Builds "Face ID Unlock Helper.app" next to this script.
# Note: the helper is signed locally, without a developer certificate, so each rebuild
# counts as a new app to macOS: Accessibility and Camera must be allowed again and the
# password saved again.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/Face ID Unlock Helper.app"
ICON="$(dirname "$HERE")/face_app/AppIcon.png"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O -target arm64-apple-macos13.0 -o "$APP/Contents/MacOS/FaceIDUnlockHelper" "$HERE/helper.swift"

if [[ -f "$ICON" ]]; then
    ICONSET=$(mktemp -d)/AppIcon.iconset
    mkdir -p "$ICONSET"
    for size in 16 32 128 256 512; do
        sips -z $size $size "$ICON" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
        sips -z $((size * 2)) $((size * 2)) "$ICON" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
    done
    iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
fi

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Face ID Unlock Helper</string>
    <key>CFBundleIdentifier</key><string>local.faceidunlock.helper</string>
    <key>CFBundleExecutable</key><string>FaceIDUnlockHelper</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>LSUIElement</key><true/>
    <key>NSCameraUsageDescription</key><string>Face ID Unlock Helper checks your face when you open the lid.</string>
</dict>
</plist>
PLIST

codesign --force --sign - --identifier local.faceidunlock.helper "$APP"
echo "Built: $APP"
