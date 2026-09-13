"""Where things live in the repository — the one place that knows the layout."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
KNOWLEDGE_BASE_DIR = PROJECT_ROOT / "knowledge_base"
SKILLS_DIR = PROJECT_ROOT / "skills"
