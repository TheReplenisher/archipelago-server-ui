# Roadmap

How the plan in [DESIGN.md](DESIGN.md) is split across releases. Each stage is a
GitHub milestone, and the issues in it are the live task list.
**This file records intent; the issues record progress.**

## Pre-public

Repo hygiene and security settings to finish before the repository is made public.

## Alpha 1: a working end-to-end game, admin-driven

- Docker Compose stack (web, worker and server services) and an LXC install script
  run inside the container
- README with install, first run, reverse proxy/HTTPS, ports, upgrade and uninstall
- Admin tab, **no login** (accepted early-alpha risk; README warns against internet
  exposure)
- Game lifecycle: Open → Locked → Generating → Generated → Running → Archived
- Archives: restore, manual delete, retention by max count **or** max total size
- YAML and apworld upload, **admin only**, with all checks:
  - YAML level-1 validation in the worker
  - apworld static inspection and worker import test
  - pending/approve (manual or auto); built-in replacements always need manual approval
  - apworld library labelled with official/custom, version and hash
  - per-game version locking with the short error message
- Upload logs with full detail
- Manual generation
- Start / Stop / Save, plus a separate **ARCHIVE** button behind an "Are you sure?" prompt
- The most important `host.yaml` settings
- Admin console with command assistance for **every** command (searchable
  player/item/location lists)
- Server feed (admin tab)
- Spoiler log behind an "Are you sure?" prompt
- Slot login (slot name + room password): received items, unreceived items, unchecked
  locations, hints
- Patch downloads (admin only)
- Health page
- Multi-arch image (amd64 + arm64)

## Alpha 2: open it up to players

- Admin login: one default admin, password set on first login and changeable
- Player uploads of YAMLs and apworlds, choosing a version from the library
- Admin override of a game's locked version, listing the slots that must re-upload
- Server feed on the player side
- Players download their own patch files
- Audit log of admin actions
- Backup and restore

## Beta: the full hosting experience

- Several admins with roles
- Scheduled start (delay or date/time), server timezone, countdown modes (open /
  restricted with a 10-second window), countdown shown in the UI
- Test server: a throwaway copy of the output, on live port + 1 by default, port set
  by the admin
- Player commands from the UI, with permissions set by the server's own settings
- Next-game staging: players upload YAMLs while a game is running
- Documented `wss://` setup for internet games
- Server hardening: block the AP server's outbound traffic while still allowing players in
  (internal network + TCP proxy on Docker; nftables owner match on LXC)

## Future

Recorded so they aren't lost, not committed to a release.

### Tracking

- **Universal Tracker integration:** an in-logic location view, computed on the server
  (in the worker) from the YAMLs and apworlds already held there.
- **Hint dashboard:**
  - hint points progress bar, with a marker at each hint threshold and full when the
    last hint is earned;
  - count of hints available to spend;
  - history of hints used.

### Players and logins

- **One login for several slots.** Options to evaluate:
  1. *Link slots in a session:* log in to slot A, then "add slot B" with its credentials.
  2. *Player profiles:* a nickname + PIN created at upload time, owning the slots
     uploaded under it.
  3. *Discord sign-in:* link slots to a Discord identity (pairs with the Discord feature).

  This is the point to tighten security beyond AP's shared-password model.
- **Ready check-ins** before a scheduled start. Optional; the admin turns it on.
- **Partial spoilers for finished players.** Off by default; the admin turns it on.
  - After finishing, a player sees the items **from their own game** still sitting in
    **their own world's** unchecked locations.
  - Other players' items in that world stay hidden until those players also finish.
  - The list is hidden by default and the player chooses to reveal it.

### Discord

- **Discord integration:** a webhook or bot for the item feed, with user mentions for
  important items in a player's slot(s).
  - Evaluate integrating [ArchipelagoSphereTracker](https://github.com/Etsuna/ArchipelagoSphereTracker)
    before building our own.
- **Async game reminders.** Off by default. The admin sets how often, at most once per
  24 hours per player. Needs the Discord integration.

### Games, generation and files

- **ROM uploads.** Users upload; the admin must approve, with no auto-approve. ROMs are
  never served back to users.
- **Generation presets:** saved sets of generation options, for example race mode or
  plando.
- **Several games running at the same time** (concurrent rooms).
- **AP version chosen by the admin.** *Unconfirmed:* only if it proves practical.

### Deployment

- **Single-container mode** for platforms that only run one container, with reduced
  isolation and a warning on the health page.
- **Proxmox host one-liner** that creates the LXC, and possibly a community-scripts
  submission.
- **Cloudflare Tunnel for the game port.** Skipped for now; revisit only with a tested
  list of game clients that work.
