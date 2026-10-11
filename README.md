# Archipelago Server UI

A self-hosted web app for running an [Archipelago](https://archipelago.gg) multiworld
randomizer server for your group. It covers the whole game: players upload YAMLs and
custom apworlds (all checked before they're accepted), the admin generates and runs
the server from a console with command assistance, players follow their own slot's
items and hints, and finished games are archived.

> **Status: Alpha 1 in progress.** The admin can run a game end to end: upload and check
> YAMLs and apworlds, generate, and start, save and stop the server. The console, server
> feed, slot view, settings page and archives are still to come. See [DESIGN.md](DESIGN.md)
> for the plan and [ROADMAP.md](ROADMAP.md) for what comes when.

**Unofficial.** This project is not affiliated with or endorsed by the Archipelago project.

> [!WARNING]
> **Alpha 1 has no admin login.** Anyone who can reach the web UI can run the admin
> tab. Keep it on your LAN or a VPN, and don't expose it to the internet, even behind a
> reverse proxy. Read [SECURITY.md](SECURITY.md) first.

## Install with Docker Compose

You need Docker with Compose v2, on amd64 or arm64.

```sh
mkdir archipelago-server-ui && cd archipelago-server-ui
curl -fsSLO https://raw.githubusercontent.com/TheReplenisher/archipelago-server-ui/main/compose.yaml
docker compose up -d
```

Then open `http://<host>:8000/admin`.

The stack is three services from one image: **web** (the UI and API), **worker** (checks
uploads and generates, with no network at all) and **server** (runs Archipelago's
MultiServer). Each runs as an unprivileged user with a read-only filesystem; see
[DESIGN.md §2](DESIGN.md) for why.

### Settings

Put any of these in a `.env` file next to `compose.yaml`, then `docker compose up -d`:

| Variable | Default | What |
|---|---|---|
| `APSUI_WEB_PORT` | `8000` | Host port for the web UI (plain HTTP) |
| `APSUI_GAME_PORT` | `38281` | Host port Archipelago clients connect to |
| `APSUI_IMAGE` | `ghcr.io/thereplenisher/archipelago-server-ui:edge` | Image to run |
| `APSUI_WEB_MEMORY` | `512m` | Memory limit of the web service |
| `APSUI_WORKER_MEMORY` | `2g` | Memory limit of the worker (generation) |
| `APSUI_SERVER_MEMORY` | `1g` | Memory limit of the server |
| `APSUI_WORKER_CPUS` | `2` | CPU limit of the worker |

A port can name the host address to listen on, e.g. `APSUI_WEB_PORT=127.0.0.1:8000`
to reach the web UI only from the same machine.

### Proxmox LXC

An install script to run inside a fresh Debian LXC is coming in Alpha 1 (#14).

## First run

Everything is on the **Admin** tab.

1. **Custom games:** upload their `.apworld` files under **Apworlds**. Each is inspected
   and test-imported in the worker, then waits for your approval. Only approve worlds
   from sources you trust: an apworld is Python code.
2. **Player YAMLs:** upload each player's YAML. Each is checked by Archipelago in the
   worker; a rejected file shows a short error, and its error code opens the full
   detail in the **Upload log**.
3. **Lock uploads**, then **Generate**. If generation fails, the game goes back to
   Locked and the card shows which YAML Archipelago blamed.
4. **Start server.** Players connect their Archipelago client to `<host>:38281` with
   their slot name. If their game needs a patch file, download it from the
   **Current game** card and send it to them.
5. **Save** writes the save file without stopping; **Stop server** saves and shuts down,
   and **Start server** resumes from the save.

The **Spoiler log** button on the same card asks "Are you sure?" before showing anything.
The **Health** tab shows each service, the ports, disk use and the Archipelago version.

## Ports

| Port | Default | What |
|---|---|---|
| Web UI | `8000` | The UI and API, plain HTTP. Put HTTPS in front of it (below). |
| Game | `38281` | Archipelago clients, over WebSocket. Published directly, never through the reverse proxy. |
| Test server | `38282` | *Beta (#41):* a throwaway copy of the game on the live port + 1. |

### `ws://` and `wss://`

The game port speaks plain `ws://`. That's fine on a LAN or over a VPN (WireGuard,
Tailscale and the like), and most desktop clients accept it over the internet too, but
the traffic, room password included, isn't encrypted. A documented `wss://` setup for
internet games is planned (#10).

## HTTPS with a reverse proxy

The web service speaks plain HTTP on `APSUI_WEB_PORT`. A reverse proxy in front of it
adds HTTPS. Turn on WebSocket support where the proxy asks: the live server feed will
use it. (Remember the warning above: in Alpha 1 this is for HTTPS on your own network,
not for exposing the admin tab.)

**Caddy** (`Caddyfile`):

```caddyfile
apsui.home.example {
    reverse_proxy 192.168.1.10:8000
}
```

**Nginx Proxy Manager:** add a *Proxy Host* for your domain with scheme `http`, the
Docker host's IP and port `8000`, and turn on *Websockets Support*. Pick a certificate on
the *SSL* tab.

**Traefik** (file provider, so `compose.yaml` stays as it is):

```yaml
http:
  routers:
    apsui:
      rule: Host(`apsui.home.example`)
      service: apsui
      tls: {}
  services:
    apsui:
      loadBalancer:
        servers:
          - url: http://192.168.1.10:8000
```

Replace `192.168.1.10` with the Docker host's address, and firewall port `8000` so only
the proxy can reach it. If the proxy is installed on the same machine (not in a
container of its own), set `APSUI_WEB_PORT=127.0.0.1:8000` instead and point it at
`127.0.0.1:8000`.

## Upgrade

**Stop the server** from the admin tab first if a game is running, then:

```sh
docker compose pull
docker compose up -d
```

Database migrations run when the web service starts. Your data lives in the stack's
volumes (database, apworld library and archives; job queue; current game; control
socket), which an upgrade keeps. The default image tag, `edge`, is the latest build of
`main`; once releases exist, pin one with `APSUI_IMAGE` (for example
`ghcr.io/thereplenisher/archipelago-server-ui:0.1.0-alpha.1`).

## Uninstall

```sh
docker compose down      # removes the containers and networks; keeps your data
docker compose down -v   # also deletes the volumes: every game, upload, apworld and archive
docker image rm ghcr.io/thereplenisher/archipelago-server-ui:edge
```

## Security

Uploaded `.apworld` files are Python code. Read [SECURITY.md](SECURITY.md) before
exposing an install to the internet. **Alpha 1 has no admin login; do not expose it
publicly.**

## License

[MIT](LICENSE)
