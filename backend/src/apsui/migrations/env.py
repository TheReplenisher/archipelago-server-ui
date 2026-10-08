from alembic import context
from sqlalchemy import Connection

from apsui import models
from apsui.config import get_settings
from apsui.db import make_engine

config = context.config
target_metadata = models.Base.metadata


def run_with(connection: Connection) -> None:
    # render_as_batch: SQLite can't ALTER most things in place
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


# migrate.upgrade() passes a connection; the alembic CLI does not.
connection = config.attributes.get("connection")
if connection is not None:
    run_with(connection)
else:
    url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
    with make_engine(url).begin() as cli_connection:
        run_with(cli_connection)
