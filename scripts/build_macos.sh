#!/usr/bin/env bash
# Build RetroSpecs as a macOS .app bundle using PyInstaller.
#
# Supports macOS 10.13 (High Sierra) through macOS 26 (Tahoe).
#
# Usage:  ./scripts/build_macos.sh
# Output: dist/RetroSpecs.app
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Ensure PyInstaller and runtime dependencies are available
pip3 install --quiet pyinstaller PyQt5 PyOpenGL numpy mss

# Write the Info.plist with screen-capture and camera usage descriptions
# so macOS will show the permission prompt instead of silently denying.
cat > retrospecs/Info.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDisplayName</key>
    <string>RetroSpecs</string>
    <key>CFBundleIdentifier</key>
    <string>com.retrospecs.retrospecs</string>
    <key>CFBundleName</key>
    <string>RetroSpecs</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundleVersion</key>
    <string>1.0.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
    <key>NSScreenCaptureUsageDescription</key>
    <string>RetroSpecs needs screen recording access to capture the desktop and apply CRT shader effects.</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSUIElement</key>
    <false/>
</dict>
</plist>
PLIST

# macOS uses the CGL (Core OpenGL) platform in PyOpenGL.
# --onedir + --windowed produces a proper .app bundle.
pyinstaller \
    --onedir \
    --name RetroSpecs \
    --windowed \
    --hidden-import=OpenGL.platform.darwin \
    --hidden-import=OpenGL.platform.ctypesloader \
    --add-data "retrospecs:retrospecs" \
    --osx-bundle-identifier com.retrospecs.retrospecs \
    retrospecs/__main__.py

# Replace the auto-generated Info.plist with ours (adds permission keys)
cp retrospecs/Info.plist dist/RetroSpecs.app/Contents/Info.plist

# Clean up the working plist
rm retrospecs/Info.plist

echo ""
echo "Build complete: dist/RetroSpecs.app"
echo ""
echo "To install, drag RetroSpecs.app into /Applications."
