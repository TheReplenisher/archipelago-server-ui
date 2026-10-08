# Contributing

Thanks for your interest! The project is in **early design/alpha**, so things move fast
and big changes are likely.

## Before you start

- Read [DESIGN.md](DESIGN.md) and [ROADMAP.md](ROADMAP.md).
- Check the [issues](../../issues): work is grouped by milestone (Alpha 1, Alpha 2,
  Beta, Future), and the `area:*` labels show which part of the app an issue touches.
- For anything bigger than a small fix, **comment on the issue (or open one) before
  writing code**, so effort isn't wasted on something that conflicts with the design.

## Pull requests

1. Fork the repo and branch from `main` (`feat/…`, `fix/…`, `docs/…`).
2. Keep PRs focused on one issue, and reference it (`Closes #12`).
3. Make sure lint and tests pass (CI runs them once the skeleton exists).
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
