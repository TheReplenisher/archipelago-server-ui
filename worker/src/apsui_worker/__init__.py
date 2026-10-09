"""Archipelago Server UI: the worker service.

Runs jobs that execute Archipelago code (YAML validation, apworld import tests,
generation) with no network, a read-only filesystem and resource limits
(DESIGN.md §2). Each job runs in its own child process with its own Archipelago user
folder, so one job's apworlds never leak into another.

Standard library only: this package is installed into Archipelago's environment, and
the web service imports `apsui_worker.protocol` (never anything that touches AP).
"""
