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

echo "--- worker: a ping and a list-worlds job (no network, read-only)"
jobs=$(mktemp -d)
chmod 777 "$jobs"
trap 'cleanup; rm -rf "$jobs" 2>/dev/null || true' EXIT
"$engine" run --rm -i -v "$jobs:/jobs:Z" --entrypoint /opt/archipelago-venv/bin/python "$image" - <<'PY'
from pathlib import Path
from apsui_worker.protocol import INPUT_DIR, SPEC_FILE, JobDirs, JobSpec, State, new_job_id, now, write_json_atomic

dirs = JobDirs(Path("/jobs"))
dirs.ensure()
for job_type in ("ping", "list-worlds"):
    job_id = new_job_id()
    tmp = dirs.path(State.TMP, job_id)
    (tmp / INPUT_DIR).mkdir(parents=True)
    spec = JobSpec(id=job_id, type=job_type, params={}, timeout=300, submitted_at=now())
    write_json_atomic(tmp / SPEC_FILE, spec.to_json())
    tmp.rename(dirs.path(State.QUEUE, job_id))
PY
"$engine" run --rm --network none --read-only --tmpfs /tmp -v "$jobs:/jobs:Z" \
    "$image" apsui-worker --jobs-dir /jobs --once
"$engine" run --rm -i -v "$jobs:/jobs:Z" --entrypoint /opt/archipelago-venv/bin/python \
    -e EXPECTED_AP_VERSION="$ap_version" "$image" - <<'PY'
import os
import sys
from pathlib import Path
from apsui_worker.protocol import RESULT_FILE, JobDirs, JobResult, State, read_json_file

dirs = JobDirs(Path("/jobs"))
results = {
    r.type: r
    for r in (JobResult.from_json(read_json_file(dirs.path(State.DONE, i) / RESULT_FILE))
              for i in dirs.ids(State.DONE))
}
for job_type in ("ping", "list-worlds"):
    if results.get(job_type) is None or results[job_type].status != "ok":
        sys.exit(f"{job_type} job failed: {results.get(job_type)}")
out = results["list-worlds"].output
assert out["archipelago_version"] == os.environ["EXPECTED_AP_VERSION"], out["archipelago_version"]
assert not out["failed"], out["failed"]
builtin = [w for w in out["worlds"] if w["builtin"]]
print(f"worker: list-worlds found {len(builtin)} built-in games")
PY

echo "--- worker: validate-yaml against the sample YAMLs (worker/tests/yaml)"
yamls=$(cd "$(dirname "$0")/../worker/tests/yaml" && pwd)
jobs=$(mktemp -d)  # a fresh queue; the earlier jobs stay behind in the first one
chmod 777 "$jobs"
"$engine" run --rm -i -v "$jobs:/jobs:Z" -v "$yamls:/yamls:ro,Z" \
    --entrypoint /opt/archipelago-venv/bin/python "$image" - <<'PY'
import shutil
from pathlib import Path
from apsui_worker.protocol import INPUT_DIR, SPEC_FILE, JobDirs, JobSpec, State, new_job_id, now, write_json_atomic

dirs = JobDirs(Path("/jobs"))
dirs.ensure()
for sample in sorted(Path("/yamls").glob("*.yaml")):
    job_id = new_job_id()
    tmp = dirs.path(State.TMP, job_id)
    (tmp / INPUT_DIR).mkdir(parents=True)
    shutil.copy(sample, tmp / INPUT_DIR / "upload.yaml")
    spec = JobSpec(id=job_id, type="validate-yaml", params={"sample": sample.name},
                   timeout=120, submitted_at=now())
    write_json_atomic(tmp / SPEC_FILE, spec.to_json())
    tmp.rename(dirs.path(State.QUEUE, job_id))
PY
"$engine" run --rm --network none --read-only --tmpfs /tmp -v "$jobs:/jobs:Z" \
    "$image" apsui-worker --jobs-dir /jobs --once 2>/dev/null
"$engine" run --rm -i -v "$jobs:/jobs:Z" --entrypoint /opt/archipelago-venv/bin/python "$image" - <<'PY'
import sys
from pathlib import Path
from apsui_worker.protocol import RESULT_FILE, SPEC_FILE, JobDirs, JobResult, State, read_json_file

dirs = JobDirs(Path("/jobs"))
failures = []
for job_id in dirs.ids(State.DONE):
    sample = read_json_file(dirs.path(State.DONE, job_id) / SPEC_FILE)["params"]["sample"]
    expected = sample.split("__")[0]
    result = JobResult.from_json(read_json_file(dirs.path(State.DONE, job_id) / RESULT_FILE))
    if result.status != "ok":
        failures.append(f"{sample}: job {result.status}: {result.error}")
        continue
    out = result.output
    errors = [out["error"]] if out["error"] else []
    for d in out["documents"]:  # a document's own error first, then a name problem
        errors += [e for e in (d.get("error"), d.get("name_error")) if e]
    got = errors[0]["code"] if errors else "ok"
    print(f"  {sample}: {got}" + (f" ({errors[0]['message']})" if errors else ""))
    if got != expected:
        failures.append(f"{sample}: expected {expected}, got {got}: {errors}")
if failures:
    sys.exit("\n".join(failures))
PY

echo "smoke test passed"
