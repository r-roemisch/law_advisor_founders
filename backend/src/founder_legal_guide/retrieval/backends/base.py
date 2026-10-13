"""Index backends store passages with their embeddings and search them.
Register new ones with @BACKENDS.register."""

import re
from abc import ABC, abstractmethod
from typing import ClassVar

from ...registry import Registry
from ...settings import Settings
from ..types import Hit, Passage, Query, SearchFilters, SearchMode


class IndexBackend(ABC):
    search_modes: ClassVar[frozenset[str]]

    def __init__(self, index_name: str, settings: Settings, **params):
        self.index_name = index_name
        self.settings = settings

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "_", self.index_name.lower()).strip("_")

    @abstractmethod
    def upsert(self, passages: list[Passage], vectors: list[list[float]]) -> None:
        """Create the index on first use (dimension from the vectors) and write passages."""

    @abstractmethod
    def delete_source(self, source_id: str, language: str) -> None:
        """Remove every passage of one Source in one language, before re-indexing it."""

    @abstractmethod
    def search(
        self, query: Query, vector: list[float], k: int, mode: SearchMode, filters: SearchFilters
    ) -> list[Hit]: ...

    @abstractmethod
    def count(self) -> int: ...


BACKENDS: Registry[IndexBackend] = Registry("index backend")
