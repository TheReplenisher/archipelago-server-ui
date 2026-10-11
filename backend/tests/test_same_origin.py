"""Pages on other websites can't use the web UI or its API (apsui.same_origin)."""

import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from apsui.config import Settings
from apsui.main import create_app
from apsui.same_origin import SAFE_METHODS, host_allowed, hostname

LAN = "http://192.168.1.10:8000"
EVIL = "http://evil.example"


@pytest.fixture
def lan(settings: Settings) -> Iterator[TestClient]:
    """The admin's browser on the default install: plain HTTP, by address."""
    settings.job_poll_interval = 3600
    with TestClient(create_app(settings), base_url=LAN) as c:
        yield c


def game_state(client: TestClient) -> str:
    state: str = client.get("/api/game").json()["state"]
    return state


def test_every_unsafe_route_refuses_other_sites(settings: Settings) -> None:
    """The guard sits in front of the whole app, so routes added later are covered too."""
    app = create_app(settings)
    routes = [
        (method.upper(), re.sub(r"\{[^}]+\}", "1", path))
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method.upper() not in SAFE_METHODS
    ]
    assert len(routes) >= 10
    with TestClient(app, base_url=LAN) as client:
        for method, path in routes:
            response = client.request(method, path, headers={"origin": EVIL})
            assert response.status_code == 403, (method, path, response.text)
            assert response.json()["detail"]["code"] == "cross-origin"
        assert game_state(client) == "open"


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": EVIL},  # plain HTTP: browsers send Sec-Fetch-* only to HTTPS
        {"origin": EVIL, "sec-fetch-site": "cross-site"},
        {"origin": "null"},  # a sandboxed frame, or a page with no-referrer
        {"origin": "http://192.168.1.10:8080"},  # another app on the same machine
        {"origin": "https://nas.home.example", "sec-fetch-site": "same-site"},
        {"origin": "http://[::1"},
    ],
)
def test_requests_from_other_sites_are_refused(lan: TestClient, headers: dict[str, str]) -> None:
    assert lan.post("/api/game/lock", headers=headers).status_code == 403
    assert game_state(lan) == "open"


def test_a_cross_site_upload_stores_nothing(lan: TestClient) -> None:
    """A form can send multipart without a preflight, and an apworld is Python code."""
    yaml = b"name: Alice\ngame: Clique\nClique: {}\n"
    for path in ("/api/uploads/yaml", "/api/apworlds"):
        response = lan.post(path, headers={"origin": EVIL}, files={"file": ("a.yaml", yaml)})
        assert response.status_code == 403
    assert lan.get("/api/uploads").json() == []
    assert lan.get("/api/apworlds").json() == []


@pytest.mark.parametrize(
    "headers",
    [
        {},  # curl, scripts, the compose test
        {"origin": LAN},  # the UI's own page, over plain HTTP
        {"origin": LAN, "sec-fetch-site": "same-origin"},
        # Behind HTTPS the browser's verdict stands, even if the proxy rewrote the port.
        {"origin": "https://192.168.1.10:8443", "sec-fetch-site": "same-origin"},
        {"sec-fetch-site": "none"},
    ],
)
def test_the_uis_own_requests_pass(lan: TestClient, headers: dict[str, str]) -> None:
    assert lan.post("/api/game/lock", headers=headers).status_code == 200
    assert game_state(lan) == "locked"


def test_links_from_other_sites_still_open_the_ui(lan: TestClient) -> None:
    response = lan.get("/admin", headers={"sec-fetch-site": "cross-site"})
    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/admin", "/api/settings", "/api/game/spoiler", "/api/health"])
def test_unknown_host_names_get_nothing(lan: TestClient, path: str) -> None:
    """DNS rebinding: the attacker's own name, pointed at this server, is same-origin with
    the attacker's page, which could then read every answer."""
    response = lan.get(path, headers={"host": "evil.example:8000"})
    assert response.status_code == 400
    assert "'evil.example'" in response.text and "APSUI_ALLOWED_HOSTS" in response.text


def test_unknown_host_names_cant_write(lan: TestClient) -> None:
    rebound = {"host": "evil.example:8000", "origin": "http://evil.example:8000"}
    assert lan.post("/api/game/lock", headers=rebound).status_code == 400
    assert game_state(lan) == "open"


def test_a_listed_name_works(settings: Settings) -> None:
    settings.allowed_hosts = ["apsui.home.example"]
    with TestClient(create_app(settings), base_url="https://apsui.home.example") as client:
        own_page = {"origin": "https://apsui.home.example", "sec-fetch-site": "same-origin"}
        assert client.post("/api/game/lock", headers=own_page).status_code == 200


@pytest.mark.parametrize("path", ["/admin", "/api/game", "/api/does-not-exist"])
def test_no_page_may_frame_the_ui(lan: TestClient, path: str) -> None:
    """Clicks inside a frame are same-origin, so framing would get round the rest."""
    response = lan.get(path)
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["content-security-policy"] == "frame-ancestors 'none'"


LISTED = ["apsui.home.example", "*.ts.example"]


@pytest.mark.parametrize(
    "host",
    [
        "192.168.1.10:8000",
        "10.0.0.5",
        "[::1]:8000",
        "[fd7a:115c:a1e0::1]",
        "localhost:5173",  # the Vite dev server passes the browser's Host through
        "LOCALHOST",
        "apsui.localhost",
        "myserver.local",
        "myserver.local.",
        "nas.home.arpa:8000",
        "apsui.internal",
        "apsui.home.example",
        "Apsui.Home.Example:443",
        "box.ts.example",
    ],
)
def test_names_answered(host: str) -> None:
    assert host_allowed(hostname(host), LISTED)


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "evil.example:8000",
        "nas",  # no dot, but DNS search domains can still make it public
        "nas.lan",  # not reserved, so not assumed local
        "ts.example",  # *. is for subdomains
        "apsui.home.example.evil.example",
        "192.168.1.10.evil.example",
        "localhost.evil.example",
        "evil-local",
        "",
        "[::1",
    ],
)
def test_names_refused(host: str) -> None:
    assert not host_allowed(hostname(host), LISTED)


def test_a_star_answers_any_name() -> None:
    assert host_allowed("anything.example", ["*"])
