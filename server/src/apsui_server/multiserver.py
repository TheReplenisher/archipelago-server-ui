"""Runs Archipelago's MultiServer with the game's custom apworlds in place of the built-in
worlds they replace (#77):

    python -m apsui_server.multiserver <archipelago dir> <MultiServer arguments>

MultiServer imports every world when it loads the multidata, and would skip an apworld
whose game is built in. The built-ins are hidden first (apsui_worker.builtin_worlds), then
MultiServer.py runs as if started directly. With no replacement nothing is imported early.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def main() -> None:
    archipelago_dir = Path(sys.argv[1])
    sys.path.insert(0, str(archipelago_dir))
    custom = Path(os.environ["XDG_DATA_HOME"]) / "Archipelago" / "worlds"
    if any(custom.glob("*.apworld")):
        from apsui_worker.builtin_worlds import load_worlds

        if hidden := load_worlds(custom, archipelago_dir):
            # Into the server log, so the admin's feed says so.
            print(f"Custom apworlds replace the built-in {', '.join(sorted(hidden))}", flush=True)
    script = archipelago_dir / "MultiServer.py"
    sys.argv = [str(script), *sys.argv[2:]]
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
