# Hybrid retrieval via a sibling Milvus collection

Product names, API fields, and abbreviations ("IC+", "SCA", "3DS") are exact tokens
that dense retrieval handles poorly, so retrieval is hybrid: dense vectors plus Milvus
native BM25 sparse vectors, fused with reciprocal rank fusion, with the knowledge-graph
scalar filter applied to both legs.

Milvus would normally hold both indexes in one collection and fuse server-side, but
Milvus Lite on Windows fails when a second index is created on a collection (a manifest
rename error, `WinError 183`, reproduced with pymilvus 3.0.0). The BM25 index therefore
lives in a sibling collection with the same chunks and metadata, ingestion writes to
both, and fusion happens in the retriever. If the project moves to a Milvus server, the
two collections can be merged and fusion moved to `hybrid_search` without changing the
tool contract.
