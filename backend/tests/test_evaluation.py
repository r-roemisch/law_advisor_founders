from founder_legal_guide.evaluation.golden import (
    ExpectedPassage,
    GoldenItem,
    GoldenSet,
    load_golden_set,
    save_golden_set,
)
from founder_legal_guide.evaluation.run import evaluate_retrieval, matches, score_retrieval
from founder_legal_guide.retrieval.strategy import RetrievalStrategy

from .test_retrieval import spec


def item(*expected: ExpectedPassage, **kw) -> GoldenItem:
    return GoldenItem(
        id="x",
        question=kw.get("question", "When must a breach be notified?"),
        language="en",
        legal_area="data_protection",
        jurisdiction="EU",
        expected=list(expected),
        reference_answer="Within 72 hours.",
    )


ART33 = ExpectedPassage(source_id="eu-gdpr", label="Art. 33", anchor="art-33")


def test_matching_prefers_anchors_and_falls_back_to_labels():
    assert matches("eu-gdpr", "GDPR › Art. 33", "art-33", ART33)
    assert not matches("eu-gdpr", "GDPR › Art. 33", "art-34", ART33)
    assert not matches("de-bdsg", "BDSG › Art. 33", "art-33", ART33)
    page = ExpectedPassage(source_id="de-gp-gmbh", label="Notar")
    assert matches("de-gp-gmbh", "Gründerplattform › Notar", None, page)


def test_scores_recall_hit_and_reciprocal_rank():
    art28 = ExpectedPassage(source_id="eu-gdpr", label="Art. 28", anchor="art-28")
    hits = [("de-bdsg", "BDSG › § 26", "p26"), ("eu-gdpr", "GDPR › Art. 33", "art-33")]
    score = score_retrieval(item(ART33, art28), hits)
    assert (score.hit, score.recall, score.reciprocal_rank) == (True, 0.5, 0.5)
    miss = score_retrieval(item(art28), hits)
    assert (miss.hit, miss.recall, miss.reciprocal_rank) == (False, 0.0, 0.0)


def test_retrieval_evaluation_over_a_strategy(ctx, gdpr_doc):
    strategy = RetrievalStrategy(spec(), ctx)
    strategy.index_document(gdpr_doc)
    result = evaluate_retrieval(strategy, [item(ART33, question="breach notify 72 hours")], k=3)
    assert result["questions"] == 1 and result["hit_rate"] == 1.0


def test_golden_set_round_trip_and_review_filter(tmp_path):
    reviewed = item(ART33).model_copy(update={"id": "a", "status": "reviewed"})
    draft = item(ART33).model_copy(update={"id": "b"})
    path = tmp_path / "golden.yaml"
    save_golden_set(GoldenSet(items=[reviewed, draft]), path, "# header\n")
    loaded = load_golden_set(path)
    assert [i.id for i in loaded.usable(reviewed_only=True)] == ["a"]
    assert [i.id for i in loaded.usable(reviewed_only=False)] == ["a", "b"]
    assert path.read_text().startswith("# header")
