"""The admin console's command catalog (DESIGN.md §5, admin console; #26).

It is generated from the pinned Archipelago's own command handlers: every command of
MultiServer's ServerCommandProcessor, as CommandMeta collects them (base classes first),
with its arguments, whether it takes its text raw, and its help text. A hand-maintained
map then says what each argument is (a player, an item, a location, a number...), so the
console can offer the right input for it.

MultiServer.py is parsed, never imported: like the rest of this package, this never runs
Archipelago code. The image runs it at build time:

    python -m apsui_server.commands /opt/archipelago/MultiServer.py /opt/apsui/commands.json

A mapped argument that no longer exists fails the build, so an Archipelago upgrade that
renames a handler's arguments is noticed instead of quietly losing its assistance.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

PROCESSOR = "ServerCommandProcessor"

ARG_KINDS: dict[tuple[str, str], str] = {
    ("status", "tag"): "text",
    ("collect", "player_name"): "player",
    ("countdown", "seconds"): "number",
    ("release", "player_name"): "player",
    ("allow_release", "player_name"): "player",
    ("forbid_release", "player_name"): "player",
    ("send_multiple", "amount"): "number",
    ("send_multiple", "player_name"): "player",
    ("send_multiple", "item_name"): "item",
    ("send", "player_name"): "player",
    ("send", "item_name"): "item",
    ("send_location", "player_name"): "player",
    ("send_location", "location_name"): "location",
    ("hint", "player_name"): "player",
    ("hint", "item_name"): "item",
    ("hint_location", "player_name"): "player",
    ("hint_location", "location_name"): "location",
    ("option", "option_name"): "option",
    ("option", "option_value"): "text",
}
"""(command, argument) -> what it is. Anything not listed is plain text."""

SPLIT_ARGS: dict[tuple[str, str], list[tuple[str, str]]] = {
    # A raw argument the handler splits at the first space itself.
    ("alias", "player_name_then_alias_name"): [("player_name", "player"), ("alias_name", "text")],
}

REFUSED: dict[str, str] = {"exit": "Use Stop to shut the server down: it saves first"}
"""Commands the supervisor won't pass on, and why. They aren't offered either."""


class CatalogError(Exception):
    pass


def _classes(tree: ast.Module) -> dict[str, ast.ClassDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}


def _handlers(
    classes: dict[str, ast.ClassDef], name: str
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """A class's _cmd_ methods by command name, inherited ones first, as CommandMeta does."""
    handlers: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for base in classes[name].bases:
        if isinstance(base, ast.Name) and base.id in classes:
            handlers.update(_handlers(classes, base.id))
    for node in classes[name].body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and (
            node.name.startswith("_cmd_")
        ):
            handlers[node.name.removeprefix("_cmd_")] = node
    return handlers


def _server_options(classes: dict[str, ast.ClassDef]) -> list[str]:
    """The options /option knows: the keys of Context.simple_options."""
    context = classes.get("Context")
    for node in context.body if context else []:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        if names == ["simple_options"] and isinstance(value, ast.Dict):
            keys = [k.value for k in value.keys if isinstance(k, ast.Constant)]
            return [k for k in keys if isinstance(k, str)]
    return []


def _default(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    try:
        value = ast.literal_eval(node)
    except ValueError:
        return None
    return str(value)


def _arguments(
    command: str,
    handler: ast.FunctionDef | ast.AsyncFunctionDef,
    kinds: dict[tuple[str, str], str],
    split: dict[tuple[str, str], list[tuple[str, str]]],
    used: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    spec = handler.args
    positional = [*spec.posonlyargs, *spec.args][1:]  # without self
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(spec.defaults))
    defaults += spec.defaults
    params = [(p.arg, d, False) for p, d in zip(positional, defaults, strict=True)]
    if spec.vararg:  # the rest of the words, joined by the handler
        params.append((spec.vararg.arg, None, True))
    args = []
    for name, default, rest in params:
        value = _default(default)
        required = default is None
        parts = split.get((command, name))
        if parts:
            used.add((command, name))
            for part, kind in parts:
                args.append({"name": part, "kind": kind, "required": required, "rest": rest})
            continue
        if (command, name) in kinds:
            used.add((command, name))
        kind = kinds.get((command, name), "text")
        arg: dict[str, Any] = {"name": name, "kind": kind, "required": required, "rest": rest}
        if value:  # an empty default just means optional
            arg["default"] = value
        args.append(arg)
    return args


def catalog(
    source: str,
    kinds: dict[tuple[str, str], str] | None = None,
    split: dict[tuple[str, str], list[tuple[str, str]]] | None = None,
) -> dict[str, Any]:
    """The catalog for MultiServer.py's source, with the maps above unless given others."""
    kinds = ARG_KINDS if kinds is None else kinds
    split = SPLIT_ARGS if split is None else split
    tree = ast.parse(source)
    classes = _classes(tree)
    if PROCESSOR not in classes:
        raise CatalogError(f"{PROCESSOR} not found")
    options = _server_options(classes)
    used: set[tuple[str, str]] = set()
    commands = []
    for name, handler in _handlers(classes, PROCESSOR).items():
        if name in REFUSED:
            continue
        args = _arguments(name, handler, kinds, split, used)
        for arg in args:
            if arg["kind"] == "option":
                arg["choices"] = options
        raw = any(isinstance(d, ast.Name) and d.id == "mark_raw" for d in handler.decorator_list)
        help_text = ast.get_docstring(handler) or ""
        commands.append({"name": name, "help": help_text, "raw": raw, "args": args})
    missing = sorted((set(kinds) | set(split)) - used)
    if missing:
        raise CatalogError(f"Mapped arguments no longer in {PROCESSOR}: {missing}")
    return {"commands": commands}


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: python -m apsui_server.commands <MultiServer.py> <output.json>")
    source, output = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        result = catalog(source.read_text(encoding="utf-8"))
    except CatalogError as exc:
        sys.exit(f"command catalog: {exc}")
    output.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"command catalog: {len(result['commands'])} commands written to {output}")


if __name__ == "__main__":
    main()
