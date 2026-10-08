"""Archipelago Server UI: the web service.

This package holds the database and secrets, and must never import Archipelago world
code. Anything that runs apworld code belongs in the worker or server service
(DESIGN.md §2).
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("apsui")
except PackageNotFoundError:  # running from a source tree that isn't installed
    __version__ = "0.0.0"
