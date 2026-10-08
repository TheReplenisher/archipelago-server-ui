# Contributing

Thanks for your interest! The project is in **early design/alpha**, so things move fast
and big changes are likely.

## Before you start

- Read [DESIGN.md](DESIGN.md) and [ROADMAP.md](ROADMAP.md).
- Check the [issues](../../issues): work is grouped by milestone (Alpha 1, Alpha 2,
  Beta, Future), and the `area:*` labels show which part of the app an issue touches.
- For anything bigger than a small fix, **comment on the issue (or open one) before
  writing code**, so effort isn't wasted on something that conflicts with the design.

## Development setup

You need [uv](https://docs.astral.sh/uv/) (it fetches Python 3.12 if needed) and
Node.js 22 or newer.

```
backend/    FastAPI web service (package `apsui`): API, SQLite + Alembic migrations
frontend/   React + TypeScript + Vite + Mantine; built into frontend/dist
```

```sh
make install        # uv sync + npm ci
make dev-backend    # API on http://localhost:8000 (data in .dev-data/)
make dev-frontend   # UI on http://localhost:5173, hot reload, /api goes to the backend
make check          # lint, format check, type check and tests for both
make format         # auto-fix formatting
```

Without `make`, run the commands from the [Makefile](Makefile) yourself.

To build and smoke-test the image locally (Docker or Podman):

```sh
docker build -t apsui:dev .
docker/smoke-test.sh apsui:dev 0.6.8        # CONTAINER=podman for Podman
```

The smoke test checks that the web service answers and that every built-in Archipelago
world imports with no network and a read-only filesystem.
The backend serves `frontend/dist` when it has been built (`make build`), which is
how the app runs in production.

Database changes need a migration:
`cd backend && uv run alembic revision --autogenerate -m "describe the change"`.
A test fails if the models and migrations disagree.

**The web service (`backend/`) must never import Archipelago world code.** Anything
that runs apworld code belongs in the worker or server service (DESIGN.md §2).

## Pull requests

1. Fork the repo and branch from `main` (`feat/…`, `fix/…`, `docs/…`).
2. Keep PRs focused on one issue, and reference it (`Closes #12`).
3. Make sure lint and tests pass. CI runs them on every PR, then builds the image for
   amd64 and arm64 and smoke-tests both.
4. Workflows on PRs from first-time contributors need maintainer approval before they run.

## Security

**Never** report vulnerabilities in a public issue. See [SECURITY.md](SECURITY.md).
Uploaded `.apworld` files are code, so changes touching uploads, the worker or the
server service get extra review.

## Never commit

ROMs or other copyrighted game files, save files, generated multiworlds, real player
YAMLs, or any secrets.

## Releases

Semantic versioning with pre-release tags: `v0.1.0-alpha.1`, `v0.2.0-beta.1`, …

CI publishes `ghcr.io/thereplenisher/archipelago-server-ui` (amd64 + arm64):

| Trigger | Tags |
|---|---|
| push to `main` | `edge`, `sha-<short sha>` |
| tag `v1.2.3` | `1.2.3`, `latest`, `sha-<short sha>` |
| pre-release tag `v0.1.0-alpha.1` | `0.1.0-alpha.1`, `sha-<short sha>` (never `latest`) |
