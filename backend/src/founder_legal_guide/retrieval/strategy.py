"""A Retrieval Strategy assembled from its configured building blocks."""

from ..config import StrategySpec
from .backends import BACKENDS, IndexBackend
from .chunkers import CHUNKERS, Chunker
from .context import ComponentContext
from .fusion import reciprocal_rank_fusion
from .query_transforms import QUERY_TRANSFORMS, QueryTransform
from .rerankers import RERANKERS, Reranker
from .types import Hit, Query, RetrievalResult, RetrievalTrace, SearchFilters, SourceDocument


class RetrievalStrategy:
    def __init__(self, spec: StrategySpec, ctx: ComponentContext):
        self.spec = spec
        self.name = spec.name
        self.embeddings = ctx.models.embeddings(spec.embedding)
        self.chunker: Chunker = CHUNKERS.get(spec.chunker.name)(
            ctx, spec.embedding, **spec.chunker.params
        )
        self.backend: IndexBackend = BACKENDS.get(spec.backend)(spec.index_name, ctx.settings)
        self.transforms: list[QueryTransform] = [
            QUERY_TRANSFORMS.get(t.name)(ctx, **t.params) for t in spec.query_transforms
        ]
        self.reranker: Reranker | None = (
            RERANKERS.get(spec.reranker.name)(ctx, **spec.reranker.params)
            if spec.reranker
            else None
        )

    def _weight_by_tier(self, hits: list[Hit]) -> list[Hit]:
        weights = self.spec.tier_weights
        if all(w == 1.0 for w in weights.values()):
            return hits
        weighted = [
            Hit(h.passage, _penalise(h.score, weights.get(h.passage.source.tier, 1.0)))
            for h in hits
        ]
        return sorted(weighted, key=lambda h: h.score, reverse=True)

    def index_document(self, doc: SourceDocument) -> int:
        """Replace one Source-language's passages in this strategy's index. Returns the count."""
        passages = self.chunker.chunk(doc)
        vectors = self.embeddings.embed_documents([p.embedding_text for p in passages])
        self.backend.delete_source(doc.source.id, doc.language)
        self.backend.upsert(passages, vectors)
        return len(passages)

    def retrieve(
        self, question: str, filters: SearchFilters | None = None, k: int | None = None
    ) -> RetrievalResult:
        k = k or self.spec.top_k
        filters = filters or SearchFilters()
        trace = RetrievalTrace(strategy=self.name)

        queries = [Query(question)]
        for transform in self.transforms:
            queries = transform.transform(queries)
        trace.queries = queries

        # Weighting or reranking needs candidates beyond the final k to have anything to promote.
        weighted = any(w != 1.0 for w in self.spec.tier_weights.values())
        pool = self.reranker.candidates if self.reranker else (k * 3 if weighted else k)
        vectors = self.embeddings.embed_documents([q.text for q in queries])
        rankings = [
            self.backend.search(q, v, pool, self.spec.search, filters)
            for q, v in zip(queries, vectors, strict=True)
        ]
        hits = rankings[0] if len(rankings) == 1 else reciprocal_rank_fusion(rankings, limit=pool)
        hits = self._weight_by_tier(hits)
        trace.candidates = len(hits)

        if self.reranker and hits:
            hits = self.reranker.rerank(question, hits, k)
            trace.reranked = True
        return RetrievalResult(hits=hits[:k], trace=trace)


def _penalise(score: float, weight: float) -> float:
    """Lower a score by `weight` (<= 1) whatever its sign: cosine scores can be negative, and
    multiplying a negative score by a small weight would raise it."""
    return score * weight if score >= 0 else score / weight
