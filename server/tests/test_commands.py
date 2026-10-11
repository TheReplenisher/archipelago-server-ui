"""The console's command catalog, from a stand-in for MultiServer.py's command
processors. The image builds it from the real MultiServer.py, which fails the build if a
mapped argument has gone."""

import json
from pathlib import Path

import pytest

from apsui_server import commands
from apsui_server.commands import CatalogError, catalog

SOURCE = '''
class CommandMeta(type):
    pass

def mark_raw(function):
    return function

class Context:
    simple_options = {"hint_cost": int, "release_mode": str}

class CommandProcessor(metaclass=CommandMeta):
    def _cmd_help(self):
        """Returns the help listing"""

class CommonCommandProcessor(CommandProcessor):
    def _cmd_options(self):
        """List all current options."""

class ServerCommandProcessor(CommonCommandProcessor):
    def _cmd_help(self):
        """Overridden: keeps its place."""

    def _cmd_exit(self):
        """Shutdown the server"""

    @mark_raw
    def _cmd_release(self, player_name: str) -> bool:
        """Send out the remaining items from a player to their intended recipients."""

    @mark_raw
    def _cmd_alias(self, player_name_then_alias_name):
        """Set a player's alias."""

    def _cmd_countdown(self, seconds: str = "10") -> bool:
        """Start a countdown in seconds"""

    def _cmd_status(self, tag: str = "") -> bool:
        """Get status information about teams."""

    def _cmd_send(self, player_name: str, *item_name: str) -> bool:
        """Sends an item to the specified player"""

    def _cmd_option(self, option_name: str, option_value: str):
        """Set an option for the server."""

    def _not_a_command(self):
        pass
'''

KINDS = {
    ("release", "player_name"): "player",
    ("countdown", "seconds"): "number",
    ("send", "player_name"): "player",
    ("send", "item_name"): "item",
    ("option", "option_name"): "option",
}
SPLIT = {
    ("alias", "player_name_then_alias_name"): [("player_name", "player"), ("alias_name", "text")]
}


def by_name() -> dict[str, dict[str, object]]:
    return {c["name"]: c for c in catalog(SOURCE, KINDS, SPLIT)["commands"]}


def test_commands_are_collected_like_commandmeta() -> None:
    names = [c["name"] for c in catalog(SOURCE, KINDS, SPLIT)["commands"]]
    assert names == [
        "help", "options", "release", "alias", "countdown", "status", "send", "option"
    ]  # fmt: skip
    assert by_name()["help"]["help"] == "Overridden: keeps its place."


def test_arguments_carry_their_kind_and_shape() -> None:
    commands = by_name()
    assert commands["send"] == {
        "name": "send",
        "help": "Sends an item to the specified player",
        "raw": False,
        "args": [
            {"name": "player_name", "kind": "player", "required": True, "rest": False},
            {"name": "item_name", "kind": "item", "required": True, "rest": True},
        ],
    }
    assert commands["release"]["raw"] is True
    assert commands["countdown"]["args"] == [
        {"name": "seconds", "kind": "number", "required": False, "rest": False, "default": "10"}
    ]
    assert commands["status"]["args"] == [
        {"name": "tag", "kind": "text", "required": False, "rest": False}
    ]


def test_a_split_argument_and_the_option_names() -> None:
    commands = by_name()
    assert [(a["name"], a["kind"]) for a in commands["alias"]["args"]] == [
        ("player_name", "player"),
        ("alias_name", "text"),
    ]
    assert commands["option"]["args"][0]["choices"] == ["hint_cost", "release_mode"]


def test_refused_commands_are_not_offered() -> None:
    assert "exit" not in by_name()


def test_a_mapped_argument_that_is_gone_fails() -> None:
    with pytest.raises(CatalogError, match=r"\('send', 'item'\)"):
        catalog(SOURCE, KINDS | {("send", "item"): "item"}, SPLIT)


def test_main_writes_the_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, output = tmp_path / "MultiServer.py", tmp_path / "commands.json"
    source.write_text(SOURCE)
    monkeypatch.setattr(commands, "ARG_KINDS", KINDS)
    monkeypatch.setattr(commands, "SPLIT_ARGS", SPLIT)
    monkeypatch.setattr("sys.argv", ["commands", str(source), str(output)])
    commands.main()
    assert json.loads(output.read_text()) == catalog(SOURCE, KINDS, SPLIT)


def test_main_fails_on_a_stale_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real map against the stand-in: as an Archipelago upgrade that renamed things."""
    source = tmp_path / "MultiServer.py"
    source.write_text(SOURCE)
    monkeypatch.setattr("sys.argv", ["commands", str(source), str(tmp_path / "out.json")])
    with pytest.raises(SystemExit, match="Mapped arguments no longer in"):
        commands.main()
    assert not (tmp_path / "out.json").exists()
