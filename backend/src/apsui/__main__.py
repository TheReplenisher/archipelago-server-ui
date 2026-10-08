import uvicorn

from apsui.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "apsui.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
    )


if __name__ == "__main__":
    main()
