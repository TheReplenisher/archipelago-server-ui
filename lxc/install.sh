#!/usr/bin/env bash
# Archipelago Server UI: install, upgrade or uninstall inside a Debian 12 or 13 LXC (#14).
#
# Run as root inside a fresh container. It installs the same three services as the
# Docker image (DESIGN.md §2), as systemd units:
#   apsui-web     the UI and API         user apsui-web
#   apsui-worker  runs apworld code      a throwaway user, no network
#   apsui-server  runs MultiServer       user apsui-server
#
#   install.sh [--ref <git ref>]       install, or upgrade to <ref> (re-run any time)
#   install.sh --uninstall [--purge]   remove it; --purge also deletes every game and setting
#
# Upgrades keep /var/lib/apsui (games, uploads, library, archives) and /etc/apsui/apsui.env.
# Needs: Debian 12 or 13, amd64 or arm64, systemd, about 2 GB of memory, and internet access
# to GitHub, PyPI and nodejs.org. Proxmox: the container needs nesting (Options → Features),
# which unprivileged containers have by default.
set -euo pipefail

REPO=${APSUI_REPO:-https://github.com/TheReplenisher/archipelago-server-ui.git}
REF=${APSUI_REF:-main}
UV_VERSION=0.12.23       # as in the Dockerfile
NODE_VERSION=24.9.0      # builds the UI, then is removed
PYTHON_VERSION=3.12      # as in the Dockerfile

PREFIX=/opt/apsui
AP_DIR=/opt/archipelago
AP_VENV=/opt/archipelago-venv
STATE=/var/lib/apsui
CONFIG=/etc/apsui/apsui.env
UNITS=(apsui-server apsui-worker apsui-web)

say() { printf '\n==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

uninstall=false purge=false
while [ $# -gt 0 ]; do
    case $1 in
        --ref) REF=${2:?--ref needs a value}; shift 2 ;;
        --uninstall) uninstall=true; shift ;;
        --purge) purge=true; shift ;;
        -h|--help) usage 0 ;;
        *) usage 1 ;;
    esac
done

[ "$(id -u)" = 0 ] || die "run it as root"
[ -d /run/systemd/system ] || die "systemd isn't running here"

if $uninstall; then
    say "Stopping and removing the services"
    for unit in "${UNITS[@]}"; do
        systemctl disable --now "$unit" 2>/dev/null || true
        rm -f "/etc/systemd/system/$unit.service"
    done
    systemctl daemon-reload
    rm -rf "$PREFIX" "$AP_DIR" "$AP_VENV"
    if $purge; then
        say "Deleting every game, upload, apworld, archive and setting"
        rm -rf "$STATE" /etc/apsui
        userdel apsui-web 2>/dev/null || true
        userdel apsui-server 2>/dev/null || true
        groupdel apsui-game 2>/dev/null || true
        groupdel apsui-jobs 2>/dev/null || true
    else
        echo "Kept $STATE and /etc/apsui: run with --uninstall --purge to delete them too."
    fi
    say "Uninstalled"
    exit 0
fi

# ---- checks
. /etc/os-release
case "${ID}:${VERSION_ID:-}" in
    debian:12|debian:13) ;;
    *) die "this needs Debian 12 or 13 (found ${PRETTY_NAME:-unknown})" ;;
esac
case $(uname -m) in
    x86_64) arch=x86_64 node_arch=x64 ;;
    aarch64) arch=aarch64 node_arch=arm64 ;;
    *) die "this needs amd64 or arm64 (found $(uname -m))" ;;
esac
mem_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
[ "$mem_kb" -ge 1500000 ] || echo "warning: under 1.5 GB of memory; generation may run out"

upgrade=false
if [ -x "$PREFIX/venv/bin/apsui-web" ]; then
    upgrade=true
    port=$(sed -n 's/^APSUI_PORT=//p' "$CONFIG" 2>/dev/null || true)
    state=$(curl -fsS --max-time 5 "http://127.0.0.1:${port:-8000}/api/game" 2>/dev/null \
        | sed -n 's/.*"state":"\([a-z]*\)".*/\1/p' || true)
    if [ "$state" = running ] || [ "$state" = generating ]; then
        die "the game is $state: stop the server (or let generation finish) from the admin page first"
    fi
fi

say "Packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q --no-install-recommends ca-certificates curl git build-essential xz-utils

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

fetch_checked() {  # fetch_checked <url> <file> <sha256>
    curl -fsSL --retry 3 -o "$2" "$1"
    echo "$3  $2" | sha256sum -c --quiet - || die "checksum mismatch for $1"
}

say "uv $UV_VERSION"
uv_tar="uv-${arch}-unknown-linux-gnu.tar.gz"
uv_url="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$uv_tar"
uv_sha=$(curl -fsSL "$uv_url.sha256" | awk '{print $1}')
fetch_checked "$uv_url" "$work/$uv_tar" "$uv_sha"
tar -xzf "$work/$uv_tar" -C "$work"
export PATH="$work/uv-${arch}-unknown-linux-gnu:$PATH"  # only for the install
export UV_PYTHON_INSTALL_DIR="$work/python" UV_CACHE_DIR="$work/uv-cache"
export UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_PREFERENCE=only-managed

say "Python $PYTHON_VERSION"
uv python install -q "$PYTHON_VERSION"
python=$(uv python find "$PYTHON_VERSION")

say "Archipelago Server UI ($REF)"
git clone -q --depth 1 --branch "$REF" "$REPO" "$work/src" 2>/dev/null \
    || { git clone -q "$REPO" "$work/src" && git -C "$work/src" checkout -q "$REF"; }
src=$work/src
commit=$(git -C "$src" rev-parse --short HEAD)
ap_version=$(sed -n 's/^ARG AP_VERSION=//p' "$src/Dockerfile")
[ -n "$ap_version" ] || die "can't find the pinned Archipelago version in the Dockerfile"
git clone -q --depth 1 --branch "$ap_version" https://github.com/ArchipelagoMW/Archipelago.git \
    "$work/archipelago"
rm -rf "$work/archipelago/.git"

say "The UI (Node $NODE_VERSION, removed afterwards)"
node_tar="node-v$NODE_VERSION-linux-$node_arch.tar.xz"
node_sha=$(curl -fsSL "https://nodejs.org/dist/v$NODE_VERSION/SHASUMS256.txt" \
    | awk -v f="$node_tar" '$2 == f {print $1}')
[ -n "$node_sha" ] || die "no checksum for $node_tar"
fetch_checked "https://nodejs.org/dist/v$NODE_VERSION/$node_tar" "$work/$node_tar" "$node_sha"
tar -xJf "$work/$node_tar" -C "$work"
(
    export PATH="$work/node-v$NODE_VERSION-linux-$node_arch/bin:$PATH"
    cd "$src/frontend"
    npm ci --no-audit --no-fund --loglevel=error
    npm run build --silent
)

# From here the install is replaced. A venv can't be moved, so everything is built where it
# will live; the old install waits beside it and comes back if anything fails.
if $upgrade; then
    say "Stopping the services for the upgrade"
    systemctl stop "${UNITS[@]}" || true
fi
for dir in "$PREFIX" "$AP_DIR" "$AP_VENV"; do
    rm -rf "$dir.old"
    if [ -e "$dir" ]; then mv "$dir" "$dir.old"; fi
done
rollback() {
    echo "error: the install failed; putting the previous one back" >&2
    for dir in "$PREFIX" "$AP_DIR" "$AP_VENV"; do
        if [ -e "$dir.old" ]; then rm -rf "$dir"; mv "$dir.old" "$dir"; fi
    done
    if $upgrade; then systemctl start "${UNITS[@]}" || true; fi
}
trap 'rollback; rm -rf "$work"' ERR
install -d "$PREFIX"

say "Archipelago $ap_version (this is the slow part)"
mv "$work/archipelago" "$AP_DIR"
uv python install -q --install-dir "$PREFIX/python" "$PYTHON_VERSION"
python=$(UV_PYTHON_INSTALL_DIR="$PREFIX/python" uv python find "$PYTHON_VERSION")
uv venv -q "$AP_VENV" --python "$python"
sh "$src/docker/install-archipelago.sh" "$AP_DIR" "$AP_VENV/bin/python"
"$AP_VENV/bin/python" -m compileall -q "$AP_DIR" >/dev/null || true
uv pip install -q --python "$AP_VENV/bin/python" --no-deps "$src/worker" "$src/server"
"$AP_VENV/bin/python" -m apsui_server.commands "$AP_DIR/MultiServer.py" "$PREFIX/commands.json"
if "$AP_VENV/bin/python" -c 'import apsui_worker.builtin_worlds' 2>/dev/null; then
    # As root the install is writable, so AP makes a custom_worlds folder in it: not wanted.
    XDG_DATA_HOME="$work/ap-user" SKIP_REQUIREMENTS_UPDATE=1 "$AP_VENV/bin/python" \
        -m apsui_worker.builtin_worlds "$AP_DIR" "$PREFIX/builtin-worlds.json"
    rm -rf "$AP_DIR/custom_worlds"
fi

say "Web service"
(cd "$src/backend" && UV_PROJECT_ENVIRONMENT="$PREFIX/venv" uv sync -q --locked --no-dev \
    --no-editable --python "$python")
cp -r "$src/frontend/dist" "$PREFIX/static"
printf '%s\n' "# Written by lxc/install.sh on every install; edit $CONFIG instead." \
    "APSUI_ARCHIPELAGO_VERSION=$ap_version" "ARCHIPELAGO_VERSION=$ap_version" \
    "APSUI_INSTALLED_REF=$REF" "APSUI_INSTALLED_COMMIT=$commit" > "$PREFIX/install.env"
# Root owns the install; the services only read it.
chown -R root:root "$PREFIX" "$AP_DIR" "$AP_VENV"
chmod -R go-w "$PREFIX" "$AP_DIR" "$AP_VENV"
trap 'rm -rf "$work"' ERR
rm -rf "$PREFIX.old" "$AP_DIR.old" "$AP_VENV.old"

say "Users and folders"
getent group apsui-game >/dev/null || groupadd --system apsui-game
getent group apsui-jobs >/dev/null || groupadd --system apsui-jobs
id apsui-web >/dev/null 2>&1 || useradd --system --user-group --groups apsui-game,apsui-jobs \
    --no-create-home --home-dir "$STATE/data" --shell /usr/sbin/nologin apsui-web
id apsui-server >/dev/null 2>&1 || useradd --system --gid apsui-game \
    --no-create-home --home-dir "$STATE/game" --shell /usr/sbin/nologin apsui-server
install -d -m 0755 -o root -g root "$STATE"
install -d -m 0700 -o apsui-web -g apsui-web "$STATE/data"         # database, library, archives
install -d -m 2770 -o apsui-web -g apsui-game "$STATE/game"        # shared with the server
install -d -m 2770 -o apsui-web -g apsui-jobs "$STATE/jobs"        # shared with the worker

if [ ! -f "$CONFIG" ]; then
    install -d -m 0755 /etc/apsui
    cat > "$CONFIG" <<'EOF'
# Archipelago Server UI settings. lxc/install.sh keeps this file on upgrade.
# After a change: systemctl restart apsui-server apsui-web

# The web UI's port, and the port players connect their game clients to.
APSUI_PORT=8000
APSUI_GAME_PORT=38281
# Host names browsers may use for the UI besides IP addresses and .local/.lan-style local
# names, comma-separated (DESIGN.md §8), e.g. ap.example.com. Behind a reverse proxy, also
# set the proxy's address as trusted:
APSUI_ALLOWED_HOSTS=
APSUI_FORWARDED_ALLOW_IPS=127.0.0.1
# The default slot limit and apworld approval, until set on the Settings page.
APSUI_MAX_SLOTS=50
APSUI_APWORLD_APPROVAL=manual
EOF
fi

say "Services"
for unit in "${UNITS[@]}"; do
    install -m 0644 "$src/lxc/systemd/$unit.service" "/etc/systemd/system/$unit.service"
done
systemctl daemon-reload
systemctl enable -q "${UNITS[@]}"
systemctl restart "${UNITS[@]}"

. "$CONFIG"
for _ in $(seq 60); do
    curl -fsS --max-time 2 "http://127.0.0.1:${APSUI_PORT}/api/health" >/dev/null 2>&1 && break
    sleep 1
done
curl -fsS --max-time 2 "http://127.0.0.1:${APSUI_PORT}/api/health" >/dev/null \
    || die "the web service didn't come up: journalctl -u apsui-web"

address=$(hostname -I | awk '{print $1}')
say "Archipelago Server UI $REF ($commit) is $($upgrade && echo upgraded || echo installed)"
cat <<EOF
  Admin:   http://$address:$APSUI_PORT/admin
  Players: game port $APSUI_GAME_PORT on this container's address
  Settings: $CONFIG    Logs: journalctl -u apsui-web -u apsui-worker -u apsui-server

  Alpha 1 has no admin login: keep this container on your LAN or a VPN, not the internet.
EOF
