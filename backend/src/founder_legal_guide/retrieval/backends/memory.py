"""In-process backend for tests and for trying the app without databases. Not persistent."""

import math
import re

from ..fusion import reciprocal_rank_fusion
from ..types import Hit, Passage, Query, SearchFilters, SearchMode
from .base import BACKENDS, IndexBackend

_WORD = re.compile(r"\w+", re.UNICODE)
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "our",
        "that",
        "the",
        "their",
        "this",
        "to",
        "under",
        "we",
        "what",
        "when",
        "which",
        "who",
        "will",
        "with",
        "you",
        "your",
        "der",
        "die",
        "das",
        "den",
        "dem",
        "des",
        "ein",
        "eine",
        "einer",
        "und",
        "oder",
        "ist",
        "sind",
        "wir",
        "unser",
        "unsere",
        "unserer",
        "für",
        "mit",
        "von",
        "zu",
        "im",
        "in",
        "ins",
        "auf",
        "an",
        "bei",
        "wie",
        "was",
        "welche",
        "welcher",
        "wann",
    ]
)


def _terms(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS}


@BACKENDS.register("memory")
class MemoryBackend(IndexBackend):
    search_modes = frozenset({"vector", "hybrid"})

    def __init__(self, index_name, settings, **params):
        super().__init__(index_name, settings)
        self._rows: dict[str, tuple[Passage, list[float]]] = {}

    def upsert(self, passages: list[Passage], vectors: list[list[float]]) -> None:
        for passage, vector in zip(passages, vectors, strict=True):
            self._rows[passage.id] = (passage, vector)

    def delete_source(self, source_id: str, language: str) -> None:
        self._rows = {
            pid: row
            for pid, row in self._rows.items()
            if not (row[0].source.id == source_id and row[0].language == language)
        }

    def search(
        self, query: Query, vector: list[float], k: int, mode: SearchMode, filters: SearchFilters
    ) -> list[Hit]:
        rows = [(p, v) for p, v in self._rows.values() if filters.matches(p.source)]
        dense = sorted((Hit(p, _cosine(vector, v)) for p, v in rows), key=lambda h: -h.score)
        if mode == "vector":
            return dense[:k]
        terms = _terms(query.text)
        keyword = sorted(
            (Hit(p, float(len(terms & _terms(p.embedding_text)))) for p, _ in rows),
            key=lambda h: -h.score,
        )
        keyword = [h for h in keyword if h.score > 0]
        return reciprocal_rank_fusion([dense[: k * 3], keyword[: k * 3]], limit=k)

    def count(self) -> int:
        return len(self._rows)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0
