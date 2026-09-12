# Integration Scripts

Standalone runnable scripts — **not** pytest modules. Their code executes at
import time and calls the OpenAI API and Milvus, so `tests/conftest.py` excludes
this directory from pytest collection (`collect_ignore_glob = ["integration/*"]`).

Run them directly. They work from any working directory.

| Script | What it does | Needs |
|---|---|---|
| `test_e2e.py` | 4 multi-turn conversations, 12 turns; asserts intent, tool usage, context retention, escalation gating | LLM + Milvus |
| `test_agent.py` | Full pipeline demo, stage-by-stage; writes `result.md` at the project root | LLM + Milvus |
| `test_all_tools.py` | Exercises all 6 tools across varied scenarios | LLM + Milvus |
| `test_multiturn.py` | Multi-turn context retention | LLM + Milvus |
| `test_retrieve.py` | KG expansion → Milvus retrieval, no agent loop | Milvus + embeddings |
| `test_milvus.py` | Raw Milvus search, no KG and no agent | Milvus + embeddings |

```bash
python tests/integration/test_e2e.py
python tests/integration/test_agent.py "your custom query"
python tests/integration/test_retrieve.py
```

For the fast suite that needs none of the above:

```bash
pytest -m "not integration"      # 198 tests, ~5s
```

Note: the 5 `@pytest.mark.integration` tests in `tests/test_intent.py` and
`tests/test_tools.py` are real pytest tests and stay in the pytest tree — they
are separated by marker, not by directory.
