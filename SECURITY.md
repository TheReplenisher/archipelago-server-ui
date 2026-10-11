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

Alpha 1 has no admin login, so the admin tab is open to anyone who can reach the web UI.
That includes, through the admin's own browser, any website the admin visits. The web
service therefore refuses:

- requests that change something, and WebSocket connections, sent by pages on other
  websites (judged by `Sec-Fetch-Site`, else `Origin`);
- host names it doesn't know (DNS rebinding): only IP addresses, local names and
  `APSUI_ALLOWED_HOSTS` are answered;
- being shown in a frame (clickjacking).

Approving an apworld means trusting its author. Only approve worlds from sources you trust.

## Supported versions

Alpha. Fixes go into `main` and the next release: only the latest release (currently
`v0.1.0-alpha.1`) and `main` are supported.
