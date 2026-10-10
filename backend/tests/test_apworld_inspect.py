import io
import stat
import zipfile

import pytest
from apworld_files import MANIFEST, make_apworld

from apsui.apworld_inspect import InspectionError, inspect_apworld, version_tuple


def test_a_good_apworld_is_described() -> None:
    data = make_apworld()
    found = inspect_apworld("sample_game.apworld", data, "0.6.8")
    assert (found.module, found.game, found.world_version) == (
        "sample_game",
        "Sample Game",
        "1.2.0",
    )
    assert found.authors == ["Someone"]
    assert found.size == len(data) and len(found.sha256) == 64
    assert [f["name"] for f in found.files] == [
        "sample_game/__init__.py",
        "sample_game/archipelago.json",
    ]


def test_a_manifest_at_the_top_of_the_zip_is_found() -> None:
    data = make_apworld(
        files={"sample_game/__init__.py": b"", "archipelago.json": b'{"game": "Top"}'}
    )
    assert inspect_apworld("sample_game.apworld", data).game == "Top"


def test_the_version_range_is_skipped_without_a_pinned_version() -> None:
    data = make_apworld(manifest=MANIFEST | {"minimum_ap_version": "9.0.0"})
    assert inspect_apworld("sample_game.apworld", data, "").game == "Sample Game"


def test_versions_compare_like_archipelago() -> None:
    assert version_tuple("0.6") == (0, 6, 0)
    assert version_tuple("0.6.10") > version_tuple("0.6.9")


def symlinked() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("sample_game/__init__.py", b"")
        zf.writestr("sample_game/archipelago.json", b'{"game": "G"}')
        link = zipfile.ZipInfo("sample_game/link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(link, "/etc/passwd")
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("filename", "data", "code"),
    [
        ("sample_game.apworld", b"not a zip", "bad-zip"),
        ("sample_game.zip", make_apworld(), "not-apworld"),
        ("sample-game.apworld", make_apworld("sample-game"), "bad-file-name"),
        ("_private.apworld", make_apworld("_private"), "bad-file-name"),
        ("other_name.apworld", make_apworld(), "bad-layout"),
        (
            "sample_game.apworld",
            make_apworld(files={"sample_game/archipelago.json": b'{"game": "G"}'}),
            "bad-layout",
        ),
        (
            "sample_game.apworld",
            make_apworld(files={"sample_game/__init__.py": b"", "extra/x.py": b""}),
            "bad-layout",
        ),
        (
            "sample_game.apworld",
            make_apworld(files={"sample_game/__init__.py": b"", "sample_game/../x": b""}),
            "unsafe-path",
        ),
        ("sample_game.apworld", symlinked(), "unsafe-path"),
        (
            "sample_game.apworld",
            make_apworld(files={"sample_game/__init__.py": b""}),
            "manifest-missing",
        ),
        ("sample_game.apworld", make_apworld(manifest="{nope"), "manifest-invalid"),
        ("sample_game.apworld", make_apworld(manifest="[1]"), "manifest-invalid"),
        (
            "sample_game.apworld",
            make_apworld(manifest='{"world_version": "1"}'),
            "manifest-no-game",
        ),
        (
            "sample_game.apworld",
            make_apworld(manifest=MANIFEST | {"world_version": "one"}),
            "manifest-bad-version",
        ),
        (
            "sample_game.apworld",
            make_apworld(manifest=MANIFEST | {"compatible_version": 8}),
            "manifest-too-new",
        ),
        (
            "sample_game.apworld",
            make_apworld(manifest=MANIFEST | {"authors": [1]}),
            "manifest-bad-authors",
        ),
        (
            "sample_game.apworld",
            make_apworld(manifest=MANIFEST | {"minimum_ap_version": "0.7.0"}),
            "ap-too-old",
        ),
        (
            "sample_game.apworld",
            make_apworld(manifest=MANIFEST | {"maximum_ap_version": "0.6.5"}),
            "ap-too-new",
        ),
    ],
)
def test_bad_apworlds_are_refused(filename: str, data: bytes, code: str) -> None:
    with pytest.raises(InspectionError) as caught:
        inspect_apworld(filename, data, "0.6.8")
    assert caught.value.code == code
