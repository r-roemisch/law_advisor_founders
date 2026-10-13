"""Numbering of retrieved passages within one turn, and the check that every citation in
an answer points at a passage that was actually retrieved (a domain security measure)."""

import re
from dataclasses import dataclass, field

from ..retrieval.types import Hit, Passage

_CITATION = re.compile(r"\[(\d{1,3})\]")


@dataclass
class RetrievedSet:
    """All passages retrieved during one turn, numbered [1], [2], ... across every search."""

    passages: list[Passage] = field(default_factory=list)
    _numbers: dict[str, int] = field(default_factory=dict)

    def add(self, hits: list[Hit]) -> list[tuple[int, Hit]]:
        numbered = []
        for hit in hits:
            number = self._numbers.get(hit.passage.id)
            if number is None:
                self.passages.append(hit.passage)
                number = len(self.passages)
                self._numbers[hit.passage.id] = number
            numbered.append((number, hit))
        return numbered

    def get(self, number: int) -> Passage | None:
        return self.passages[number - 1] if 1 <= number <= len(self.passages) else None


@dataclass(frozen=True)
class CitationReport:
    cited: list[int]
    invalid: list[int]

    @property
    def ok(self) -> bool:
        return not self.invalid


def check_citations(answer: str, retrieved: RetrievedSet) -> CitationReport:
    cited = sorted({int(n) for n in _CITATION.findall(answer)})
    invalid = [n for n in cited if retrieved.get(n) is None]
    return CitationReport(cited=[n for n in cited if n not in invalid], invalid=invalid)
