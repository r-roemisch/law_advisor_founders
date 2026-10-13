"""Source adapters turn a Source Registry entry into SourceDocuments, one per language.
Register new ones with @ADAPTERS.register; the name is the `adapter` value in sources.yaml."""

from abc import ABC, abstractmethod

from ...registry import Registry
from ...retrieval.types import SourceDocument
from ..http import Fetcher
from ..registry import SourceEntry


class SourceAdapter(ABC):
    def __init__(self, fetcher: Fetcher):
        self.fetcher = fetcher

    @abstractmethod
    def fetch(self, entry: SourceEntry) -> list[SourceDocument]: ...


ADAPTERS: Registry[SourceAdapter] = Registry("source adapter")
