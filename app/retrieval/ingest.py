"""
Rebuild the knowledge index.

    python -m app.retrieval.ingest              # rebuild milvus.db from knowledge_base/
    python -m app.retrieval.ingest --uri PATH   # rebuild somewhere else

Every collection at the target is dropped first, so the index always mirrors
the current public documents — no stale chunks from files that shrank or
moved. Only documents whose header says `Access Level: public` are indexed,
into the dense and BM25 collections, embedding through the production Provider.
"""

from __future__ import annotations

import argparse

from dotenv import load_dotenv

from app.harness.deepseek import DeepSeekProvider
from app.paths import KNOWLEDGE_BASE_DIR
from app.retrieval.index import DEFAULT_MILVUS_URI, build_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild the public knowledge index in Milvus Lite")
    parser.add_argument("--uri", default=DEFAULT_MILVUS_URI, help="Milvus Lite database path")
    args = parser.parse_args()

    load_dotenv()
    report = build_index(
        provider=DeepSeekProvider.from_env(),
        knowledge_base=KNOWLEDGE_BASE_DIR,
        milvus_uri=args.uri,
        rebuild=True,
    )
    print(f"indexed {report['chunks']} chunks from {report['documents']} public documents "
          f"into {', '.join(report['collections'])} at {args.uri}")


if __name__ == "__main__":
    main()
