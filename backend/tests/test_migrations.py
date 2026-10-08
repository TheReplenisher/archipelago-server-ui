from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

from apsui import migrate, models
from apsui.config import Settings


def test_startup_creates_and_migrates_the_database(client: TestClient, settings: Settings) -> None:
    assert (settings.data_dir / "app.db").is_file()
    head = ScriptDirectory.from_config(migrate.alembic_config()).get_current_head()
    with client.app.state.engine.connect() as connection:  # type: ignore[attr-defined]
        assert MigrationContext.configure(connection).get_current_revision() == head


def test_models_match_migrations(client: TestClient) -> None:
    """Fails when a model changes without a migration (run alembic revision --autogenerate)."""
    with client.app.state.engine.connect() as connection:  # type: ignore[attr-defined]
        diff = compare_metadata(MigrationContext.configure(connection), models.Base.metadata)
    assert diff == []
