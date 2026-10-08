# Archipelago Server UI

A self-hosted web app for running an [Archipelago](https://archipelago.gg) multiworld
randomizer server for your group. It covers the whole game: players upload YAMLs and
custom apworlds (all checked before they're accepted), the admin generates and runs
the server from a console with command assistance, players follow their own slot's
items and hints, and finished games are archived.

> **Status: design phase.** Nothing is runnable yet. See [DESIGN.md](DESIGN.md) for the
> plan and [ROADMAP.md](ROADMAP.md) for what comes when.

**Unofficial.** This project is not affiliated with or endorsed by the Archipelago project.

## Installation

*Written during Alpha 1.* Two supported targets:

- **Docker Compose** (primary): amd64 and arm64
- **Proxmox LXC**: an install script run inside a fresh Debian container

## Security

Uploaded `.apworld` files are Python code. Read [SECURITY.md](SECURITY.md) before
exposing an install to the internet. **Alpha 1 has no admin login; do not expose it
publicly.**

## License

[MIT](LICENSE)
