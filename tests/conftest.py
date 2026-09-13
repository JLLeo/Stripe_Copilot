"""
Shared pytest configuration and fixtures.

Every run gets its own runtime database, so tests never write to
data/runtime.db and never touch the tracked seed database. No test talks to a
model: the app always starts with a harness over a ScriptedProvider, and tests
that script replies get their own via the `client` / `provider` fixtures.
"""

import json
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


# ---------------------------------------------------------------------------
# Driving the HTTP seam with a scripted provider
# ---------------------------------------------------------------------------
@pytest.fixture
def provider():
    from app.harness.scripted import ScriptedProvider

    return ScriptedProvider()


@pytest.fixture
def harness_config(request):
    """Override per test with `@pytest.mark.parametrize("harness_config", [HarnessConfig(...)], indirect=True)`."""
    from app.harness.core import HarnessConfig

    return getattr(request, "param", None) or HarnessConfig()


@pytest.fixture
def client(tmp_path, monkeypatch, provider, harness_config):
    """TestClient over the app with a fresh runtime DB and a harness on `provider`."""
    from fastapi.testclient import TestClient

    from app import database, main
    from app.harness.core import Harness

    monkeypatch.setenv("RUNTIME_DB_PATH", str(tmp_path / "runtime.db"))
    database.close_connection()
    previous = main.app.state.harness
    main.app.state.harness = Harness.build(provider=provider, config=harness_config)
    with TestClient(main.app) as c:
        yield c
    main.app.state.harness = previous
    database.close_connection()


def sse_events(body: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into (event, data) pairs."""
    out = []
    for block in body.strip().split("\n\n"):
        event, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        out.append((event, data))
    return out


def first_customer(client) -> dict:
    return client.get("/api/customers").json()[0]


def chat(client, session_id: str, message: str, customer_id: str | None = None):
    body = {"session_id": session_id, "message": message}
    if customer_id:
        body["customer_id"] = customer_id
    return client.post("/sales-agent/chat", json=body)


# ---------------------------------------------------------------------------
# A fixture knowledge base indexed once per session through the fake embedder
# ---------------------------------------------------------------------------
FIXTURE_EMBEDDING_DIM = 64


@pytest.fixture(scope="session")
def knowledge_base(tmp_path_factory) -> Path:
    from tests.fixture_kb import DOCS

    root = tmp_path_factory.mktemp("kb")
    for rel, text in DOCS.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


@pytest.fixture(scope="session")
def index_uri(tmp_path_factory, knowledge_base) -> str:
    """A real Milvus Lite index of the fixture knowledge base (dense + BM25), built once."""
    from app.harness.scripted import ScriptedProvider
    from app.retrieval.index import build_index

    uri = str(tmp_path_factory.mktemp("milvus") / "knowledge.db")
    report = build_index(
        provider=ScriptedProvider(embedding_dim=FIXTURE_EMBEDDING_DIM),
        knowledge_base=knowledge_base,
        milvus_uri=uri,
        rebuild=True,
    )
    assert report["documents"] == 3 and report["chunks"] >= 6
    return uri
