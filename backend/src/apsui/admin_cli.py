"""`apsui-admin`: admin tasks from a shell on the host (#32).

Anyone who can run this can already read the database, so it needs no password of its
own. It is how the admin password is set or reset without the web UI: after a forgotten
password, or to take back an install whose password someone else set first.

    docker compose exec web apsui-admin set-password      (Compose)
    apsui-admin set-password                              (LXC, as root)
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import func, select

from apsui import admin_auth, audit, migrate
from apsui.config import get_settings
from apsui.db import make_engine, make_sessionmaker
from apsui.models import AdminSession


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apsui-admin", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    set_password = commands.add_parser(
        "set-password", help="set the admin password and log every admin out"
    )
    set_password.add_argument(
        "--password-stdin", action="store_true", help="read the new password from stdin"
    )
    commands.add_parser("status", help="whether the admin password is set")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.data_dir.is_dir():
        print(f"No data folder at {settings.data_dir}: is APSUI_DATA_DIR right?", file=sys.stderr)
        return 1
    engine = make_engine(settings.database_url)
    migrate.upgrade(engine)
    with make_sessionmaker(engine)() as session:
        if args.command == "status":
            admin = admin_auth.get_admin(session)
            sessions = session.scalar(select(func.count()).select_from(AdminSession)) or 0
            if admin is None:
                print("The admin password isn't set: the first person to open Admin sets it.")
            else:
                # Not the date it changed: CodeQL reads any "password" attribute as the secret.
                print("The admin password is set.")
                print(f"Logged-in admin sessions: {sessions}")
            return 0
        password = _read_password(args.password_stdin)
        try:
            admin_auth.set_password(session, password)
        except admin_auth.AuthError as exc:
            print(exc.message, file=sys.stderr)
            return 1
        audit.record(session, actor="shell", action="set_password_shell", status=0)
    print("The admin password is set. Every admin session was logged out.")
    return 0


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("New admin password: ")
    if getpass.getpass("Again: ") != first:
        print("The passwords don't match.", file=sys.stderr)
        raise SystemExit(1)
    return first


if __name__ == "__main__":
    raise SystemExit(main())
