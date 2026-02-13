#!/usr/bin/env bash
# Build the RetroSpecs .deb package.
#
# Usage:  ./scripts/build_deb.sh
# Output: build/retrospecs_1.0.0-1_all.deb
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PKG="retrospecs"
VERSION="1.0.0-1"
ARCH="all"
BUILD_DIR="$PROJECT_DIR/build/${PKG}_${VERSION}_${ARCH}"

echo "==> Cleaning previous build"
rm -rf "$BUILD_DIR" "$PROJECT_DIR/build/${PKG}_${VERSION}_${ARCH}.deb"

echo "==> Creating directory tree"
mkdir -p "$BUILD_DIR"/{DEBIAN,opt/retrospecs/retrospecs,opt/retrospecs/vendor,usr/bin,usr/share/applications}

echo "==> Copying application source"
cp "$PROJECT_DIR"/retrospecs/*.py "$BUILD_DIR/opt/retrospecs/retrospecs/"

echo "==> Vendoring mss library"
MSS_SRC="$(python3 -c 'import mss, os; print(os.path.dirname(mss.__file__))')"
cp -r "$MSS_SRC" "$BUILD_DIR/opt/retrospecs/vendor/mss"
find "$BUILD_DIR/opt/retrospecs/vendor" -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

echo "==> Patching mss for Python 3.6–3.8 compatibility"
# models.py uses dict[], list[], tuple[] (Python 3.9+) at module level;
# replace with typing equivalents so the aliases work at runtime.
python3 -c "
import pathlib, re

vendor = pathlib.Path('$BUILD_DIR/opt/retrospecs/vendor/mss')

# --- models.py: fix runtime type aliases ---
models = vendor / 'models.py'
src = models.read_text()
src = src.replace('from typing import Any, NamedTuple',
                  'from typing import Any, Dict, List, NamedTuple, Tuple')
src = src.replace('Monitor = dict[str, int]',      'Monitor = Dict[str, int]')
src = src.replace('Monitors = list[Monitor]',       'Monitors = List[Monitor]')
src = src.replace('Pixel = tuple[int, int, int]',   'Pixel = Tuple[int, int, int]')
src = src.replace('Pixels = list[tuple[Pixel, ...]]','Pixels = List[Tuple[Pixel, ...]]')
src = re.sub(
    r'CFunctions = dict\[str, tuple\[str, list\[Any\], Any\]\]',
    'CFunctions = Dict[str, Tuple[str, List[Any], Any]]',
    src,
)
models.write_text(src)

# --- all .py files: add 'from __future__ import annotations' ---
# This makes function annotations lazy strings, fixing dict[], X | Y, etc.
for py in vendor.glob('*.py'):
    text = py.read_text()
    if 'from __future__ import annotations' in text:
        continue
    # Insert after the module docstring or at the very top
    lines = text.split('\n')
    insert_at = 0
    # Skip shebang
    if lines and lines[0].startswith('#!'):
        insert_at = 1
    # Skip module docstring
    if insert_at < len(lines):
        stripped = lines[insert_at].strip()
        if stripped.startswith('\"\"\"'):
            if stripped.endswith('\"\"\"') and stripped.count('\"\"\"') >= 2:
                insert_at += 1
            else:
                for j in range(insert_at + 1, len(lines)):
                    if '\"\"\"' in lines[j]:
                        insert_at = j + 1
                        break
    lines.insert(insert_at, 'from __future__ import annotations')
    py.write_text('\n'.join(lines))

print('  patched', len(list(vendor.glob('*.py'))), 'files')
"

echo "==> Writing DEBIAN/control"
cat > "$BUILD_DIR/DEBIAN/control" <<'CTRL'
Package: retrospecs
Version: 1.0.0-1
Section: graphics
Priority: optional
Architecture: all
Depends: python3 (>= 3.6),
 python3-pyqt5,
 python3-pyqt5.qtopengl,
 python3-opengl,
 python3-numpy,
 libxext6,
 libgl1-mesa-glx | libgl1,
 libxrandr2,
 x11-utils
Recommends: python3-mss, libgl1-mesa-dri
Maintainer: RetroSpecs <retrospecs@localhost>
Homepage: https://github.com/retrospecs
Description: CRT shader overlay for your desktop
 RetroSpecs creates a transparent, always-on-top, click-through window
 that captures what is behind it and re-renders it with selectable CRT
 shader effects.  Clicks pass straight through the overlay to whatever
 is underneath.
 .
 Includes 5 shaders: basic scanlines, CRT curvature, phosphor grid,
 aperture grille, and retro green phosphor.
 .
 Supports Ubuntu 18.04 through 24.04 and Windows 10/11.
CTRL

echo "==> Writing launcher"
cat > "$BUILD_DIR/usr/bin/retrospecs" <<'LAUNCHER'
#!/usr/bin/env python3
"""Launcher for RetroSpecs — adds vendored deps to sys.path."""
import sys
import os

vendor_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'opt', 'retrospecs', 'vendor')
vendor_dir = os.path.normpath(vendor_dir)
if vendor_dir not in sys.path:
    sys.path.insert(0, vendor_dir)

app_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'opt', 'retrospecs')
app_dir = os.path.normpath(app_dir)
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

from retrospecs.app import main
sys.exit(main())
LAUNCHER
chmod 755 "$BUILD_DIR/usr/bin/retrospecs"

echo "==> Writing desktop entry"
cat > "$BUILD_DIR/usr/share/applications/retrospecs.desktop" <<'DESKTOP'
[Desktop Entry]
Name=RetroSpecs
Comment=CRT shader overlay for your desktop
Exec=retrospecs
Type=Application
Categories=Graphics;Utility;
Terminal=false
DESKTOP

echo "==> Setting permissions"
chmod 755 "$BUILD_DIR/DEBIAN"
find "$BUILD_DIR/opt" -type d -exec chmod 755 {} +
find "$BUILD_DIR/opt" -type f -exec chmod 644 {} +
find "$BUILD_DIR/usr" -type d -exec chmod 755 {} +
chmod 755 "$BUILD_DIR/usr/bin/retrospecs"

echo "==> Building .deb"
dpkg-deb --build --root-owner-group "$BUILD_DIR"

echo ""
echo "Done: build/${PKG}_${VERSION}_${ARCH}.deb"
dpkg-deb -I "$BUILD_DIR.deb"
