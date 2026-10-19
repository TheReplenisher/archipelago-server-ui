# Archipelago Server UI

A self-hosted web app for running an [Archipelago](https://archipelago.gg) multiworld
randomizer server for your group. It covers the whole game: players upload YAMLs and
custom apworlds (all checked before they're accepted), the admin generates and runs
the server from a console with command assistance, players follow their own slot's
items and hints, and finished games are archived.

> **Status: Alpha 1 (`v0.1.0-alpha.1`).** The admin runs a game end to end: upload and
> check YAMLs and apworlds, generate, start, save and stop the server, send it commands from
> the console, watch its output in the server feed, change its settings, and archive and
> restore games, and players follow their own slot. Player uploads and an admin login come
> in Alpha 2. See [DESIGN.md](DESIGN.md) for the plan and [ROADMAP.md](ROADMAP.md) for what
> comes when.

**Unofficial.** This project is not affiliated with or endorsed by the Archipelago project.

> [!WARNING]
> **Set the admin password as soon as it's installed.** Until it is set, whoever opens the
> **Admin** tab first sets it and becomes the admin. This is still alpha software: keep it
> on your LAN or a VPN unless you've read [SECURITY.md](SECURITY.md).

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
| `APSUI_ALLOWED_HOSTS` | *(none)* | Names you reach the web UI by, comma-separated (below) |
| `APSUI_FORWARDED_ALLOW_IPS` | `127.0.0.1` | Your HTTPS reverse proxy's address, so the admin's login cookie is marked HTTPS-only |

A port can name the host address to listen on, e.g. `APSUI_WEB_PORT=127.0.0.1:8000`
to reach the web UI only from the same machine.

**Host names.** The web UI answers only to names it knows, so that another website can't
reach it through a name of its own (DNS rebinding). IP addresses and local names
(`localhost`, `*.local`, `*.home.arpa`, `*.internal`) always work. For any other name,
such as `nas.lan` or your reverse proxy's domain, list it: `APSUI_ALLOWED_HOSTS=nas.lan`.
`*.example.com` covers its subdomains. Until you do, the page says which name to add.

## Install in a Proxmox LXC

The same three services, as systemd units, installed by a script you run **inside** a fresh
Debian 12 or 13 container (amd64 or arm64).

1. In Proxmox, create a container from the `debian-13-standard` (or 12) template:
   unprivileged with **nesting** on (the default for unprivileged containers), 2 CPU cores,
   **2 GB** of memory and 8 GB of disk or more. It needs internet access while installing.
2. In the container's console, as root:

   ```sh
   apt-get update && apt-get install -y curl
   curl -fsSLO https://raw.githubusercontent.com/TheReplenisher/archipelago-server-ui/main/lxc/install.sh
   bash install.sh
   ```

   It takes a while (it builds Archipelago's requirements). At the end it prints the
   address of the admin tab: `http://<container address>:8000/admin`.

`bash install.sh --ref <tag>` installs a given release instead of the latest `main`.

| Service | Runs as | Can write to |
|---|---|---|
| `apsui-web` (UI and API) | `apsui-web` | `/var/lib/apsui/data`, `game`, `jobs` |
| `apsui-worker` (checks, generation) | a throwaway user (`DynamicUser`), **no network** | `/var/lib/apsui/jobs` |
| `apsui-server` (MultiServer) | `apsui-server` | `/var/lib/apsui/game` |

**Settings** are in `/etc/apsui/apsui.env`: the web and game ports (`APSUI_PORT`,
`APSUI_GAME_PORT`), `APSUI_ALLOWED_HOSTS` (above), and the trusted reverse proxy
(`APSUI_FORWARDED_ALLOW_IPS`). After changing it: `systemctl restart apsui-server apsui-web`.
Logs: `journalctl -u apsui-web -u apsui-worker -u apsui-server`.

## First run

**Open the Admin tab first and set the admin password** (at least 8 characters). Admin,
Settings and Health all need it from then on; **Log out** and **Change password** are at
the top of those pages. A login lasts a week unused (a month at most), and changing the
password logs out every other browser.

Forgotten the password, or someone set it before you did? Set a new one from a shell on
the host, which also logs every admin out:

```sh
docker compose exec web apsui-admin set-password   # Docker Compose
apsui-admin set-password                           # LXC, as root
```

Everything else is on the **Admin** tab.

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
6. While the server runs, the **console** sends a line to MultiServer's own console: pick
   a **Command** and fill in its arguments (players, items and locations are searchable
   lists from the game), or type any `/command`, or a message to every player. The up
   and down arrows recall what you sent. Its replies appear in the **Server feed** below,
   with everything else MultiServer prints, live.
7. **ARCHIVE** (apart from the other buttons, and it asks first) ends the game: the server
   is saved and stopped, the YAMLs, output, save file, spoiler log, apworlds and logs move
   into an archive, and a new game opens for uploads. Under **Archives** you can browse an
   archive, download it as a zip, delete it, or **Restore** it as the current game; if
   the current game has anything in it, you choose to archive or delete it first.

Players upload their own YAMLs on the **Player** tab while the game is Open, unless you
turn off **Anyone can upload** in Settings. Their apworlds wait for your approval after
their checks (Settings can approve them automatically, at your own risk: an apworld is
Python code). Their browser keeps a receipt for each upload, so they can see its result,
fix a slot name, or withdraw it.

Players use the **Player** tab while the server runs: their slot name and the room
password (as in their game client) show the items they've received, the locations they
haven't checked, their hints, and, as the room's `!remaining` setting allows, the items
still out there; their own patch file to download; and a **Server feed** of item sends,
chat and goals. Nothing shows where an item is unless a hint says so. While the server is
stopped, the tab says so and asks them to contact you.

The **Settings** tab holds the server's host.yaml settings (room password, release and
collect, hints, idle stop), the generation settings (spoiler, race, plando), the upload
rules (slot limit, apworld approval) and the archive limit (by count or total size; the
oldest archives are deleted when a game is archived). The ones marked *Live* change a
running server at once; the rest apply at the next start, generation, upload or archive.

The **Spoiler log** button on the same card asks "Are you sure?" before showing anything.
The **Audit log** tab lists every admin action: who, when, from where, and whether it
worked.
The **Health** tab shows each service, the ports, disk use, the Archipelago version and
the host names the web UI answers to.

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
adds HTTPS. Turn on WebSocket support where the proxy asks: the server feed uses it. The
proxy must pass the `Host` header through, as these three do by default, because the feed
only accepts its own page. Behind HTTPS the admin's login cookie is only ever sent over
HTTPS; set `APSUI_FORWARDED_ALLOW_IPS` to the proxy's address so the web service knows.

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
the proxy can reach it. Add the proxy's domain to `APSUI_ALLOWED_HOSTS`
(`APSUI_ALLOWED_HOSTS=apsui.home.example` here). If the proxy is installed on the same machine (not in a
container of its own), set `APSUI_WEB_PORT=127.0.0.1:8000` instead and point it at
`127.0.0.1:8000`.

## Backups

The **Backups** tab makes a backup of the database (settings, uploads and logs), the
apworld library, the current game's files and, if you tick it, the archives. Backups are
kept on the server; **download them** to keep a copy somewhere else. **Upload a backup**
and **Restore** put one back, for example on a new install. Restoring replaces everything
but your admin password and the audit log, and makes a backup of the current state first.
Stop the server before restoring.

Make a backup before every upgrade.

## Upgrade

**Stop the server** from the admin tab first if a game is running, then:

```sh
docker compose pull
docker compose up -d
```

In an LXC, run the install script again (`bash install.sh`, or `--ref <tag>`). It refuses
while a game is running or generating, builds everything before stopping the services,
and puts the previous install back if the upgrade fails. `/var/lib/apsui` and
`/etc/apsui/apsui.env` are kept.

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

In an LXC:

```sh
bash install.sh --uninstall           # removes the services and the install; keeps your data
bash install.sh --uninstall --purge   # also deletes /var/lib/apsui and /etc/apsui
```

Or delete the container.

## Security

Uploaded `.apworld` files are Python code. Read [SECURITY.md](SECURITY.md) before
exposing an install to the internet.

The admin pages need the admin password (above). It is stored as a salted scrypt hash, and
logins are limited to 10 a minute per address. The player pages need no admin login.

The web service refuses requests that pages on other websites send through your browser,
names it doesn't know, and being shown in a frame, so a site you visit can't use the
admin tab even though your browser can reach it.

## License

[MIT](LICENSE)
