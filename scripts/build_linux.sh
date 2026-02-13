#!/usr/bin/env bash
# Build RetroSpecs as a standalone Linux binary using PyInstaller.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Ensure PyInstaller is available
pip install --quiet pyinstaller

pyinstaller \
    --onefile \
    --name retrospecs \
    --windowed \
    --hidden-import=OpenGL.platform.egl \
    --hidden-import=OpenGL.platform.glx \
    --add-data "retrospecs:retrospecs" \
    retrospecs/__main__.py

echo ""
echo "Build complete: dist/retrospecs"
