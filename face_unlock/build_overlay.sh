#!/bin/bash
# Builds "Face ID Unlock Overlay.app" (the Liquid Glass scan animation) next to this script.
# It needs no permissions, so rebuilding it never affects the helper's Accessibility or
# Keychain access. The helper starts it; after a rebuild, restart the helper to pick it up.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/Face ID Unlock Overlay.app"
ICON="$(dirname "$HERE")/face_app/AppIcon.png"

pkill -f "Face ID Unlock Overlay.app/Contents/MacOS/FaceIDUnlockOverlay" 2>/dev/null || true
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O -parse-as-library -target arm64-apple-macos13.0 -o "$APP/Contents/MacOS/FaceIDUnlockOverlay" \
    "$HERE/overlay_main.swift" "$HERE/overlay.swift"

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
    <key>CFBundleName</key><string>Face ID Unlock Overlay</string>
    <key>CFBundleIdentifier</key><string>local.faceidunlock.overlay</string>
    <key>CFBundleExecutable</key><string>FaceIDUnlockOverlay</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST

codesign --force --sign - --identifier local.faceidunlock.overlay "$APP"
echo "Built: $APP"
