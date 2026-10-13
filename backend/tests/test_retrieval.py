from founder_legal_guide.config import ComponentSpec, StrategySpec
from founder_legal_guide.retrieval.chunkers import FixedSizeChunker, StructureChunker
from founder_legal_guide.retrieval.fusion import reciprocal_rank_fusion
from founder_legal_guide.retrieval.strategy import RetrievalStrategy
from founder_legal_guide.retrieval.types import Hit, SearchFilters, Section, SourceDocument

from .conftest import GDPR


def spec(**overrides) -> StrategySpec:
    base = {
        "name": "T",
        "chunker": ComponentSpec(name="structure"),
        "embedding": "fake",
        "backend": "memory",
        "search": "hybrid",
        "top_k": 3,
    }
    return StrategySpec(**{**base, **overrides})


def test_structure_chunker_keeps_one_passage_per_section(ctx, gdpr_doc):
    passages = StructureChunker(ctx, "fake").chunk(gdpr_doc)
    assert [p.citation_label for p in passages] == [
        "GDPR › Art. 6",
        "GDPR › Art. 28",
        "GDPR › Art. 33",
    ]
    assert passages[1].anchor == "art-28"
    assert len({p.id for p in passages}) == 3


def test_structure_chunker_splits_oversized_sections_under_the_same_heading(ctx):
    long_text = "\n\n".join(f"Paragraph {i}. " + "word " * 40 for i in range(10))
    doc = SourceDocument(GDPR, "en", (Section(("GDPR", "Art. 5"), long_text),), "v")
    passages = StructureChunker(ctx, "fake", max_chars=500).chunk(doc)
    assert len(passages) > 1
    assert {p.citation_label for p in passages} == {"GDPR › Art. 5"}


def test_fixed_chunker_attributes_chunks_to_the_section_they_start_in(ctx, gdpr_doc):
    passages = FixedSizeChunker(ctx, "fake", chunk_size=80, chunk_overlap=0).chunk(gdpr_doc)
    assert len(passages) > 3
    assert passages[0].citation_label == "GDPR › Art. 6"
    assert passages[-1].citation_label == "GDPR › Art. 33"


def test_reciprocal_rank_fusion_rewards_agreement(gdpr_doc, ctx):
    a, b, c = StructureChunker(ctx, "fake").chunk(gdpr_doc)
    fused = reciprocal_rank_fusion([[Hit(a, 1), Hit(b, 0.9)], [Hit(b, 5), Hit(c, 4)]], limit=3)
    assert [h.passage.id for h in fused] == [b.id, a.id, c.id]


def test_strategy_indexes_retrieves_and_filters(ctx, gdpr_doc, bdsg_doc):
    strategy = RetrievalStrategy(spec(), ctx)
    assert strategy.index_document(gdpr_doc) == 3
    strategy.index_document(bdsg_doc)

    # Fake embeddings carry no meaning, so only the keyword side is checked here.
    result = strategy.retrieve("data processing agreement processor")
    assert "art-28" in {h.passage.anchor for h in result.hits}

    german_only = strategy.retrieve("Beschäftigte", SearchFilters(jurisdictions=frozenset({"DE"})))
    assert {h.passage.source.id for h in german_only.hits} == {"de-bdsg"}


def test_reindexing_a_source_replaces_its_passages(ctx, gdpr_doc):
    strategy = RetrievalStrategy(spec(), ctx)
    strategy.index_document(gdpr_doc)
    strategy.index_document(gdpr_doc)
    assert strategy.backend.count() == 3


def test_bilingual_expansion_adds_translated_query(ctx, fake_models, gdpr_doc):
    fake_models.utility = lambda system, user: {
        "language": "en",
        "translation": "Auftragsverarbeitungsvertrag",
    }
    strategy = RetrievalStrategy(
        spec(query_transforms=[ComponentSpec(name="bilingual_expansion")]), ctx
    )
    strategy.index_document(gdpr_doc)
    result = strategy.retrieve("data processing agreement")
    assert [(q.text, q.language) for q in result.trace.queries] == [
        ("data processing agreement", "en"),
        ("Auftragsverarbeitungsvertrag", "de"),
    ]


def test_query_transform_failure_falls_back_to_original_question(ctx, fake_models, gdpr_doc):
    fake_models.utility = lambda system, user: "not json"
    strategy = RetrievalStrategy(
        spec(query_transforms=[ComponentSpec(name="bilingual_expansion")]), ctx
    )
    strategy.index_document(gdpr_doc)
    result = strategy.retrieve("breach")
    assert [q.text for q in result.trace.queries] == ["breach"]


def test_llm_reranker_reorders_candidates(ctx, fake_models, gdpr_doc):
    fake_models.utility = lambda system, user: [2, 0]
    strategy = RetrievalStrategy(
        spec(reranker=ComponentSpec(name="llm", params={"candidates": 3})), ctx
    )
    strategy.index_document(gdpr_doc)
    result = strategy.retrieve("anything", k=2)
    assert result.trace.reranked
    assert len(result.hits) == 2


def test_tier_weights_rank_official_sources_above_practical_pages(ctx, gdpr_doc):
    from dataclasses import replace

    from founder_legal_guide.retrieval.types import Section, SourceDocument

    practical = replace(gdpr_doc.source, id="de-ihk-page", tier=3)
    page = SourceDocument(
        practical,
        "en",
        (Section(("IHK", "Breach"), "A personal data breach must be reported within 72 hours."),),
        "v",
    )
    question = "A personal data breach must be reported within 72 hours."
    neutral = RetrievalStrategy(spec(), ctx)
    weighted = RetrievalStrategy(spec(tier_weights={1: 1.0, 2: 1.0, 3: 0.01}), ctx)
    for s in (neutral, weighted):
        s.index_document(gdpr_doc)
        s.index_document(page)

    def page_rank(strategy) -> int:
        return [h.passage.source.tier for h in strategy.retrieve(question, k=4).hits].index(3)

    assert page_rank(weighted) > page_rank(neutral)
    assert page_rank(weighted) == 3  # last of four


def test_penalty_lowers_negative_scores_too():
    from founder_legal_guide.retrieval.strategy import _penalise

    assert _penalise(0.8, 0.5) == 0.4
    assert _penalise(-0.2, 0.5) == -0.4


def test_semantic_chunks_never_exceed_the_size_limit(ctx):
    from founder_legal_guide.retrieval.chunkers import SemanticChunker

    long_text = " ".join(f"Sentence number {i} about data protection duties." for i in range(400))
    doc = SourceDocument(GDPR, "en", (Section(("GDPR", "Art. 5"), long_text),), "v")
    passages = SemanticChunker(ctx, "fake", max_chars=1000).chunk(doc)
    assert passages and max(len(p.text) for p in passages) <= 1000
    assert {p.citation_label for p in passages} == {"GDPR › Art. 5"}
