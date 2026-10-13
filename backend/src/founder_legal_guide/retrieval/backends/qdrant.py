"""Qdrant backend: dense vectors plus BM25 sparse vectors, fused natively with RRF.

Each passage gets BM25 terms stemmed in its own language; queries are expanded with both
the English and the German stemmer, so either side of the bilingual Corpus can match.
"""

import uuid
from functools import lru_cache

from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient, models

from ..types import Hit, Passage, Query, SearchFilters, SearchMode
from .base import BACKENDS, IndexBackend

_DENSE = "dense"
_SPARSE = "bm25"
_STEMMER_LANGUAGE = {"en": "english", "de": "german"}


@lru_cache(maxsize=2)
def _bm25(language: str) -> SparseTextEmbedding:
    return SparseTextEmbedding("Qdrant/bm25", language=_STEMMER_LANGUAGE[language])


@BACKENDS.register("qdrant")
class QdrantBackend(IndexBackend):
    search_modes = frozenset({"vector", "hybrid"})

    def __init__(self, index_name, settings, **params):
        super().__init__(index_name, settings)
        self._collection = f"passages_{self.slug}"
        self._client = QdrantClient(url=settings.qdrant_url)

    def _exists(self) -> bool:
        return self._client.collection_exists(self._collection)

    def _ensure(self, dim: int) -> None:
        if self._exists():
            return
        self._client.create_collection(
            self._collection,
            vectors_config={_DENSE: models.VectorParams(size=dim, distance=models.Distance.COSINE)},
            sparse_vectors_config={
                _SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )
        for key, schema in [
            ("source_id", models.PayloadSchemaType.KEYWORD),
            ("language", models.PayloadSchemaType.KEYWORD),
            ("jurisdiction", models.PayloadSchemaType.KEYWORD),
            ("legal_areas", models.PayloadSchemaType.KEYWORD),
            ("tier", models.PayloadSchemaType.INTEGER),
        ]:
            self._client.create_payload_index(self._collection, key, schema)

    def upsert(self, passages: list[Passage], vectors: list[list[float]]) -> None:
        if not passages:
            return
        self._ensure(len(vectors[0]))
        sparse_by_id = {}
        for language in {p.language for p in passages}:
            group = [p for p in passages if p.language == language]
            encoded = _bm25(language).embed([p.embedding_text for p in group])
            sparse_by_id.update({p.id: e for p, e in zip(group, encoded, strict=True)})
        points = []
        for passage, vector in zip(passages, vectors, strict=True):
            sparse = sparse_by_id[passage.id]
            points.append(
                models.PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, passage.id)),
                    vector={
                        _DENSE: vector,
                        _SPARSE: models.SparseVector(
                            indices=sparse.indices.tolist(), values=sparse.values.tolist()
                        ),
                    },
                    payload={
                        "source_id": passage.source.id,
                        "language": passage.language,
                        "jurisdiction": passage.source.jurisdiction,
                        "legal_areas": list(passage.source.legal_areas),
                        "tier": passage.source.tier,
                        "passage": passage.to_payload(),
                    },
                )
            )
        self._client.upsert(self._collection, points=points)

    def delete_source(self, source_id: str, language: str) -> None:
        if not self._exists():
            return
        self._client.delete(
            self._collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="source_id", match=models.MatchValue(value=source_id)
                        ),
                        models.FieldCondition(
                            key="language", match=models.MatchValue(value=language)
                        ),
                    ]
                )
            ),
        )

    def search(
        self, query: Query, vector: list[float], k: int, mode: SearchMode, filters: SearchFilters
    ) -> list[Hit]:
        if not self._exists():
            return []
        qfilter = _filter(filters)
        if mode == "vector":
            result = self._client.query_points(
                self._collection,
                query=vector,
                using=_DENSE,
                limit=k,
                query_filter=qfilter,
                with_payload=True,
            )
        else:
            prefetch = [models.Prefetch(query=vector, using=_DENSE, limit=k * 3, filter=qfilter)]
            for language in _STEMMER_LANGUAGE:
                sparse = next(iter(_bm25(language).query_embed(query.text)))
                prefetch.append(
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=sparse.indices.tolist(), values=sparse.values.tolist()
                        ),
                        using=_SPARSE,
                        limit=k * 3,
                        filter=qfilter,
                    )
                )
            result = self._client.query_points(
                self._collection,
                prefetch=prefetch,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=k,
                with_payload=True,
            )
        return [
            Hit(Passage.from_payload(p.payload["passage"]), float(p.score)) for p in result.points
        ]

    def count(self) -> int:
        if not self._exists():
            return 0
        return self._client.count(self._collection).count


def _filter(filters: SearchFilters) -> models.Filter | None:
    must = []
    if filters.jurisdictions:
        must.append(
            models.FieldCondition(
                key="jurisdiction", match=models.MatchAny(any=sorted(filters.jurisdictions))
            )
        )
    if filters.legal_areas:
        must.append(
            models.FieldCondition(
                key="legal_areas", match=models.MatchAny(any=sorted(filters.legal_areas))
            )
        )
    if filters.tiers:
        must.append(
            models.FieldCondition(key="tier", match=models.MatchAny(any=sorted(filters.tiers)))
        )
    return models.Filter(must=must) if must else None
