"""Value types shared by every Retrieval Strategy building block."""

from dataclasses import dataclass, field
from typing import Literal

Language = Literal["en", "de"]
SearchMode = Literal["vector", "hybrid"]


@dataclass(frozen=True)
class SourceInfo:
    """The Source Registry facts about one Source that travel with each of its passages."""

    id: str
    title: str
    jurisdiction: str
    tier: int
    legal_areas: tuple[str, ...]
    legal_status: str
    url: str | None = None


@dataclass(frozen=True)
class Section:
    """One structural unit of a Source as parsed by an adapter, e.g. an article or a §."""

    heading_path: tuple[str, ...]
    text: str
    kind: Literal["provision", "recital", "text"] = "provision"
    anchor: str | None = None


@dataclass(frozen=True)
class SourceDocument:
    """One Source in one language, split into Sections, ready for chunking."""

    source: SourceInfo
    language: Language
    sections: tuple[Section, ...]
    version: str


@dataclass(frozen=True)
class Passage:
    """A searchable piece of a Source, produced by a chunker."""

    id: str
    source: SourceInfo
    language: Language
    heading_path: tuple[str, ...]
    text: str
    anchor: str | None = None

    @property
    def citation_label(self) -> str:
        return " › ".join(self.heading_path) or self.source.title

    @property
    def embedding_text(self) -> str:
        """Heading path plus text, so a passage carries the context of where it sits."""
        return f"{self.citation_label}\n\n{self.text}"

    def to_payload(self) -> dict:
        return {
            "id": self.id,
            "source": {
                "id": self.source.id,
                "title": self.source.title,
                "jurisdiction": self.source.jurisdiction,
                "tier": self.source.tier,
                "legal_areas": list(self.source.legal_areas),
                "legal_status": self.source.legal_status,
                "url": self.source.url,
            },
            "language": self.language,
            "heading_path": list(self.heading_path),
            "text": self.text,
            "anchor": self.anchor,
        }

    @classmethod
    def from_payload(cls, payload: dict) -> "Passage":
        src = payload["source"]
        return cls(
            id=payload["id"],
            source=SourceInfo(
                id=src["id"],
                title=src["title"],
                jurisdiction=src["jurisdiction"],
                tier=src["tier"],
                legal_areas=tuple(src["legal_areas"]),
                legal_status=src["legal_status"],
                url=src.get("url"),
            ),
            language=payload["language"],
            heading_path=tuple(payload["heading_path"]),
            text=payload["text"],
            anchor=payload.get("anchor"),
        )


@dataclass(frozen=True)
class Query:
    """A search query; `language` is None when unknown."""

    text: str
    language: Language | None = None


@dataclass(frozen=True)
class SearchFilters:
    jurisdictions: frozenset[str] | None = None
    legal_areas: frozenset[str] | None = None
    tiers: frozenset[int] | None = None

    def matches(self, source: SourceInfo) -> bool:
        if self.jurisdictions and source.jurisdiction not in self.jurisdictions:
            return False
        if self.legal_areas and not self.legal_areas.intersection(source.legal_areas):
            return False
        return not self.tiers or source.tier in self.tiers


@dataclass(frozen=True)
class Hit:
    passage: Passage
    score: float


@dataclass
class RetrievalTrace:
    """What a Retrieval Strategy did for one search, for the "how this answer was found" panel."""

    strategy: str
    queries: list[Query] = field(default_factory=list)
    candidates: int = 0
    reranked: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class RetrievalResult:
    hits: list[Hit]
    trace: RetrievalTrace
