#!/bin/sh
# Bring up compose.yaml with a given image and check that it works and that each
# service's isolation holds (DESIGN.md §2, #13).
# Usage: compose-test.sh <image>       (COMPOSE="podman compose" etc. to override)
set -eu

export APSUI_IMAGE="$1"
export APSUI_WEB_PORT="${APSUI_WEB_PORT:-18080}"
export APSUI_GAME_PORT="${APSUI_GAME_PORT:-48281}"
project="apsui-test-$$"
here=$(cd "$(dirname "$0")/.." && pwd)
compose() { ${COMPOSE:-docker compose} -p "$project" -f "$here/compose.yaml" "$@"; }
py() { service=$1; shift; compose exec -T "$service" /opt/archipelago-venv/bin/python - "$@"; }

cleanup() {
    status=$?
    if [ "$status" -ne 0 ]; then compose logs --no-color --tail 50 || true; fi
    compose down -v --timeout 5 >/dev/null 2>&1 || true
    exit "$status"
}
trap cleanup EXIT

echo "--- start the stack and wait for every healthcheck"
compose up -d --wait --wait-timeout 120

echo "--- web answers on the published port"
curl -fsS "http://127.0.0.1:$APSUI_WEB_PORT/api/health" | grep -q '"status":"ok"'

echo "--- web reaches the server supervisor over the control socket"
curl -fsS "http://127.0.0.1:$APSUI_WEB_PORT/api/server" | grep -q '"reachable":true'

echo "--- a job goes web -> worker -> web"
compose exec -T web python - <<'PY'
import time
from apsui.config import get_settings
from apsui.db import make_engine, make_sessionmaker
from apsui.jobs import JobQueue
from apsui.models import Job

settings = get_settings()
sessions = make_sessionmaker(make_engine(settings.database_url))
with sessions() as session:
    job_id = JobQueue(settings.resolved_jobs_dir).submit(session, "ping").id
for _ in range(60):  # the web service's own collector records the result
    with sessions() as session:
        job = session.get(Job, job_id)
        if job is not None and job.status not in ("queued", "running"):
            break
    time.sleep(0.5)
assert job is not None and job.status == "ok", (job.status if job else None, job and job.result)
print("ping job: ok")
PY

echo "--- YAML uploads: web -> worker (real Archipelago) -> slots"
base="http://127.0.0.1:$APSUI_WEB_PORT/api"
wait_checked() {
    for _ in $(seq 60); do
        curl -fsS "$base/uploads" | grep -q '"status":"pending"' || return 0
        sleep 1
    done
    echo "uploads still pending"; exit 1
}
for sample in ok__weighted option-invalid__bad-choice name-not-fixed__weighted-name; do
    curl -fsS -F "file=@$here/worker/tests/yaml/$sample.yaml" "$base/uploads/yaml" >/dev/null
done
wait_checked
uploads=$(curl -fsS "$base/uploads")
echo "$uploads" | grep -q '"filename":"ok__weighted.yaml","status":"accepted"' \
    || { echo "weighted YAML not accepted: $uploads"; exit 1; }
echo "$uploads" | grep -q '"error_code":"option-invalid"' \
    || { echo "bad option not rejected: $uploads"; exit 1; }
echo "$uploads" | grep -q '"status":"needs-name"' \
    || { echo "weighted name not waiting for a name: $uploads"; exit 1; }

echo "--- rename a weighted name on the spot; the edited YAML is checked again by real AP"
waiting=$(echo "$uploads" | python3 -c 'import json,sys; print(next(u["id"] for u in json.load(sys.stdin) if u["status"] == "needs-name"))')
curl -fsS -H 'Content-Type: application/json' -d '{"names":[{"document":0,"name":"Alice"}]}' \
    "$base/uploads/$waiting/rename" >/dev/null
wait_checked
slots=$(curl -fsS "$base/slots")
echo "$slots" | grep -q '"name":"Quester"' && echo "$slots" | grep -q '"name":"Alice"' \
    || { echo "slots after rename: $slots"; exit 1; }
echo "uploads: ok"

echo "--- apworlds: inspected by web, import-tested by the worker (real AP), approved"
apworlds=$(mktemp -d)
for sample in "$here"/worker/tests/apworld/*/; do
    module=$(basename "$sample" | sed 's/.*__//')
    (cd "$sample" && mkdir -p "$apworlds/src/$module" && cp ./* "$apworlds/src/$module/")
    (cd "$apworlds/src" && python3 -m zipfile -c "$apworlds/$module.apworld" "$module")
    curl -fsS -F "file=@$apworlds/$module.apworld" "$base/apworlds" >/dev/null
done
for _ in $(seq 60); do
    curl -fsS "$base/apworlds" | grep -q '"status":"checking"' || break
    sleep 1
done
listing=$(curl -fsS "$base/apworlds")
status_of() { echo "$listing" | python3 -c 'import json,sys; print(next(a["status"] + ":" + str(a["replaces_builtin"]) for a in json.load(sys.stdin) if a["filename"] == sys.argv[1]))' "$1"; }
[ "$(status_of apsui_test_world.apworld)" = "pending:None" ] || { echo "test world: $listing"; exit 1; }
[ "$(status_of apquest.apworld)" = "pending:2.0.0" ] || { echo "apquest: $listing"; exit 1; }
[ "$(status_of apsui_broken.apworld)" = "rejected:None" ] || { echo "broken: $listing"; exit 1; }
[ "$(status_of apsui_mismatch.apworld)" = "rejected:None" ] || { echo "mismatch: $listing"; exit 1; }
id=$(echo "$listing" | python3 -c 'import json,sys; print(next(a["id"] for a in json.load(sys.stdin) if a["filename"] == "apsui_test_world.apworld"))')
curl -fsS -X POST "$base/apworlds/$id/approve" | grep -q '"status":"approved"' \
    || { echo "approve failed"; exit 1; }
sha=$(curl -fsS "$base/apworlds/$id" | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha256"])')
py web <<PY || { echo "approved apworld not in the library"; exit 1; }
import pathlib
assert pathlib.Path("/data/library/apworlds/$sha.apworld").is_file()
PY
rm -rf "$apworlds"

echo "--- a YAML picks the approved apworld; real AP checks it with it, and the game locks"
curl -fsS -F "file=@$here/worker/tests/yaml/game-unknown__custom-world.yaml" \
    -F "apworld_ids=$id" "$base/uploads/yaml" >/dev/null
wait_checked
curl -fsS "$base/uploads" | grep -q '"filename":"game-unknown__custom-world.yaml","status":"accepted"' \
    || { echo "custom-world YAML not accepted: $(curl -fsS "$base/uploads")"; exit 1; }
curl -fsS "$base/worlds" | grep -q "\"world\":\"APSUI Test World\",\"label\":\"APSUI Test World · custom · v1.0.0 · ${sha%"${sha#??????}"}\"" \
    || { echo "world not locked: $(curl -fsS "$base/worlds")"; exit 1; }
echo "apworlds: ok"

echo "--- upload log: the real rejection keeps the worker's full detail"
bad=$(curl -fsS "$base/uploads" | python3 -c 'import json,sys; print(next(u["id"] for u in json.load(sys.stdin) if u["error_code"] == "option-invalid"))')
curl -fsS "$base/logs/uploads/yaml/$bad" | python3 -c '
import json, sys
entry = json.load(sys.stdin)
failed = [c for c in entry["checks"] if c["status"] == "failed" and c["detail"]]
assert failed and "player_sprite" in failed[0]["detail"], entry
assert entry["job"]["type"] == "validate-yaml" and len(entry["sha256"]) == 64, entry
' || { echo "upload log entry incomplete"; exit 1; }
[ "$(curl -fsS "$base/logs/uploads" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')" -ge 8 ] \
    || { echo "upload log is missing entries"; exit 1; }
echo "upload log: ok"

echo "--- generation: lock, then real AP generates; the server service sees the output"
custom=$(curl -fsS "$base/uploads" | python3 -c 'import json,sys; print(next(u["id"] for u in json.load(sys.stdin) if u["filename"] == "game-unknown__custom-world.yaml"))')
curl -fsS -X DELETE "$base/uploads/$custom" >/dev/null  # the sample world is a stub
curl -fsS -X POST "$base/game/lock" | grep -q '"state":"locked"' || { echo "lock failed"; exit 1; }
curl -fsS -X POST "$base/game/generate" >/dev/null
for _ in $(seq 180); do
    curl -fsS "$base/game" | grep -q '"state":"generating"' || break
    sleep 1
done
curl -fsS "$base/game" | grep -q '"state":"generated"' \
    || { echo "not generated: $(curl -fsS "$base/game/generations")"; exit 1; }
zip=$(curl -fsS "$base/game/generations" | python3 -c '
import json, sys
g = json.load(sys.stdin)[0]
assert sorted(g["players"]) == ["Alice", "Quester"], g
print(g["output_file"])')
py server <<PY || { echo "server can't see the output"; exit 1; }
import zipfile
assert zipfile.is_zipfile("/data/game/output/$zip")
PY
curl -fsS "$base/game/patches" | python3 -c '
import json, sys
patches = json.load(sys.stdin)
assert isinstance(patches, list), patches
print("patch files:", [p["file"] for p in patches] or "none for these games")' || { echo "patch list failed"; exit 1; }
echo "generation: ok ($zip)"

echo "--- server control: real MultiServer starts, answers on the game port, saves, stops"
curl -fsS -X POST "$base/game/start" | grep -q '"state":"running"' || { echo "start failed"; exit 1; }
for _ in $(seq 90); do
    curl -fsS "$base/server" | grep -q '"state":"running"' && break
    sleep 1
done
curl -fsS "$base/server" | grep -q '"state":"running"' \
    || { echo "MultiServer not running: $(curl -fsS "$base/server")"; exit 1; }
python3 - "$APSUI_GAME_PORT" <<'PY' || { echo "game port not answering"; exit 1; }
import base64, os, socket, sys
# An Archipelago client starts with a WebSocket handshake; MultiServer must accept it.
key = base64.b64encode(os.urandom(16)).decode()
with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=10) as s:
    s.sendall(f"GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
              f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
    assert s.recv(200).startswith(b"HTTP/1.1 101"), "no WebSocket upgrade"
PY
curl -fsS -X POST "$base/server/save" >/dev/null
save="${zip%.zip}.apsave"
for _ in $(seq 20); do
    py server <<PY >/dev/null 2>&1 && break
import pathlib
assert pathlib.Path("/data/game/output/$save").is_file()
PY
    sleep 1
done
py server <<PY || { echo "no save file after Save"; exit 1; }
import pathlib
assert pathlib.Path("/data/game/output/$save").is_file()
PY
curl -fsS -X POST "$base/game/stop" | grep -q '"state":"generated"' || { echo "stop failed"; exit 1; }
curl -fsS "$base/server" | grep -q '"state":"stopped"' || { echo "server not stopped"; exit 1; }
echo "server control: ok"

echo "--- health page: every service up, the published ports, compose isolation"
curl -fsS "$base/health/details" | python3 -c '
import json, os, sys
h = json.load(sys.stdin)
assert all(s["up"] for s in h["services"]), h["services"]
assert (h["isolation"], h["isolation_warning"]) == ("compose", None), h
assert [p["port"] for p in h["ports"]] == [int(os.environ["APSUI_WEB_PORT"]), int(os.environ["APSUI_GAME_PORT"])], h
assert {d["name"] for d in h["disks"]} == {"Data", "Job queue", "Current game"}, h
' || { echo "health details wrong: $(curl -fsS "$base/health/details")"; exit 1; }
echo "health page: ok"

# Checks run inside every service.
common_checks='
import os, sys
status = dict(line.split(":\t", 1) for line in open("/proc/self/status").read().splitlines() if ":\t" in line)
assert os.getuid() == 10001, f"uid {os.getuid()}"
caps = status["CapEff"]
assert int(caps, 16) == 0, "capabilities " + caps
assert status["NoNewPrivs"].strip() == "1", "no-new-privileges is off"
try:
    open("/opt/write-test", "w")
    sys.exit("root filesystem is writable")
except OSError:
    pass
'

for service in web worker server; do
    echo "--- $service: unprivileged, read-only root, no capabilities"
    printf '%s\n' "$common_checks" | py "$service"
done

echo "--- worker: no network, and only the job queue is visible"
py worker <<'PY'
import os, socket
assert sorted(os.listdir("/sys/class/net")) == ["lo"], os.listdir("/sys/class/net")
try:
    socket.create_connection(("1.1.1.1", 443), timeout=3)
    raise SystemExit("worker reached the internet")
except OSError:
    pass
mounts = {line.split()[4] for line in open("/proc/self/mountinfo")}
for path in ("/data", "/data/game", "/run/apsui"):  # empty image folders are fine
    assert path not in mounts, f"worker has {path} mounted"
assert "/data/jobs" in mounts
open("/data/jobs/.write-test", "w").close()
os.remove("/data/jobs/.write-test")
print("ok")
PY

echo "--- server: no route to the web service, and no database or job queue"
web_ip=$(compose exec -T web python -c 'import socket; print(socket.gethostbyname(socket.gethostname()))' | tr -d '\r')
py server "$web_ip" <<'PY'
import os, socket, sys
assert sys.argv[1].count(".") == 3, f"no address for the web container: {sys.argv[1]!r}"
for host in ("web", sys.argv[1]):  # by name, and by the web container's address
    try:
        socket.create_connection((host, 8000), timeout=3)
        raise SystemExit(f"server reached the web service as {host!r}")
    except OSError:
        pass
mounts = {line.split()[4] for line in open("/proc/self/mountinfo")}
for path in ("/data", "/data/jobs"):  # empty image folders are fine
    assert path not in mounts, f"server has {path} mounted"
assert {"/data/game", "/run/apsui"} <= mounts
print("ok")
PY

echo "compose test passed"
