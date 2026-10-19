#!/bin/sh
# Bring up compose.yaml with a given image and check that it works and that each
# service's isolation holds (DESIGN.md §2, #13).
# Usage: compose-test.sh <image>       (COMPOSE="podman compose" etc. to override)
set -eu
# Waits scale with APSUI_TEST_WAIT_SCALE, e.g. 10 for an image run under emulation (#60).
scale=${APSUI_TEST_WAIT_SCALE:-1}

export APSUI_IMAGE="$1"
export APSUI_WEB_PORT="${APSUI_WEB_PORT:-18080}"
export APSUI_GAME_PORT="${APSUI_GAME_PORT:-48281}"
project="apsui-test-$$"
here=$(cd "$(dirname "$0")/.." && pwd)
files="-f $here/compose.yaml"
if [ "$scale" -gt 1 ]; then
    # A slow (emulated) run: each healthcheck starts Python, which takes longer than its
    # 5-second timeout there. Give the checks the same scale, in an override file.
    slow=$(mktemp)
    for service in web worker server; do
        printf '  %s:\n    healthcheck: {interval: %ss, timeout: %ss, start_period: %ss}\n' \
            "$service" $((6 * scale)) $((5 * scale)) $((30 * scale))
    done | { echo "services:"; cat; } > "$slow"
    files="$files -f $slow"
fi
# shellcheck disable=SC2086  # $files is a list of arguments
compose() { ${COMPOSE:-docker compose} -p "$project" $files "$@"; }
py() { service=$1; shift; compose exec -T "$service" /opt/archipelago-venv/bin/python - "$@"; }

cleanup() {
    status=$?
    if [ "$status" -ne 0 ]; then compose logs --no-color --tail 50 || true; fi
    compose down -v --timeout 5 >/dev/null 2>&1 || true
    [ -z "${slow:-}" ] || rm -f "$slow"
    [ -z "${CURL_HOME:-}" ] || rm -rf "$CURL_HOME"
    exit "$status"
}
trap cleanup EXIT

echo "--- start the stack and wait for every healthcheck"
compose up -d --wait --wait-timeout $((120 * scale))

echo "--- web answers on the published port"
curl -fsS "http://127.0.0.1:$APSUI_WEB_PORT/api/health" | grep -q '"status":"ok"'

echo "--- admin login (#32): the admin API is closed until the admin logs in"
[ "$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$APSUI_WEB_PORT/api/game")" = 401 ] \
    || { echo "the admin API answered without a login"; exit 1; }
echo 'compose test password' | compose exec -T web apsui-admin set-password --password-stdin
# Every curl from here on sends (and keeps) the admin's session cookie.
CURL_HOME=$(mktemp -d)
export CURL_HOME
printf 'cookie = "%s/jar"\ncookie-jar = "%s/jar"\n' "$CURL_HOME" "$CURL_HOME" > "$CURL_HOME/.curlrc"
curl -fsS -H 'Content-Type: application/json' -d '{"password":"compose test password"}' \
    "http://127.0.0.1:$APSUI_WEB_PORT/api/admin/login" | grep -q '"logged_in":true' \
    || { echo "admin login failed"; exit 1; }
admin_token=$(awk '$6 == "apsui_admin" {print $7}' "$CURL_HOME/jar")

echo "--- web reaches the server supervisor over the control socket"
curl -fsS "http://127.0.0.1:$APSUI_WEB_PORT/api/server" | grep -q '"reachable":true'

echo "--- a job goes web -> worker -> web"
compose exec -T web python - "$scale" <<'PY'
import sys, time
from apsui.config import get_settings
from apsui.db import make_engine, make_sessionmaker
from apsui.jobs import JobQueue
from apsui.models import Job

settings = get_settings()
sessions = make_sessionmaker(make_engine(settings.database_url))
with sessions() as session:
    job_id = JobQueue(settings.resolved_jobs_dir).submit(session, "ping").id
for _ in range(60 * int(sys.argv[1])):  # the web service's own collector records it
    with sessions() as session:
        job = session.get(Job, job_id)
        if job is not None and job.status not in ("queued", "running"):
            break
    time.sleep(0.5)
assert job is not None and job.status == "ok", (job.status if job else None, job and job.result)
print("ping job: ok")
PY

echo "--- apworlds: inspected by web, import-tested by the worker (real AP), approved"
base="http://127.0.0.1:$APSUI_WEB_PORT/api"
wait_checked() {
    for _ in $(seq $((60 * scale))); do
        curl -fsS "$base/uploads" | grep -q '"status":"pending"' || return 0
        sleep 1
    done
    echo "uploads still pending"; exit 1
}
apworlds=$(mktemp -d)
for sample in "$here"/worker/tests/apworld/*/; do
    case $sample in */replaces__*) continue ;; esac  # stubs; a real replacement follows
    module=$(basename "$sample" | sed 's/.*__//')
    (cd "$sample" && mkdir -p "$apworlds/src/$module" && cp ./* "$apworlds/src/$module/")
    (cd "$apworlds/src" && python3 -m zipfile -c "$apworlds/$module.apworld" "$module")
    curl -fsS -F "file=@$apworlds/$module.apworld" "$base/apworlds" >/dev/null
done
# A working replacement for a built-in world, with the built-in's own folder name (#77):
# the image's APQuest, as version 9.9.0.
py web > "$apworlds/apquest.apworld" <<'PY'
import io, json, sys, zipfile
from pathlib import Path
src = Path("/opt/archipelago/worlds/apquest")
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
    for f in sorted(src.rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts and f.name != "archipelago.json":
            zf.write(f, f"apquest/{f.relative_to(src)}")
    # version/compatible_version as AP's packaging writes them; without, AP ignores the rest
    manifest = json.loads((src / "archipelago.json").read_text()) | {
        "world_version": "9.9.0", "version": 7, "compatible_version": 7}
    zf.writestr("apquest/archipelago.json", json.dumps(manifest))
sys.stdout.buffer.write(buf.getvalue())
PY
curl -fsS -F "file=@$apworlds/apquest.apworld" "$base/apworlds" >/dev/null
for _ in $(seq $((60 * scale))); do
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
apquest=$(echo "$listing" | python3 -c 'import json,sys; print(next(a["id"] for a in json.load(sys.stdin) if a["filename"] == "apquest.apworld"))')
curl -fsS -X POST "$base/apworlds/$apquest/approve" | grep -q '"status":"approved"' \
    || { echo "approving the replacement failed"; exit 1; }
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

echo "--- YAML uploads: web -> worker (real Archipelago) -> slots"
# The first APQuest YAML picks the replacement, which locks the game to it; the rest get it.
curl -fsS -F "file=@$here/worker/tests/yaml/ok__weighted.yaml" -F "apworld_ids=$apquest" \
    "$base/uploads/yaml" >/dev/null
wait_checked
for sample in option-invalid__bad-choice name-not-fixed__weighted-name; do
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
curl -fsS "$base/worlds" | grep -q '"world":"APQuest","label":"APQuest · custom · v9.9.0 · ' \
    || { echo "APQuest not locked to the replacement: $(curl -fsS "$base/worlds")"; exit 1; }
echo "uploads: ok"

echo "--- player upload (#33): no admin login, real AP checks it, withdrawn with its receipt"
# curl -q: without the admin's cookie.
player=$(curl -q -fsS -F "file=@$here/worker/tests/yaml/ok__multi.yaml" "$base/player/yaml")
upload_id=$(echo "$player" | python3 -c 'import json,sys; print(json.load(sys.stdin)["upload"]["id"])')
receipt=$(echo "$player" | python3 -c 'import json,sys; print(json.load(sys.stdin)["receipt"])')
wait_checked
curl -q -fsS -H 'Content-Type: application/json' \
    -d "{\"receipts\":[{\"kind\":\"yaml\",\"id\":$upload_id,\"receipt\":\"$receipt\"}]}" \
    "$base/player/receipts" | python3 -c '
import json, sys
[u] = json.load(sys.stdin)
assert (u["status"], sorted(u["slots"])) == ("accepted", ["First", "Second"]), u
assert "detail" not in u and "traceback" not in json.dumps(u), u' \
    || { echo "player upload not accepted"; exit 1; }
curl -fsS "$base/uploads" | grep -q '"uploaded_by":"player"' || { echo "not marked as a player upload"; exit 1; }
curl -q -fsS -H 'Content-Type: application/json' -d "{\"receipt\":\"$receipt\"}" \
    "$base/player/yaml/$upload_id/withdraw" | grep -q '"status":"removed"' \
    || { echo "withdraw failed"; exit 1; }
echo "player upload: ok"

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
for _ in $(seq $((180 * scale))); do
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
curl -fsS "$base/game/spoiler" | python3 -c '
import json, sys
spoiler = json.load(sys.stdin)
assert spoiler["file"].endswith("_Spoiler.txt") and spoiler["size"] > 0, spoiler' \
    || { echo "no spoiler log"; exit 1; }
curl -fsS "$base/game/spoiler.txt" | head -c 200 | grep -q "Archipelago Version" \
    || { echo "spoiler log unreadable"; exit 1; }
compose exec -T web python - <<'PY' || { echo "generation didn't use the replacement"; exit 1; }
from sqlalchemy import select
from apsui.config import get_settings
from apsui.db import make_engine, make_sessionmaker
from apsui.models import Generation, Job

sessions = make_sessionmaker(make_engine(get_settings().database_url))
with sessions() as session:
    generation = session.scalars(select(Generation).order_by(Generation.id.desc())).first()
    output = session.get(Job, generation.job_id).result["output"]
assert output["custom_worlds"] == {"APQuest": "9.9.0"}, output
PY
echo "generation: ok ($zip, with the APQuest replacement)"

echo "--- settings: saved, then MultiServer reads them from host.yaml at start"
settings() {  # settings '<python dict of changes>': PUT the settings with those changed
    curl -fsS "$base/settings" | python3 -c "
import json, sys
values = json.load(sys.stdin)['values']
values.update($1)
print(json.dumps(values))" | curl -fsS -X PUT -H 'Content-Type: application/json' -d @- "$base/settings"
}
settings '{"password": "compose pw", "hint_cost": 20}' >/dev/null || { echo "settings not saved"; exit 1; }

echo "--- server control: real MultiServer starts, answers on the game port, saves, stops"
curl -fsS -X POST "$base/game/start" | grep -q '"state":"running"' || { echo "start failed"; exit 1; }
for _ in $(seq $((90 * scale))); do
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
for _ in $(seq $((20 * scale))); do
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
py server <<'PY' || { echo "MultiServer didn't use the replacement"; exit 1; }
log = open("/data/game/logs/server.log").read()
assert "Custom apworlds replace the built-in APQuest" in log, log[-2000:]
assert "is already loaded" not in log, log[-2000:]
PY
echo "--- console: the catalog and names, and a /send built from them reaches MultiServer"
curl -fsS "$base/console/commands" | python3 -c '
import json, sys
commands = {c["name"]: c for c in json.load(sys.stdin)}
assert [a["kind"] for a in commands["send"]["args"]] == ["player", "item"], commands.get("send")' \
    || { echo "no command catalog"; exit 1; }
send=$(curl -fsS "$base/console/names" | python3 -c '
import json, sys
names = json.load(sys.stdin)
assert sorted(p["name"] for p in names["players"]) == ["Alice", "Quester"], names["players"]
game = next(p["game"] for p in names["players"] if p["name"] == "Alice")
item = names["games"][game]["items"][0]
print(json.dumps({"text": f"/send Alice \"{item}\""}))') || { echo "no console names"; exit 1; }
curl -fsS -X POST -H 'Content-Type: application/json' -d "$send" "$base/server/command" \
    | grep -q '"state":"running"' || { echo "console command failed"; exit 1; }
for _ in $(seq $((20 * scale))); do
    py server <<'PY' >/dev/null 2>&1 && break
assert "Cheat console: sending" in open("/data/game/logs/server.log").read()
PY
    sleep 1
done
py server <<'PY' || { echo "the /send never reached MultiServer"; exit 1; }
assert "Cheat console: sending" in open("/data/game/logs/server.log").read()
PY
echo "console: ok ($send)"
py server <<'PY' || { echo "MultiServer didn't read host.yaml"; exit 1; }
log = open("/data/game/logs/server.log").read()
assert "(Password: compose pw)" in log, log[-2000:]
PY
settings '{"hint_cost": 30}' | grep -q '"applied_now":\["hint_cost"\]' \
    || { echo "live setting not applied"; exit 1; }
for _ in $(seq $((20 * scale))); do
    py server <<'PY' >/dev/null 2>&1 && break
assert "Set option hint_cost to 30" in open("/data/game/logs/server.log").read()
PY
    sleep 1
done
py server <<'PY' || { echo "the live setting never reached MultiServer"; exit 1; }
assert "Set option hint_cost to 30" in open("/data/game/logs/server.log").read()
PY
echo "settings: ok (host.yaml at start, /option live)"
py web "$admin_token" <<'PY' || { echo "server feed incomplete"; exit 1; }
import asyncio, json, sys
try:  # the new client (websockets 13+)
    from websockets.asyncio.client import connect
    headers = "additional_headers"
except ImportError:
    from websockets import connect
    headers = "extra_headers"

async def scrollback():
    url, cookie = "ws://127.0.0.1:8000/api/server/feed", {"Cookie": f"apsui_admin={sys.argv[1]}"}
    async with connect(url, **{headers: cookie}) as ws:
        return json.loads(await ws.recv())["lines"]

lines = asyncio.run(scrollback())
assert any(l.startswith("[") and "Hosting game at" in l for l in lines), lines[-20:]  # --logtime
assert any("Cheat console: sending" in l for l in lines), lines[-20:]  # the console's /send
print(f"server feed: {len(lines)} lines of scrollback")
PY
echo "--- slot view: real MultiServer checks the login through the relay; items, locations, hints"
jar=$(mktemp)
slot_login() {  # slot_login <name> <password>: prints the HTTP status
    curl -sS -o /dev/null -w '%{http_code}' -c "$jar" -H 'Content-Type: application/json' \
        -d "{\"name\":\"$1\",\"password\":\"$2\"}" "$base/slot/login"
}
[ "$(slot_login Quester 'wrong pw')" = 401 ] || { echo "a wrong room password was let in"; exit 1; }
[ "$(slot_login Nobody 'compose pw')" = 401 ] || { echo "an unknown slot was let in"; exit 1; }
[ "$(slot_login Quester 'compose pw')" = 200 ] || { echo "slot login failed"; exit 1; }
curl -fsS -b "$jar" "$base/slot" | python3 -c '
import json, sys
v = json.load(sys.stdin)
assert v["slot"]["name"] == "Quester" and v["slot"]["game"] == "APQuest", v["slot"]
assert v["live"] and v["locations"] > 0 and v["unchecked"], v
assert not any(l.startswith("Location ") for l in v["unchecked"]), v["unchecked"][:5]  # named
assert (v["unreceived"], v["unreceived_rule"]) == (None, "goal"), v  # AP default: after goal
print("slot view:", v["locations"], "locations,", len(v["received"]), "received")' \
    || { echo "slot view wrong"; exit 1; }
settings '{"remaining_mode": "enabled"}' >/dev/null
curl -fsS -b "$jar" "$base/slot" | python3 -c '
import json, sys
v = json.load(sys.stdin)
assert v["unreceived_rule"] == "enabled" and v["unreceived"], v  # the whole pool is still out
assert all(u["count"] >= 1 and not u["item"].startswith("Item ") for u in v["unreceived"]), v' \
    || { echo "unreceived items not shown"; exit 1; }
py server <<'PY' || { echo "the tracker never reached MultiServer"; exit 1; }
assert "Quester (Team #1) tracking APQuest has joined" in open("/data/game/logs/server.log").read()
PY
echo "slot view: ok"
echo "--- player feed (#35): one observer connection; a real /send reaches it, hints never do"
curl -fsS -b "$jar" "$base/slot/feed" >/dev/null  # opens the observer
curl -fsS -H 'Content-Type: application/json' -d '{"text": "/send Alice \"Confetti Cannon\""}' \
    "$base/server/command" >/dev/null
for _ in $(seq $((20 * scale))); do
    curl -fsS -b "$jar" "$base/slot/feed" | grep -q '"type":"ItemCheat"' && break
    sleep 1
done
curl -fsS -b "$jar" "$base/slot/feed" | python3 -c '
import json, sys
f = json.load(sys.stdin)
cheat = [e for e in f["entries"] if e["type"] == "ItemCheat"]
assert cheat, f
parts = {(p["kind"], p["text"]) for p in cheat[-1]["parts"]}
assert ("item", "Confetti Cannon") in parts and ("player", "Alice") in parts, cheat[-1]
assert not any(e["type"] in ("Hint", "Tutorial", "CommandResult") for e in f["entries"]), f
print("player feed:", len(f["entries"]), "entries")' || { echo "player feed wrong"; exit 1; }
curl -fsS -X POST "$base/game/stop" | grep -q '"state":"generated"' || { echo "stop failed"; exit 1; }
[ "$(curl -sS -o /dev/null -w '%{http_code}' -b "$jar" "$base/slot")" = 503 ] \
    || { echo "slot view while stopped isn't 503"; exit 1; }
rm -f "$jar"
curl -fsS "$base/server" | grep -q '"state":"stopped"' || { echo "server not stopped"; exit 1; }
echo "server control: ok"

echo "--- archive and restore: the game moves between the game and data volumes and back"
game_id=$(curl -fsS "$base/game" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
curl -fsS -X POST "$base/game/archive" | grep -q '"state":"open"' || { echo "archive failed"; exit 1; }
curl -fsS "$base/archives/$game_id" | python3 -c '
import json, sys
paths = {f["path"] for f in json.load(sys.stdin)["files"]}
assert "archive.json" in paths, paths
assert any(p.startswith("output/AP_") and p.endswith(".zip") for p in paths), paths
assert any(p.endswith(".apsave") for p in paths), paths  # Stop saved
assert "logs/server.log" in paths, paths' || { echo "archive incomplete"; exit 1; }
py server <<'PY' || { echo "game folder not emptied"; exit 1; }
import os
left = set(os.listdir("/data/game"))
assert not left & {"yamls", "output", "logs"}, left  # ap/ may keep AP's default files
PY
curl -fsS "$base/archives/$game_id/download" | python3 -c '
import io, sys, zipfile
names = zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())).namelist()
assert "archive.json" in names, names' || { echo "archive zip unreadable"; exit 1; }
curl -fsS -X POST -H 'Content-Type: application/json' -d '{}' "$base/archives/$game_id/restore" \
    | grep -q '"state":"generated"' || { echo "restore failed"; exit 1; }
curl -fsS -X POST "$base/game/start" | grep -q '"state":"running"' || { echo "restored game won't start"; exit 1; }
for _ in $(seq $((90 * scale))); do
    curl -fsS "$base/server" | grep -q '"state":"running"' && break
    sleep 1
done
curl -fsS "$base/server" | grep -q '"state":"running"' \
    || { echo "restored game not hosted: $(curl -fsS "$base/server")"; exit 1; }
curl -fsS -X POST "$base/game/stop" | grep -q '"state":"generated"' || { echo "stop failed"; exit 1; }
echo "archives: ok"

echo "--- backup and restore (#38): a real backup on the data volume, restored in place"
curl -fsS -H 'Content-Type: application/json' -d '{"archives": true}' "$base/backups" >/dev/null
for _ in $(seq $((60 * scale))); do
    curl -fsS "$base/backups" | grep -q '"making":false' && break
    sleep 1
done
backup=$(curl -fsS "$base/backups" | python3 -c '
import json, sys
[b] = [b for b in json.load(sys.stdin)["backups"] if b["readable"]]
assert b["archives"] and b["files"] > 5, b
print(b["name"])') || { echo "no backup made"; exit 1; }
curl -fsS -X POST "$base/game/discard-output" >/dev/null  # a change the restore undoes
curl -fsS -X POST "$base/backups/$backup/restore" | grep -q "\"restored\":\"$backup\"" \
    || { echo "restore failed"; exit 1; }
curl -fsS "$base/game" | grep -q '"state":"generated"' \
    || { echo "restored game wrong: $(curl -fsS "$base/game")"; exit 1; }
curl -fsS -X POST "$base/game/start" | grep -q '"state":"running"' \
    || { echo "the restored game won't start"; exit 1; }
for _ in $(seq $((30 * scale))); do
    curl -fsS "$base/server" | grep -q '"state":"running"' && break
    sleep 1
done
curl -fsS "$base/server" | grep -q '"state":"running"' || { echo "restored game not hosted"; exit 1; }
curl -fsS -X POST "$base/game/stop" | grep -q '"state":"generated"' || { echo "stop failed"; exit 1; }
curl -fsS "$base/audit" | grep -q '"action":"restore_backup"' \
    || { echo "restore not in the audit log"; exit 1; }
echo "backups: ok"

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
