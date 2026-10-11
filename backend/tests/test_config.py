"""Runtime settings."""

import pytest
from pydantic import ValidationError

from apsui.config import Settings


@pytest.mark.parametrize(
    ("published", "port"),
    [("8000", 8000), ("127.0.0.1:8000", 8000), ("[::1]:8080", 8080)],
)
def test_a_published_port_may_name_a_host_address(
    monkeypatch: pytest.MonkeyPatch, published: str, port: int
) -> None:
    """Compose passes APSUI_WEB_PORT through, and binding it to localhost (behind a
    reverse proxy on the same host) must not stop the web service starting."""
    monkeypatch.setenv("APSUI_PUBLIC_WEB_PORT", published)
    monkeypatch.setenv("APSUI_PUBLIC_GAME_PORT", published)
    settings = Settings()
    assert (settings.public_web_port, settings.public_game_port) == (port, port)


def test_allowed_hosts_come_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compared as browsers send them: lower case, no port, no trailing dot."""
    monkeypatch.setenv("APSUI_ALLOWED_HOSTS", " Apsui.Home.Example , *.ts.example:443,, nas. ")
    assert Settings().allowed_hosts == ["apsui.home.example", "*.ts.example", "nas"]
    monkeypatch.setenv("APSUI_ALLOWED_HOSTS", "")
    assert Settings().allowed_hosts == []


@pytest.mark.parametrize("value", ["https://apsui.example", "apsui.example/admin", ":8000"])
def test_allowed_hosts_are_names_not_urls(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("APSUI_ALLOWED_HOSTS", value)
    with pytest.raises(ValidationError, match="isn't a host name"):
        Settings()
