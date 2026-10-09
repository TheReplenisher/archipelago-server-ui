"""List every world Archipelago can load: built-in, plus any apworlds in input/.

Output: {"archipelago_version", "worlds": [{game, version, module, builtin}], "failed"}
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apsui_worker.jobs import JobContext


def run(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    from apsui_worker.archipelago import custom_worlds_dir

    # Apworlds supplied with the job become this job's custom worlds.
    custom = custom_worlds_dir()
    for apworld in sorted(ctx.input_dir.glob("*.apworld")):
        shutil.copy2(apworld, custom / apworld.name)

    import Utils
    import worlds

    builtin = {source.name: source.relative for source in worlds.world_sources}
    found = []
    for game, cls in sorted(worlds.AutoWorldRegister.world_types.items()):
        module = cls.__module__.split(".")[1] if cls.__module__.startswith("worlds.") else ""
        found.append(
            {
                "game": game,
                "version": cls.world_version.as_simple_string(),
                "module": module,
                "builtin": builtin.get(module, False),
            }
        )
    return {
        "archipelago_version": Utils.__version__,
        "worlds": found,
        # The traceback's last line is enough here; the whole thing is in log.txt.
        "failed": {
            name: reason.strip().splitlines()[-1]
            for name, reason in worlds.failed_world_loads.items()
        },
    }
