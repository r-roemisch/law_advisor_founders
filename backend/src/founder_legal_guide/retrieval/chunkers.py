"""Chunkers cut a SourceDocument into Passages. Register new ones with @CHUNKERS.register."""

import hashlib
from abc import ABC, abstractmethod
from bisect import bisect_right

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..registry import Registry
from .context import ComponentContext
from .types import Passage, Section, SourceDocument


class Chunker(ABC):
    def __init__(self, ctx: ComponentContext, embedding_model: str, **params):
        self.ctx = ctx
        self.embedding_model = embedding_model

    @abstractmethod
    def chunk(self, doc: SourceDocument) -> list[Passage]: ...


CHUNKERS: Registry[Chunker] = Registry("chunker")


def passage_id(doc: SourceDocument, index: int, text: str) -> str:
    digest = hashlib.sha1(text.encode()).hexdigest()[:10]
    return f"{doc.source.id}:{doc.language}:{index:05d}:{digest}"


@CHUNKERS.register("structure")
class StructureChunker(Chunker):
    """One passage per Section (article, §, recital). Oversized Sections are split on
    paragraph boundaries, each part keeping the Section's heading path."""

    def __init__(self, ctx, embedding_model, max_chars: int = 6000, **params):
        super().__init__(ctx, embedding_model)
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=max_chars, chunk_overlap=0, separators=["\n\n", "\n", ". ", " "]
        )

    def chunk(self, doc: SourceDocument) -> list[Passage]:
        passages: list[Passage] = []
        for section in doc.sections:
            for part in self._splitter.split_text(section.text):
                passages.append(
                    Passage(
                        id=passage_id(doc, len(passages), part),
                        source=doc.source,
                        language=doc.language,
                        heading_path=section.heading_path,
                        text=part,
                        anchor=section.anchor,
                    )
                )
        return passages


class _FlatTextChunker(Chunker):
    """Base for chunkers that ignore structure: they split the concatenated text and
    attribute each chunk to the Section it starts in."""

    def chunk(self, doc: SourceDocument) -> list[Passage]:
        text, starts = _flatten(doc.sections)
        passages: list[Passage] = []
        for chunk_text, start in self._split(text):
            section = doc.sections[max(bisect_right(starts, start) - 1, 0)]
            passages.append(
                Passage(
                    id=passage_id(doc, len(passages), chunk_text),
                    source=doc.source,
                    language=doc.language,
                    heading_path=section.heading_path,
                    text=chunk_text,
                    anchor=section.anchor,
                )
            )
        return passages

    @abstractmethod
    def _split(self, text: str) -> list[tuple[str, int]]:
        """Return (chunk text, start offset) pairs."""


def _flatten(sections: tuple[Section, ...]) -> tuple[str, list[int]]:
    parts, starts, offset = [], [], 0
    for section in sections:
        block = f"{' › '.join(section.heading_path)}\n{section.text}\n\n"
        starts.append(offset)
        parts.append(block)
        offset += len(block)
    return "".join(parts), starts


@CHUNKERS.register("fixed")
class FixedSizeChunker(_FlatTextChunker):
    """Fixed-size character windows with overlap: the classic RAG baseline."""

    def __init__(
        self, ctx, embedding_model, chunk_size: int = 1200, chunk_overlap: int = 200, **params
    ):
        super().__init__(ctx, embedding_model)
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap, add_start_index=True
        )

    def _split(self, text: str) -> list[tuple[str, int]]:
        return [
            (d.page_content, d.metadata["start_index"])
            for d in self._splitter.create_documents([text])
        ]


@CHUNKERS.register("semantic")
class SemanticChunker(_FlatTextChunker):
    """Splits where the embedding similarity between neighbouring sentences drops."""

    def __init__(
        self,
        ctx,
        embedding_model,
        breakpoint_threshold_type: str = "percentile",
        max_chars: int = 6000,
        **params,
    ):
        super().__init__(ctx, embedding_model)
        from langchain_experimental.text_splitter import SemanticChunker as _LCSemanticChunker

        self._splitter = _LCSemanticChunker(
            ctx.models.embeddings(embedding_model),
            breakpoint_threshold_type=breakpoint_threshold_type,
            add_start_index=True,
        )
        # Semantic chunks can grow past the embedding model's input limit; cut those further.
        self._oversize = RecursiveCharacterTextSplitter(
            chunk_size=max_chars, chunk_overlap=0, add_start_index=True
        )
        self.max_chars = max_chars

    def _split(self, text: str) -> list[tuple[str, int]]:
        chunks = []
        for d in self._splitter.create_documents([text]):
            start = d.metadata["start_index"]
            if len(d.page_content) <= self.max_chars:
                chunks.append((d.page_content, start))
            else:
                chunks += [
                    (p.page_content, start + p.metadata["start_index"])
                    for p in self._oversize.create_documents([d.page_content])
                ]
        return chunks
