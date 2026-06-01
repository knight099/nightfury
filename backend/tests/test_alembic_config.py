"""Smoke test for Alembic configuration.

Verifies that alembic.ini is loadable and that at least one migration script
exists in the versions/ directory. Does NOT touch the database.
"""
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


BACKEND_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def test_alembic_ini_exists():
    assert ALEMBIC_INI.is_file(), f"alembic.ini missing at {ALEMBIC_INI}"


def test_alembic_has_migration_head():
    cfg = Config(str(ALEMBIC_INI))
    # Ensure script_location resolves relative to the backend dir, not cwd.
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))

    script_dir = ScriptDirectory.from_config(cfg)
    head = script_dir.get_current_head()
    assert head is not None, "No Alembic migration scripts found"

    revisions = list(script_dir.walk_revisions())
    assert len(revisions) >= 1, "Expected at least one revision"
