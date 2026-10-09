# Archipelago Server UI — Design

> **Status:** design draft for **Alpha 1**. Only the project skeleton is built so far.
> What is planned for later is in [ROADMAP.md](ROADMAP.md); the work itself is tracked
> as GitHub issues, one milestone per release stage.

## 1. What this is

A self-hosted web app for running an [Archipelago](https://archipelago.gg) multiworld
randomizer server for a group. It handles the whole life of a game:

- **Before the game:** players upload YAMLs, and custom apworlds if they need them.
  Every file is checked.
- **Generation:** the admin generates the multiworld and can trial it on a throwaway
  test server.
- **During the game:** the admin runs the server from a console with command
  assistance. Players log in to their own slot to see their items, locations and hints.
- **After the game:** the game is archived and can be restored, and the next game
  opens for uploads.

It installs as a Docker Compose stack or into a Proxmox LXC, and is built for HTTPS.

**Unofficial.** This project is not affiliated with or endorsed by the Archipelago project.

### Scope rules

- **One live multiworld per install.** Concurrent rooms are a Future item.
- **Archipelago is pinned per release** (currently targeting **0.6.8**). Admin-selectable
  AP versions are a *possible* Future item, not a commitment.
  - The pin is `ARG AP_VERSION` in the Dockerfile. A daily workflow opens an `upstream`
    issue for each newer AP version, starting at its first release candidate, with an
    upgrade checklist.
- **Archipelago's own trust model is kept, not reinvented.** A slot is accessed with its
  slot name plus the server password, exactly as a game client would.

## 2. Architecture

One image, three services. Docker runs them as three Compose services; the LXC install
runs them as three systemd units. **Either way the user installs once and manages
everything from the web UI.**

```
                 browser (HTTPS via the user's reverse proxy)
                                 │
                       ┌─────────▼─────────┐
                       │       web         │  FastAPI + React UI, SQLite.
                       │  UI, API, auth,   │  NEVER imports apworld code.
                       │  lifecycle, logs  │
                       └───┬──────────┬────┘
            job queue (shared volume)  │  control channel + AP protocol
                   ┌───────▼──────┐  ┌─▼──────────────────┐
                   │    worker    │  │      server        │
                   │ NO network   │  │ AP MultiServer     │
                   │ read-only fs │  │ live: 38281        │
                   │ CPU/mem/time │  │ test: 38282        │
                   │ limits       │  │ (exposed to players)│
                   └──────────────┘  └────────────────────┘
          validates YAMLs + apworlds,        runs the generated
          runs generation                    multiworld
```

### Why three services (decision: "option C")

A `.apworld` is a zipped Python package. **Validating a YAML or generating a world means
running that package's code.** Uploaded apworlds are therefore treated as untrusted
until an admin approves them, and even then they only ever run in the worker or server.

Rejected alternatives:

- **Spawning containers from the app** needs the Docker socket or a privileged
  container. Socket access is effectively root on the host.
- **A sandboxed process inside the one container** (bubblewrap/nsjail) needs Docker's
  default seccomp profile loosened, and LXC nesting enabled.

The worker gets `network_mode: none`, a read-only root filesystem, dropped capabilities
and resource limits. Under LXC, the same restrictions come from systemd
(`PrivateNetwork=yes`, `ProtectSystem=strict`, `DynamicUser=yes`, `MemoryMax=`, …).

The web service holds the database and secrets, and never imports Archipelago world code.
It learns what it needs through the AP network protocol and from files the worker writes.

### Worker jobs (#16)

- **Jobs pass through `/data/jobs`,** the only part of `/data` the worker can see. Each
  job is a directory that moves by atomic rename: `tmp/` (the web service assembles
  `spec.json` and `input/`) → `queue/` → `running/` (claimed by the worker) → `done/`
  (`result.json`, `log.txt`, `output/`). The format is versioned, in
  `apsui_worker.protocol`.
- **One job at a time, oldest first, each in its own child process,** with a per-job time
  limit. On timeout the job's whole process group is killed. Each job also gets its own
  Archipelago user folder (`XDG_DATA_HOME`), so the apworlds of one job are never loaded
  by another.
- **Results are structured:** status `ok`, `error` or `timeout`, the output, an error
  code and one-line message, the traceback, and the tail of the log. A job interrupted by
  a worker restart is failed with code `interrupted`, never retried.
- **The web service records each job in the `jobs` table,** passes the output to the
  feature that asked for it, then deletes the files. It treats everything in `done/` as
  untrusted: results must name the right job, are size-limited, and symlinks or other
  non-regular files are never followed.

### Mounts, networks and the control channel (#13, #70)

| | web | worker | server |
|---|---|---|---|
| `/data` (database, library, archives) | ✔ | — | — |
| `/data/jobs` (job queue) | ✔ | ✔ | — |
| `/data/game` (current game) | ✔ | — | ✔ |
| `/run/apsui` (sockets) | ✔ | — | ✔ |
| Network | `web` (UI port) | **none** | `game` (game port) |

- **Every service** runs as uid 10001 with a read-only root, no capabilities and
  `no-new-privileges`, under its own memory and process limits.
- **The web service and the server share no network.** The web service talks to the
  server's supervisor through a **Unix socket** in `/run/apsui` (decided in #70): no
  listening port, and filesystem permissions are the authentication. The web service's own
  Archipelago-protocol connections (observer feed, slot logins) will go through a second
  socket there that the supervisor relays to MultiServer (#24, #27, #30). So code in the
  server container has **no route to the web API** — checked by `docker/compose-test.sh`,
  by name and by address.
- **Healthchecks:** web `/api/health`; worker a heartbeat file it updates every few seconds,
  also during a long job; server the supervisor answering `status` on the socket.

### The server service also runs apworld code (#5)

Archipelago's MultiServer imports **every** world in its worlds folder when it starts,
including worlds not in the current game. This was confirmed in AP 0.6.8's source and
in a live test.

- **Alpha 1 (decided):** contain the server process.
  - It has no database, no secrets and no access to the library.
  - Only the **current game's locked apworlds** are mounted into its custom worlds folder.
  - Read-only except the game directory, unprivileged, all capabilities dropped,
    memory-limited.
  - It is always started with an explicit `--host`. Without it, MultiServer makes an
    outbound request to look up the host's public IP.
- **Beta hardening (decided):** block the server's outbound traffic while still allowing
  players in.
  - Docker: the server sits on an `internal` network, and a small TCP proxy container
    publishes the game ports.
  - LXC: an nftables owner-match rule on the server unit's user.
- **Rejected:** patching MultiServer to skip `import worlds`. It would mean carrying a
  patch on AP core for every release.

**Known trade-off:** users of single-container platforms (plain `docker run`, Unraid
templates) need three containers. A reduced-isolation single-container mode is a Future
item, and if built it must show a warning on the health page.

### Stack

| Layer | Choice |
|---|---|
| Backend | Python, FastAPI |
| Frontend | React + TypeScript + Vite, Mantine component library |
| Live updates | WebSocket from web service to browser |
| Storage | SQLite (SQLAlchemy; Alembic migrations applied at startup) + a data directory (uploads, library, games, archives) |
| Archipelago | Run from source at a pinned tag (needed for arm64), **without the desktop GUI dependencies** (kivy/kivymd). Every built-in world's requirements are installed except `dolphin-memory-engine` (The Wind Waker's game client only; no arm64 wheel). `requests` and `setuptools<81`, which a normal install gets implicitly, are added explicitly (`docker/install-archipelago.sh`) |
| Packaging | One multi-arch image (amd64 primary, arm64 supported), GHCR. Each architecture is built and smoke-tested on a native CI runner |

**arm64 matters** because Oracle Cloud's free tier is Ampere ARM. It was verified in #8:
every server and generator dependency has a native aarch64 wheel, and generation and
hosting work. Each release is tested under emulated arm64 before it ships.

### Data layout

```
/data
  app.db                SQLite: settings, uploads, library index, logs, audit
  jobs/                 worker job queue: tmp/, queue/, running/, done/ (shared with the worker)
  library/apworlds/     every approved apworld, stored by hash
  library/roms/         (Future) admin-approved base ROMs; never served to users
  game/                 the current game: YAMLs, chosen apworlds, output zip, save file, logs
                        (shared with the server)
  staging/              (Beta) uploads for the next game while one is running
  archives/<id>/        archived games (zip + metadata)
  backups/              (Alpha 2) app backups
```

## 3. Game lifecycle

```
Open ──► Locked ──► Generating ──► Generated ──► Running ──► Archived
 ▲          │            │              │  ▲         │           │
 │          └─ unlock ◄──┴─ on failure ─┘  └── stop ─┘           │
 └──────────────────── new game (ARCHIVE) ◄──────────────────────┘
                          restore: Archived ──► Generated
```

| State | Meaning |
|---|---|
| **Open** | Uploads accepted (admin-only in Alpha 1; players from Alpha 2) |
| **Locked** | Uploads frozen; admin reviews before generating |
| **Generating** | Worker runs generation. Failures go to the generation log, and the state returns to Locked |
| **Generated** | Output exists and the server is stopped. The admin can start it, run the **test server** (Beta), or discard the output to change uploads |
| **Scheduled** | (Beta) A countdown to start is running, between Generated and Running |
| **Running** | The live server is up. The admin has **Start / Stop / Save** |
| **Archived** | Read-only, downloadable and restorable |

**Transitions (#17)** — enforced in `apsui/lifecycle.py`; nothing else changes a game's state:

| Action | From | To |
|---|---|---|
| lock / unlock | Open ⇄ Locked | |
| generate | Locked | Generating |
| generation succeeded / failed | Generating | Generated / Locked |
| discard output | Generated | Locked |
| start / stop | Generated ⇄ Running | |
| archive | Generated or Running | Archived, and a new Open game becomes current |
| restore | Archived | Generated |

- **Exactly one game is current**, enforced by the database. A state change is a
  conditional update on the state it was read in, so two simultaneous requests can't both
  move the game.
- **Stop keeps the game resumable:** it returns to Generated with its save file, and Start
  continues it.
- **Generation is always started manually by the admin.**
- **Start / Stop / Save:** Stop is a clean shutdown with a save. Save writes the save
  file without stopping the server.
- **ARCHIVE** is a separate button, near the others but visually apart. It is labelled
  `ARCHIVE` and has an "Are you sure?" prompt. It ends the game and re-opens uploads.
- **Each archive holds** the multidata, save file, spoiler log, YAMLs, the apworlds used
  and all logs. It can be downloaded as a zip, browsed read-only, or restored.
- **Retention:** the admin can delete archives by hand and set a limit, either
  **max archive count** or **max total archive size**. When the limit is reached, the
  oldest archive is deleted automatically.
- **Next-game staging (Beta):** while a game is running, players can upload YAMLs for
  the next game.

## 4. Uploads and validation

### YAMLs — "level 1" checks (every upload)

1. The file parses as YAML. Multi-document files are allowed and give one slot per document.
2. `name` is present, at most 16 characters, and unique in the current game.
3. `game` exists, either as a built-in world or as an approved library apworld.
4. Every option exists for that game and every value is legal. Weighted options and
   triggers are allowed.
5. The total slot count stays under the admin's **max slots** setting. If `allow_quantity`
   is on, each document's quantity counts toward it.

Steps 3–4 import world code, so they run **in the worker** (the `validate-yaml` job,
#20). Decided while building it:

- **Every value that could be rolled is checked,** not just one roll: each key of a
  weighted option with a non-zero weight, each list item, then the option's own
  `verify()`. Archipelago's `roll_settings()` then runs 5 times, which also exercises
  triggers, linked options and `requires`.
- **The name must be one fixed string.** Weighted names and templates (`%number%`,
  `%player%`) are rejected, because a slot is logged in to by name (§6).
- **Unknown option names are warnings, not errors,** as in Archipelago itself.
- **`quantity` above 1 is rejected** until `allow_quantity` exists on the settings page
  (#25); with fixed names it could never be unique anyway.
- **Names and the slot limit are checked by the web service** when the job finishes, since
  they depend on the other uploads. Names are compared without case, as Archipelago does.
- **The accepted file is always the admin's own bytes,** kept in web-only storage while it
  is checked, never a copy back from the worker.
- **Lock waits for checks:** the game can't be locked while a file is still being checked.

**No solo test generation.** Some YAMLs fail on their own but work in a full multiworld,
so a solo test would reject good uploads.

### Apworlds

1. **Static inspection (no code runs):** the file is a valid zip; its folder matches the
   file name; `archipelago.json` gives `game`, `world_version`, `minimum_ap_version`,
   `maximum_ap_version` and `authors`. It is checked against the pinned AP version and
   hashed with SHA-256.
2. **Pending:** a new apworld waits in a pending state. The admin setting is
   **manual approve** (default) or **auto-approve**.
3. **The admin sees, before approving:** the manifest fields, the file list, the hash,
   the uploader and the worker's import result.
   - If the apworld **replaces a built-in world**, it always needs manual approval, and
     the approval screen says so plainly.
4. **Worker import test:** the worker loads the world in isolation and records any errors.

### The apworld library

- Approved apworlds go into a library and are reused, so the same file is never stored twice.
- Each entry is labelled `Game · official|custom · version · short hash`, for example
  `Hollow Knight · custom · v1.2.0 · a3f9c1`.
  - Two files with the same version number but different contents count as different
    versions, told apart by hash.
- When uploading a YAML, the player picks which library version their game uses.
- **A new game defaults to the official built-in world.** A custom apworld from an
  earlier game is never reused automatically.

### Version locking

Archipelago allows one world per game in a multiworld. So:

- The first accepted YAML for a game **locks that game to a version** for this multiworld.
- A later upload that picks a different version is rejected with a short error (4–10
  words), for example: *"Different game version already in use — contact the server
  admin."*
- The error code links to the full detail in the admin's upload log.
- **Admin override (Alpha 2):** the admin can change a game's locked version. The UI
  lists every slot whose YAML needs re-uploading for the new version.

### Upload logs (admin)

Every upload (YAML, apworld, and later ROM) gets a log entry containing:

- who uploaded it, when, and the file hash;
- every check and its result;
- the full error and traceback from the worker.

Users only ever see the short error.

## 5. Running the server

### Admin console and command assistance

- A free-text console still accepts any command, typed by hand.
- **Assistance covers every server command**, not only `/send`:
  1. Pick a command from a dropdown.
  2. Each argument gets the right input: player, item, location, number or text.
  3. Player, item and location inputs are **searchable lists** built from the data
     package of the multiworld currently running. They update when a new game is
     generated.
- **The command list is generated automatically** from the pinned AP version's command
  handlers, then given a hand-maintained map of argument types. This keeps it correct
  when AP is upgraded.

### Server feed (decided in #6: hybrid)

- **Admin console and admin feed:** the server process's stdout, streamed live.
  - It is the only source that includes command output, for example `/players`.
  - It is **admin-only**, because it contains the room password and the passwords of
    refused login attempts.
- **Player feed (Alpha 2) and slot views:** the AP protocol.
  - The backend holds one observer connection (tag `Tracker`). Item sends are broadcast
    to the whole team, structured, with item flags.
  - The flags let the UI highlight progression, useful and trap items, and later drive
    Discord's "important items".
- **Accepted:** every Tracker connection is announced to all players ("X tracking … has
  joined"), including in their game clients. Universal Tracker and PopTracker behave the
  same way.

### Spoiler log

- The admin can view or download it.
- It always shows an "Are you sure?" prompt first.

### host.yaml settings (decided in #9)

⚡ = applied live with `/option`; everything else applies at the next start or generation.

- **Server:**
  - room `password` ⚡ and `server_password` ⚡
  - `release_mode` ⚡, `collect_mode` ⚡, `remaining_mode` ⚡, `countdown_mode` ⚡
  - `hint_cost` ⚡, `location_check_points` ⚡
  - `disable_item_cheat` ⚡ (**our default: true**, so `!getitem` is off; AP's default has it on)
  - `compatibility` ⚡
  - `auto_shutdown` (shown as "stopped (idle)")
  - `port`
- **Generation:** `spoiler`, `race`, `plando_options` (checkboxes), `panic_method`
- **Advanced section:**
  - `loglevel`
  - `log_network` (with a warning: very large logs)
  - `allow_quantity` (each slot's quantity counts toward **max slots**)
- **Hidden, set by the backend:**
  - `host` (bind all; also stops the public-IP lookup)
  - file paths: `multidata`, `savefile`, `output_path`, `player_files_path`, `weights_file_path`,
    `meta_file_path`
  - `players` (inferred from the uploads)
  - `disable_save` (always false)
  - `logtime` (always on, so the feed has timestamps)
- **Belong to Future features:**
  - per-game sections (ROM paths) go with ROM uploads
  - `meta.yaml` goes with generation presets

### Patch files

- After generation, each slot's patch or mod file (`.apz5` and similar) can be downloaded.
- **Alpha 1:** admin only. **Alpha 2:** each player can download their own slot's files.

### Test server (Beta)

- A throwaway copy of the generated output, with its own save file, run alongside the
  live server without touching it.
- The port defaults to the live port + 1 (`38282`); the admin can set a different one.
- It is wiped when stopped.

### Scheduled start (Beta)

- The admin sets either a delay ("in 5 minutes") or a date and time, in the server's
  timezone (an admin setting). Times are stored in UTC.
- The UI shows the countdown in the server's timezone and in the viewer's local time.
- **Countdown modes** (admin's choice):
  - **Open:** players can join at any time; AP's in-game countdown runs.
  - **Restricted:** the server refuses players until 10 seconds remain, then opens and
    runs AP's countdown for the final 10 seconds.
- The countdown is always visible in the UI.

## 6. Player side

### Slot login

- **The login is the slot name plus the server password**, which is the same trust
  model AP itself uses.
  - Here "server password" means the room's connection password (`password` in
    `server_options`), **not** AP's admin `server_password`.
- **It works whether or not a server password is set.** With no password, anyone who
  knows a slot name can view that slot, just as anyone could connect to it in AP.
- **One login is one slot** for now. Logging in once for several slots is a Future item
  (see ROADMAP).
- **Credentials are checked against the running AP server** over the AP protocol, so the
  web app never stores its own copy of slot credentials.
  - While the server is stopped, the slot view shows the last known state, marked
    stale, and no new logins are accepted. *(Open question — confirm during Alpha 1.)*

### Slot view

| Panel | Content |
|---|---|
| Received items | Items this slot has received |
| Unreceived items | Items for this slot that are still in the multiworld somewhere. **Where they are is not shown** |
| Unchecked locations | Locations in this slot's world not yet checked. **What they hold is not shown** |
| Hints | Every hint involving this slot: found or not, and who holds it |

**No spoilers, ever,** except through hints the player paid for.

The tracker data comes from an AP-protocol connection made as that slot with the
`Tracker` tag. It uses the official protocol, never AP's internal files.

### Player commands (Beta)

- Players can run `!hint`, `!release`, `!collect`, `!remaining`, etc. from the UI.
- What is allowed is decided by the server's own settings, not by this app.

## 7. Admin side

- **Alpha 1: there is no admin login.** The admin tab is open to anyone who can reach
  the UI. This is an accepted early-alpha risk; the README warns against exposing an
  Alpha 1 install to the internet.
- **Alpha 2:** one default admin account. A password is set on first login and can be
  changed later.
- **Beta:** the default admin can add more admins, each with a role that limits what
  they can do.
- **Audit log (Alpha 2):** every admin action, with who did it and when.
- **Health page (Alpha 1):** whether each service is up, ports, disk use, the AP version,
  and the isolation mode.
- **Backup and restore (Alpha 2):** the app database, library and archives.

## 8. Networking and security

- **The web UI is HTTPS by design.** The app serves plain HTTP behind the user's reverse
  proxy (Nginx Proxy Manager, Caddy, Traefik). The README gives setups for each.
- **Game traffic is separate from web traffic.** AP clients connect directly to the
  server port (`38281`), not through the web UI.
  - **LAN games:** plain `ws://` is fine.
  - **Internet games:** `wss://` using AP's own certificate options is recommended.
    This needs verifying against 0.6.8.
- **Cloudflare Tunnel is out of scope for the game port.** AP's standard client uses
  `ws://` and port 38281 by default, so players would have to type `wss://host:443`, and
  clients not written in Python vary. Cloudflare's free plan also caps request bodies at
  100 MB. Tunnelling the web UI is still fine.
- **Uploads are sent in chunks**, so large files work behind proxies with body-size limits.
- **ROMs (Future):** admin approval only, with no auto-approve. ROMs are never served to
  players, and users must supply their own legally obtained copies.

## 9. Installation targets

| Target | Alpha 1 |
|---|---|
| Docker Compose | Primary. One `docker compose up -d` |
| Proxmox LXC | A script run **inside** a fresh Debian LXC. It installs the same three services as systemd units |
| Proxmox host one-liner (creates the LXC) | Future |

The README covers installation, first run, reverse proxy and HTTPS, ports, upgrades,
backups and uninstalling.
