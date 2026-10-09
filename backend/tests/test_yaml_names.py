import pytest
import yaml

from apsui.yaml_names import InvalidName, check_new_name, set_names


def names_of(text: str) -> list[object]:
    return [d.get("name") if isinstance(d, dict) else None for d in yaml.safe_load_all(text)]


def test_replaces_a_weighted_name_and_keeps_the_rest() -> None:
    text = (
        "# my settings\n"
        "name:\n  Alice: 1\n  Bob: 2  # either\n"
        "game: APQuest\n"
        "APQuest:\n  hard_mode: true  # keep me\n"
    )
    out = set_names(text, {0: "Carol"})
    assert names_of(out) == ["Carol"]
    assert "# my settings\n" in out and "hard_mode: true  # keep me" in out
    assert yaml.safe_load(out)["APQuest"] == {"hard_mode": True}


def test_only_the_chosen_documents_change() -> None:
    text = "name: A%number%\ngame: X\n---\n---\nname: Keep\ngame: Y\n---\nname: TooLongNameForAP!\n"
    out = set_names(text, {0: "Ann", 3: "Short"})
    assert names_of(out) == ["Ann", None, "Keep", "Short"]


def test_adds_a_missing_name() -> None:
    out = set_names("game: APQuest\nAPQuest: {}\n", {0: "Newbie"})
    assert yaml.safe_load(out) == {"name": "Newbie", "game": "APQuest", "APQuest": {}}


def test_flow_style_and_odd_characters() -> None:
    out = set_names('name: {"A": 1, "B": 1}\ngame: X\n', {0: 'Zoë "Z"'})
    assert yaml.safe_load(out)["name"] == 'Zoë "Z"'


def test_a_leading_document_marker() -> None:
    out = set_names("---\nname: [A, B]\ngame: X\n", {0: "A"})
    assert names_of(out) == ["A"]


@pytest.mark.parametrize("bad", ["", "   ", "x" * 17, "P%number%", "Archipelago"])
def test_new_names_follow_the_same_rules(bad: str) -> None:
    with pytest.raises(InvalidName):
        check_new_name(bad)


def test_new_names_are_trimmed() -> None:
    assert check_new_name("  Bob  ") == "Bob"
