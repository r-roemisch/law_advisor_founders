"""Chroma backend, vector-only: Chroma's native hybrid search needs Chroma Cloud (ADR 0005)."""

import json

import chromadb

from ..types import Hit, Passage, Query, SearchFilters, SearchMode
from .base import BACKENDS, IndexBackend


@BACKENDS.register("chroma")
class ChromaBackend(IndexBackend):
    search_modes = frozenset({"vector"})

    def __init__(self, index_name, settings, **params):
        super().__init__(index_name, settings)
        self._client = None
        self._name = f"passages_{self.slug}"

    def _collection(self):
        if self._client is None:  # connect lazily: the client contacts the server on creation
            self._client = chromadb.HttpClient(
                host=self.settings.chroma_host, port=self.settings.chroma_port
            )
        return self._client.get_or_create_collection(self._name, metadata={"hnsw:space": "cosine"})

    def upsert(self, passages: list[Passage], vectors: list[list[float]]) -> None:
        if not passages:
            return
        self._collection().upsert(
            ids=[p.id for p in passages],
            embeddings=vectors,
            documents=[p.embedding_text for p in passages],
            metadatas=[_metadata(p) for p in passages],
        )

    def delete_source(self, source_id: str, language: str) -> None:
        self._collection().delete(
            where={"$and": [{"source_id": source_id}, {"language": language}]}
        )

    def search(
        self, query: Query, vector: list[float], k: int, mode: SearchMode, filters: SearchFilters
    ) -> list[Hit]:
        result = self._collection().query(
            query_embeddings=[vector],
            n_results=k,
            where=_where(filters),
            include=["metadatas", "distances"],
        )
        metadatas = result["metadatas"][0] if result["metadatas"] else []
        distances = result["distances"][0] if result["distances"] else []
        return [
            Hit(Passage.from_payload(json.loads(m["payload"])), 1.0 - float(d))
            for m, d in zip(metadatas, distances, strict=True)
        ]

    def count(self) -> int:
        return self._collection().count()


def _metadata(p: Passage) -> dict:
    # Chroma metadata values must be scalars, so legal areas become boolean flags.
    meta = {
        "source_id": p.source.id,
        "language": p.language,
        "jurisdiction": p.source.jurisdiction,
        "tier": p.source.tier,
        "payload": json.dumps(p.to_payload()),
    }
    meta.update({f"area_{area}": True for area in p.source.legal_areas})
    return meta


def _where(filters: SearchFilters) -> dict | None:
    clauses = []
    if filters.jurisdictions:
        clauses.append({"jurisdiction": {"$in": sorted(filters.jurisdictions)}})
    if filters.tiers:
        clauses.append({"tier": {"$in": sorted(filters.tiers)}})
    if filters.legal_areas:
        areas = [{f"area_{a}": True} for a in sorted(filters.legal_areas)]
        clauses.append(areas[0] if len(areas) == 1 else {"$or": areas})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}
