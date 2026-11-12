#!/usr/bin/env bash
# Build a self-contained Linux AppImage for TurboPad.
#
# Usage:
#   ./packaging/build_appimage.sh [output.AppImage]
#
# The first run creates .build-venv (PyInstaller + runtime dependencies) and
# downloads appimagetool into ~/.cache/turbopad.  Override the tool with
# APPIMAGETOOL=/path/to/appimagetool.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUTPUT="${1:-$ROOT/TurboPad-x86_64.AppImage}"
VENV="$ROOT/.build-venv"
PYTHON="${PYTHON:-python3}"
TOOL="${APPIMAGETOOL:-${XDG_CACHE_HOME:-$HOME/.cache}/turbopad/appimagetool-x86_64.AppImage}"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "==> creating build environment"
  "$PYTHON" -m venv "$VENV"
fi

echo "==> installing build dependencies"
"$VENV/bin/pip" -q install --upgrade pip
"$VENV/bin/pip" -q install -r requirements.txt pyinstaller

echo "==> generating icon"
"$VENV/bin/python" packaging/make_icon.py

echo "==> freezing the application"
"$VENV/bin/pyinstaller" \
  --noconfirm \
  --clean \
  --windowed \
  --name TurboPad \
  --add-data "assets:assets" \
  --hidden-import "PIL._tkinter_finder" \
  --collect-submodules pynput \
  --collect-submodules pygame \
  run.py

echo "==> assembling AppDir"
rm -rf AppDir
mkdir -p \
  AppDir/usr/bin \
  AppDir/usr/share/applications \
  AppDir/usr/share/icons/hicolor/512x512/apps
cp -a dist/TurboPad/. AppDir/usr/bin/
install -m 644 packaging/turbopad.png AppDir/turbopad.png
install -m 644 packaging/turbopad.png \
  AppDir/usr/share/icons/hicolor/512x512/apps/turbopad.png
install -m 644 packaging/turbopad.desktop AppDir/turbopad.desktop
install -m 644 packaging/turbopad.desktop \
  AppDir/usr/share/applications/turbopad.desktop

cat > AppDir/AppRun <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/TurboPad" "$@"
APPRUN
chmod 755 AppDir/AppRun

if [[ ! -x "$TOOL" ]]; then
  echo "==> downloading appimagetool"
  mkdir -p "$(dirname "$TOOL")"
  curl -fsSL -o "$TOOL" \
    "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
  chmod +x "$TOOL"
fi

echo "==> packaging $OUTPUT"
ARCH=x86_64 "$TOOL" --no-appstream AppDir "$OUTPUT"

echo
echo "Built: $OUTPUT"
