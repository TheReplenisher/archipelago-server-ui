"""Change slot names inside an uploaded YAML, keeping everything else as the player wrote
it (comments, layout, other documents). Used when the checks found a name problem and the
admin picked a new name instead of asking for a re-upload.

Only the `name:` entry of the chosen documents is rewritten, by its exact position in the
text (PyYAML's node marks), so nothing is re-serialised. The edited file is then checked
by the worker again from scratch.
"""

from __future__ import annotations

import json

import yaml

MAX_NAME_LENGTH = 16


class InvalidName(ValueError):
    pass


def check_new_name(name: str) -> str:
    """The rules a name typed by the admin must meet: the same as the worker's."""
    name = name.strip()
    if not name:
        raise InvalidName("A slot name can't be empty")
    if len(name) > MAX_NAME_LENGTH:
        raise InvalidName(f"{name} is longer than 16 characters")
    if "%" in name:
        raise InvalidName("Slot names can't contain %")
    if name == "Archipelago":
        raise InvalidName("A slot can't be named Archipelago")
    return name


def set_names(text: str, names: dict[int, str]) -> str:
    """Return text with the `name:` of each document index in `names` set to that name.

    Documents are numbered as Archipelago numbers them (empty documents count). A
    document without a name gets one added at its start."""
    edits: list[tuple[int, int, str]] = []  # (start, end, replacement), by text offset
    for index, node in enumerate(yaml.compose_all(text, Loader=yaml.SafeLoader)):
        if index not in names:
            continue
        if not isinstance(node, yaml.MappingNode):
            raise InvalidName(f"Document {index + 1} is not a set of options")
        line = f"name: {json.dumps(names[index], ensure_ascii=False)}"
        entry = next(((k, v) for k, v in node.value if k.value == "name"), None)
        if entry is None:
            start = node.start_mark.index
            indent = " " * node.start_mark.column
            edits.append((start, start, f"{line}\n{indent}"))
            continue
        key, value = entry
        start, end = key.start_mark.index, value.end_mark.index
        old = text[start:end]
        trailing = old[len(old.rstrip()) :]  # a block value's span ends after its newline
        edits.append((start, end, line + trailing))
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text
