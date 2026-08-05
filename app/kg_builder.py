"""
Knowledge Graph Builder
========================
Loads knowledge_graph.yaml into a networkx DiGraph.
Provides lookup methods for entity resolution and graph traversal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import networkx as nx
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
KG_YAML_PATH = Path(__file__).resolve().parent.parent / "knowledge_base" / "knowledge_graph.yaml"


# ---------------------------------------------------------------------------
# Graph loader
# ---------------------------------------------------------------------------
class KnowledgeGraph:
    """In-memory knowledge graph built from YAML definitions."""

    def __init__(self, yaml_path: Path | None = None):
        self.yaml_path = yaml_path or KG_YAML_PATH
        self.graph = nx.DiGraph()
        self._entity_index: dict[str, dict] = {}  # id → {type, name, ...}
        self._scenario_patterns: dict[str, list[str]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Load from YAML
    # ------------------------------------------------------------------
    def _load(self) -> None:
        with open(self.yaml_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        # --- entities ---
        entities_section = data.get("entities", {})
        for entity_type, items in entities_section.items():
            for item in items:
                eid = item["id"]
                item["entity_type"] = entity_type
                self.graph.add_node(eid, **item)
                self._entity_index[eid] = item

                # Index question patterns for fast matching
                if entity_type == "sales_scenario" and "question_patterns" in item:
                    self._scenario_patterns[eid] = item["question_patterns"]

        # --- relationships ---
        rels = data.get("relationships", [])
        for rel in rels:
            subj, pred, obj = rel[0], rel[1], rel[2]
            self.graph.add_edge(subj, obj, predicate=pred)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------
    def get_node(self, node_id: str) -> dict | None:
        """Return full entity dict for a node, or None."""
        return self._entity_index.get(node_id)

    def get_nodes_by_type(self, entity_type: str) -> list[dict]:
        """Return all entities of a given type."""
        return [v for v in self._entity_index.values() if v.get("entity_type") == entity_type]

    def get_products_for_scenario(self, scenario_id: str) -> list[str]:
        """Return product ids connected to a sales scenario via `used_for`."""
        products = set()
        for _, neighbor, edge_data in self.graph.out_edges(scenario_id, data=True):
            if edge_data.get("predicate") == "used_for":
                products.add(neighbor)
        for pred, _ in self.graph.in_edges(scenario_id):
            edge = self.graph.get_edge_data(pred, scenario_id)
            if edge and edge.get("predicate") == "used_for":
                products.add(pred)
        return list(products)

    def get_related_products(self, product_id: str, radius: int = 1) -> list[str]:
        """Return products within N hops via integrates_with / cross_sell edges."""
        related = set()
        for node in nx.descendants_at_distance(self.graph, product_id, radius):
            if self._entity_index.get(node, {}).get("entity_type") == "product":
                related.add(node)
        return [p for p in related if p != product_id]

    def get_payment_methods(self, product_id: str) -> list[str]:
        """Return payment methods supported by a product."""
        methods = []
        for _, neighbor, edge_data in self.graph.out_edges(product_id, data=True):
            if edge_data.get("predicate") == "supports_method":
                methods.append(neighbor)
        return methods

    def get_compliance_standards(self, product_id: str) -> list[str]:
        """Return compliance standards met by a product."""
        standards = []
        for _, neighbor, edge_data in self.graph.out_edges(product_id, data=True):
            if edge_data.get("predicate") == "complies_with":
                standards.append(neighbor)
        return standards

    def get_scenario_patterns(self) -> dict[str, list[str]]:
        """Return {scenario_id: [keyword patterns]} for query matching."""
        return self._scenario_patterns

    # ------------------------------------------------------------------
    # Debug / export
    # ------------------------------------------------------------------
    def summary(self) -> dict:
        """Return a high-level summary of the graph."""
        entity_counts = {}
        for item in self._entity_index.values():
            et = item.get("entity_type", "unknown")
            entity_counts[et] = entity_counts.get(et, 0) + 1

        edge_counts = {}
        for _u, _v, data in self.graph.edges(data=True):
            pred = data.get("predicate", "unknown")
            edge_counts[pred] = edge_counts.get(pred, 0) + 1

        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "entities_by_type": entity_counts,
            "edges_by_predicate": edge_counts,
        }

    def export_json(self, path: Path | None = None) -> Path:
        """Export the graph as a node-link JSON for visualization."""
        data = nx.node_link_data(self.graph, edges="links")
        out = path or self.yaml_path.parent / "knowledge_graph.json"
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        return out


# ---------------------------------------------------------------------------
# Singleton convenience
# ---------------------------------------------------------------------------
_kg_instance: KnowledgeGraph | None = None


def get_knowledge_graph() -> KnowledgeGraph:
    """Return (and cache) the singleton KnowledgeGraph instance."""
    global _kg_instance
    if _kg_instance is None:
        _kg_instance = KnowledgeGraph()
    return _kg_instance


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    kg = KnowledgeGraph()
    print("=== Knowledge Graph Summary ===")
    s = kg.summary()
    print(f"Nodes: {s['total_nodes']}  |  Edges: {s['total_edges']}")
    print(f"Entity types: {s['entities_by_type']}")
    print(f"Edge predicates: {s['edges_by_predicate']}")

    # Test: what products for "marketplace" scenario?
    products = kg.get_products_for_scenario("marketplace")
    print(f"\nProducts for 'marketplace' scenario: {products}")

    # Test: 1-hop neighbors of checkout
    related = kg.get_related_products("checkout", radius=1)
    print(f"Products related to Checkout (1-hop): {related}")

    # Test: payment methods of checkout
    methods = kg.get_payment_methods("checkout")
    print(f"Payment methods supported by Checkout: {methods}")
