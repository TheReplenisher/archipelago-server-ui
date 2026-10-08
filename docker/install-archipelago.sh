#!/bin/sh
# Install Archipelago's server and generator requirements into a venv, as AP's own
# ModuleUpdate.py would (core requirements, then each world's file constrained by core),
# minus what a headless server never uses:
#   kivy, kivymd           desktop GUI
#   dolphin-memory-engine  The Wind Waker's game client only (TWWClient.py); no arm64 wheel
# Usage: install-archipelago.sh <archipelago source dir> <venv python>
set -eu

src=$1
python=$2
exclude='^(kivy|kivymd|dolphin-memory-engine)([^a-z0-9_.-]|$)'
tmp=$(mktemp -d)

grep -viE "$exclude" "$src/requirements.txt" > "$tmp/core.txt"
# Two packages a normal install has without listing them, and that built-in worlds import:
#   requests    arrives through kivy (Kivy-Garden); used by ffmq, messenger, osrs, sm
#   setuptools  ModuleUpdate installs "setuptools>=75,<81" for pkg_resources (pokemon_emerald)
cat >> "$tmp/core.txt" <<'REQ'
requests
setuptools>=75,<81
REQ
uv pip install --python "$python" -r "$tmp/core.txt"

# One install per file: soe's file uses hashes, which pip/uv then require of every line.
for req in "$src"/worlds/*/requirements.txt; do
    grep -viE "$exclude" "$req" > "$tmp/world.txt" || continue  # nothing left after excluding
    uv pip install --python "$python" -r "$tmp/world.txt" --constraint "$tmp/core.txt"
done

# C speedups, built now so nothing is compiled at runtime.
cd "$src"
"$(dirname "$python")/cythonize" -b -i -q _speedups.pyx
rm -rf build _speedups.c _speedups.cpp _speedups.pyx _speedups.pyxbld
rm -rf "$tmp"

# A read-only install makes AP use $HOME/.local/share/Archipelago as its user folder,
# which it seeds by copying these from the install (Utils.user_path). A git checkout
# lacks Players/, so create it as an installer would.
mkdir -p Players data/sprites data/lua
