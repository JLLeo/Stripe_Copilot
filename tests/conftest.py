"""
Shared pytest configuration.

Every run gets its own runtime database, so tests never write to
data/runtime.db and never touch the tracked seed database. No test talks to a
model: the app always starts with a harness over a ScriptedProvider, and tests
that need to script replies install their own.
"""

import os
import sys
from pathlib import Path

import pytest

# Make `import app` work regardless of the working directory pytest is run from.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture(scope="session", autouse=True)
def _isolated_runtime_db(tmp_path_factory):
    from app import database

    os.environ["RUNTIME_DB_PATH"] = str(tmp_path_factory.mktemp("db") / "runtime.db")
    database.close_connection()
    yield
    database.close_connection()


@pytest.fixture(scope="session", autouse=True)
def _scripted_default_harness(_isolated_runtime_db):
    """The app never builds the production provider under test."""
    from app import main
    from app.harness.core import Harness
    from app.harness.scripted import ScriptedProvider

    main.app.state.harness = Harness.build(provider=ScriptedProvider())
    yield
    main.app.state.harness = None
