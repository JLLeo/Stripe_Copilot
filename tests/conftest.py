"""
Shared pytest configuration for the unit suite.

tests/integration/ holds standalone runnable scripts, not pytest modules —
their code executes at import time and hits the LLM and Milvus. Collecting
them would fire real API calls during `pytest`, so they are excluded here.
Run them directly instead:  python tests/integration/test_e2e.py

The suite also gets its own runtime database per run, so tests never write to
data/runtime.db and never touch the tracked seed database.
"""

import os
import sys
from pathlib import Path

import pytest

# Keep pytest away from the runnable scripts.
collect_ignore_glob = ["integration/*"]

# Make `import app` work regardless of the working directory pytest is run from.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Unit tests make no model calls, but the old pipeline still constructs an
# OpenAI client at import time, which refuses to start without a key. Give it a
# placeholder so the suite collects without a .env file. Goes away with the
# pipeline itself.
os.environ.setdefault("OPENAI_API_KEY", "unit-tests-never-call-openai")


@pytest.fixture(scope="session", autouse=True)
def _isolated_runtime_db(tmp_path_factory):
    from app import database

    os.environ["RUNTIME_DB_PATH"] = str(tmp_path_factory.mktemp("db") / "runtime.db")
    database.close_connection()
    yield
    database.close_connection()
