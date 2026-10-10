"""A sample world for Archipelago Server UI's tests. It does nothing."""

from worlds.AutoWorld import World


class APSUIMismatchWorld(World):
    """Sample world."""

    game = "APSUI Actual Game"
    item_name_to_id = {"Sample Item": 1}
    location_name_to_id = {"Sample Location": 1}
