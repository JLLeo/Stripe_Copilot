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


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """After `pytest -m eval`: the report's headline numbers and where the full report went."""
    summary = getattr(config, "_eval_summary", None)
    if not summary:
        return
    numbers, path = summary
    mean = numbers["mean_judge_score"]
    judge = f"{mean:.1f}/5" if mean is not None else "n/a"
    terminalreporter.section("evaluation")
    terminalreporter.write_line(
        f"first-action accuracy {numbers['first_action_matched']}/{numbers['cases']} ({numbers['first_action_accuracy']:.0%}) "
        f"- leak-free {numbers['leak_free']}/{numbers['cases']} - mean judge score {judge}"
    )
    terminalreporter.write_line(f"cases passed {numbers['passed']}/{numbers['cases']} - report: {path}")


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


def customers(client) -> list[dict]:
    """The signed-in choices — the list without its 'new prospect' entry."""
    return [c for c in client.get("/api/customers").json() if c["customer_id"]]


def first_customer(client) -> dict:
    return customers(client)[0]


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
