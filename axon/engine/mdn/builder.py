"""
AXON Engine — MDN Corpus Builder
====================================
Constructs CorpusGraph instances from document definitions and edge specifications.

This is the entry point for creating corpus graphs programmatically.
The builder enforces all invariants from §2.1 (Definition 1) during construction.

Usage:
    builder = CorpusBuilder("LegalCorpus")
    builder.add_document("ley123", "Ley 123", doc_type="statute")
    builder.add_document("reglamento", "Reglamento", doc_type="regulation")
    builder.add_edge("ley123", "reglamento", "implement", weight=0.9)
    corpus = builder.build()
"""

from __future__ import annotations

from typing import Any

from axon.engine.mdn.corpus_graph import (
    CorpusGraph,
    Document,
    Edge,
    RelationType,
    STANDARD_RELATION_TYPES,
)


class CorpusBuilder:
    """Builder for constructing CorpusGraph instances.

    Provides a fluent API for incrementally defining a corpus
    and validates all constraints before returning the final graph.
    """

    def __init__(self, name: str = "") -> None:
        self.name = name
        self._documents: list[Document] = []
        self._edge_specs: list[dict[str, Any]] = []
        self._relation_types: dict[str, RelationType] = {}

        # Register standard relation types
        for rel_name in STANDARD_RELATION_TYPES:
            self._relation_types[rel_name] = RelationType(name=rel_name)

    def add_document(
        self,
        doc_id: str,
        title: str,
        doc_type: str = "generic",
        summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> "CorpusBuilder":
        """Add a document to the corpus.

        Args:
            doc_id:   Unique document identifier.
            title:    Document title.
            doc_type: Semantic type (§4.3 extensible ontology).
            summary:  Document summary for relevance scoring.
            metadata: Optional metadata dictionary.

        Returns:
            self (for fluent chaining).
        """
        self._documents.append(Document(
            doc_id=doc_id,
            title=title,
            doc_type=doc_type,
            summary=summary,
            metadata=metadata or {},
        ))
        return self

    def add_relation_type(
        self,
        name: str,
        properties: set[str] | None = None,
        domain_constraint: tuple[str, str] | None = None,
    ) -> "CorpusBuilder":
        """Register a custom relation type.

        Only needed for non-standard relations. Standard types
        (cite, depend, contradict, etc.) are pre-registered.

        Args:
            name:              Relation type name.
            properties:        Modal properties (reflexive, transitive, etc.).
            domain_constraint: (source_type, target_type) restriction.

        Returns:
            self (for fluent chaining).
        """
        self._relation_types[name] = RelationType(
            name=name,
            properties=frozenset(properties) if properties else frozenset(),
            domain_constraint=domain_constraint,
        )
        return self

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        weight: float = 1.0,
    ) -> "CorpusBuilder":
        """Add an edge between two documents.

        The edge will be validated during build().

        Args:
            source_id: Source document ID.
            target_id: Target document ID.
            relation:  Relation type name.
            weight:    Edge weight ∈ (0, 1].

        Returns:
            self (for fluent chaining).
        """
        self._edge_specs.append({
            "source_id": source_id,
            "target_id": target_id,
            "relation": relation,
            "weight": weight,
        })
        return self

    def build(self) -> CorpusGraph:
        """Build and return the CorpusGraph.

        Validates all constraints from Definition 1, §2.1:
            - (G1) Finite corpus (guaranteed by construction)
            - (G2) Edge endpoints exist in D
            - (G3) Edge types are defined (total τ)
            - (G4) Weights in (0, 1]

        Raises:
            ValueError: If any constraint is violated.
        """
        corpus = CorpusGraph(name=self.name)

        # Add all documents first
        for doc in self._documents:
            corpus.add_document(doc)

        # Then add edges (validates G2 automatically)
        for spec in self._edge_specs:
            rel_name = spec["relation"]
            if rel_name not in self._relation_types:
                raise ValueError(
                    f"Unknown relation type '{rel_name}'. "
                    f"Known types: {sorted(self._relation_types.keys())}. "
                    f"Register custom types with add_relation_type() first."
                )
            rel_type = self._relation_types[rel_name]
            edge = Edge(
                source_id=spec["source_id"],
                target_id=spec["target_id"],
                relation=rel_type,
                weight=spec["weight"],
            )
            corpus.add_edge(edge)  # validates G2

        return corpus
