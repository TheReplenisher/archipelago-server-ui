"""Where Archipelago lives and where it puts per-job files. Used inside a job's child process."""

from __future__ import annotations

import os
from pathlib import Path


def custom_worlds_dir() -> Path:
    """This job's custom worlds folder.

    The install is read-only, so AP uses $XDG_DATA_HOME/Archipelago as its user folder and
    loads custom worlds from its worlds/ folder (Utils.user_path, worlds/__init__.py). The
    worker points XDG_DATA_HOME into the job's own directory.
    """
    path = Path(os.environ["XDG_DATA_HOME"]) / "Archipelago" / "worlds"
    path.mkdir(parents=True, exist_ok=True)
    return path
