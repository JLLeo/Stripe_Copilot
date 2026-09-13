"""
The knowledge graph — products and the things they relate to.

`knowledge_base/knowledge_graph.yaml` lists entities by type (products,
payment methods, compliance standards, geographies, customer types, …) and
`[subject, predicate, object]` relationships between them. This module loads
it into a `networkx.DiGraph` and answers the two questions retrieval asks:

- which products relate to this product one hop away (Graph Expansion), and
- which products does this non-product entity point at (a compliance
  standard, a payment method, a geography, a customer type).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import networkx as nx
import yaml

from app.paths import KNOWLEDGE_BASE_DIR

KG_YAML_PATH = KNOWLEDGE_BASE_DIR / "knowledge_graph.yaml"

# Predicates that make two products neighbours for expansion purposes.
PRODUCT_NEIGHBOUR_PREDICATES = ("integrates_with", "cross_sell")
# Entity types the model may name as topics; each maps to products through
# the inbound predicate listed.
TOPIC_TYPES: dict[str, str] = {
    "compliance": "complies_with",
    "payment_method": "supports_method",
    "geography": "available_in",
    "customer_type": "suitable_for",
}


class KnowledgeGraph:
    def __init__(self, yaml_path: Path | None = None):
        self.path = yaml_path or KG_YAML_PATH
        self.graph = nx.DiGraph()
        self._nodes: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        for entity_type, items in (data.get("entities") or {}).items():
            for item in items:
                node = {**item, "entity_type": entity_type}
                self.graph.add_node(item["id"], **node)
                self._nodes[item["id"]] = node
        for subject, predicate, obj in data.get("relationships") or []:
            self.graph.add_edge(subject, obj, predicate=predicate)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------
    def node(self, node_id: str) -> dict[str, Any] | None:
        return self._nodes.get(node_id)

    def name(self, node_id: str) -> str:
        node = self._nodes.get(node_id)
        return (node or {}).get("name") or node_id

    def ids_of_type(self, entity_type: str) -> list[str]:
        return [nid for nid, n in self._nodes.items() if n["entity_type"] == entity_type]

    def type_of(self, node_id: str) -> str | None:
        node = self._nodes.get(node_id)
        return node["entity_type"] if node else None

    def topic_ids(self) -> list[str]:
        """Every entity the model may name as a topic, sorted."""
        return sorted(t for entity_type in TOPIC_TYPES for t in self.ids_of_type(entity_type))

    def targets(self, node_id: str, predicate: str) -> list[str]:
        """Nodes reached from `node_id` along one predicate, sorted."""
        if not self.graph.has_node(node_id):
            return []
        return sorted(t for _, t, d in self.graph.out_edges(node_id, data=True) if d.get("predicate") == predicate)

    # ------------------------------------------------------------------
    # Graph Expansion
    # ------------------------------------------------------------------
    def related_products(self, product_id: str) -> list[str]:
        """Products one hop away along integration / cross-sell edges, either direction."""
        out: set[str] = set()
        for _, target, data in self.graph.out_edges(product_id, data=True):
            if data.get("predicate") in PRODUCT_NEIGHBOUR_PREDICATES and self.type_of(target) == "product":
                out.add(target)
        for source, _, data in self.graph.in_edges(product_id, data=True):
            if data.get("predicate") in PRODUCT_NEIGHBOUR_PREDICATES and self.type_of(source) == "product":
                out.add(source)
        out.discard(product_id)
        return sorted(out)

    def products_for(self, topic_id: str) -> list[str]:
        """Products that point at a topic entity (comply with it, support it, are available in it, suit it)."""
        predicate = TOPIC_TYPES.get(self.type_of(topic_id) or "")
        if predicate is None:
            return []
        return sorted(
            source
            for source, _, data in self.graph.in_edges(topic_id, data=True)
            if data.get("predicate") == predicate and self.type_of(source) == "product"
        )

    def summary(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for n in self._nodes.values():
            by_type[n["entity_type"]] = by_type.get(n["entity_type"], 0) + 1
        return {"nodes": self.graph.number_of_nodes(), "edges": self.graph.number_of_edges(), "by_type": by_type}
