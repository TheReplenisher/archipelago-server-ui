#!/bin/sh
# Smoke-test a built image: the web service answers, and Archipelago is the pinned
# version, headless, with its speedups and every built-in world importable.
# Usage: smoke-test.sh <image> <expected AP version>     (CONTAINER=podman to use podman)
set -eu

image=$1
ap_version=$2
engine=${CONTAINER:-docker}
name=apsui-smoke-$$
port=${SMOKE_PORT:-18000}

cleanup() { "$engine" rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "--- web service"
"$engine" run -d --name "$name" -p "127.0.0.1:$port:8000" "$image" >/dev/null
for _ in $(seq 30); do
    curl -fsS "http://127.0.0.1:$port/api/health" >/dev/null 2>&1 && break
    sleep 1
done
curl -fsS "http://127.0.0.1:$port/api/health" | grep -q '"status":"ok"'
curl -fsS "http://127.0.0.1:$port/admin" | grep -q '<div id="root">'

echo "--- archipelago (no network, read-only; /data writable, as the volume would be)"
"$engine" run --rm -i --network none --read-only --tmpfs /tmp --tmpfs /data:mode=1777 \
    --workdir /opt/archipelago --entrypoint /opt/archipelago-venv/bin/python \
    -e EXPECTED_AP_VERSION="$ap_version" "$image" - <<'PY'
import importlib.util
import os
import sys

sys.path.insert(0, "/opt/archipelago")
import NetUtils
import Utils

assert Utils.__version__ == os.environ["EXPECTED_AP_VERSION"], Utils.__version__
assert NetUtils.LocationStore.__module__ == "_speedups", "speedups not compiled"
for gui in ("kivy", "kivymd"):
    assert importlib.util.find_spec(gui) is None, f"{gui} should not be installed"

import worlds

if worlds.failed_world_loads:
    sys.exit(f"worlds failed to load: {worlds.failed_world_loads}")
print(f"Archipelago {Utils.__version__}: {len(worlds.AutoWorldRegister.world_types)} worlds load")
PY

echo "smoke test passed"
