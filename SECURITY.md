# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's
**private vulnerability reporting**: *Security → Report a vulnerability* on this repository.

## The threat this project is built around

An Archipelago `.apworld` is a Python package. Validating a YAML or generating a
multiworld means running that code. This project therefore:

- holds new apworlds in a **pending** state until an admin approves them (manual approval
  by default; replacing a built-in world always needs manual approval);
- runs validation and generation in an **isolated worker** with no network access, a
  read-only filesystem and resource limits;
- never imports apworld code in the web service, which holds the database and secrets.

Approving an apworld means trusting its author. Only approve worlds from sources you trust.

## Supported versions

Pre-release. Only the latest commit on `main` is supported.
