"""
Shared pytest configuration for the unit suite.

tests/integration/ holds standalone runnable scripts, not pytest modules —
their code executes at import time and hits the LLM and Milvus. Collecting
them would fire real API calls during `pytest`, so they are excluded here.
Run them directly instead:  python tests/integration/test_e2e.py
"""

import sys
from pathlib import Path

# Keep pytest away from the runnable scripts.
collect_ignore_glob = ["integration/*"]

# Make `import app` work regardless of the working directory pytest is run from.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
