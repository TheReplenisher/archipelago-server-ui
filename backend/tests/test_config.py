"""Runtime settings."""

import pytest

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
