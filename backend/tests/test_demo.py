import json

import pytest
from fastapi.testclient import TestClient

from founder_legal_guide.api import AppState, create_app
from founder_legal_guide.config import _validate_strategies
from founder_legal_guide.demo import (
    DEMO_EXAMPLES,
    DEMO_STRATEGIES,
    SAMPLE_DOCUMENTS,
    HashingEmbeddings,
)
from founder_legal_guide.disclaimer import DISCLAIMER
from founder_legal_guide.ingestion.eurlex_parser import parse_eurlex_xhtml
from founder_legal_guide.ingestion.gii_parser import parse_gii_xml
from founder_legal_guide.ingestion.us_parsers import parse_uslm
from founder_legal_guide.settings import Settings

from .ingestion_fakes import fixture


@pytest.fixture
def client(tmp_path):
    state = AppState(
        Settings(demo_mode=True, openrouter_api_key="", admin_token="", config_dir=tmp_path)
    )
    with TestClient(create_app(state)) as c:
        yield c


def chat(client, **body) -> list[dict]:
    response = client.post("/api/chat", json=body)
    assert response.status_code == 200
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


def test_demo_strategies_pass_the_same_validation_as_config_files(tmp_path):
    _validate_strategies(DEMO_STRATEGIES, tmp_path / "demo")


def test_hashing_embeddings_put_similar_wording_closer():
    e = HashingEmbeddings()
    q, near, far = e.embed_documents(
        ["personal data breach", "notify a personal data breach", "job applications"]
    )
    dot = lambda a, b: sum(x * y for x, y in zip(a, b, strict=True))
    assert dot(q, near) > dot(q, far)


def test_options_announce_demo_mode_and_offer_only_the_demo_model(client):
    body = client.get("/api/options").json()
    assert body["demo_notice"].startswith("Demo mode")
    assert [m["id"] for m in body["answer_models"]] == ["demo/extractive"]


@pytest.mark.parametrize("mode", ["single_pass", "agentic"])
def test_demo_answers_cite_retrieved_passages_without_an_api_key(client, mode):
    events = chat(
        client, question="How fast must we notify a personal data breach?", answering_mode=mode
    )
    answer = next(e for e in events if e["type"] == "answer")
    assert answer["citations"]["ok"] and answer["citations"]["cited"]
    assert "Art. 33(1)" in answer["text"]
    assert DISCLAIMER in answer["text"]
    assert any(e["type"] == "token" for e in events)


@pytest.mark.parametrize(
    ("question", "expected"),
    list(
        zip(
            DEMO_EXAMPLES,
            ["Art. 33", "Art. 28", "Art. 6(2)", "Art. 50", "§ 5", "§ 230"],
            strict=True,
        )
    ),
)
def test_every_demo_example_retrieves_its_provision_first(client, question, expected):
    events = chat(client, question=question)
    retrieval = next(e for e in events if e["type"] == "retrieval")
    assert expected in retrieval["hits"][0]["label"]


def test_demo_detects_german_questions(client):
    events = chat(client, question="Welche Angaben gehören ins Impressum unserer Website?")
    retrieval = next(e for e in events if e["type"] == "retrieval")
    assert retrieval["queries"][0]["language"] == "de"


def test_options_offer_examples_matching_the_mode(client):
    assert client.get("/api/options").json()["examples"] == DEMO_EXAMPLES


def _official_text(source_id: str) -> str:
    if source_id == "eu-gdpr":
        sections = parse_eurlex_xhtml(fixture("eurlex/gdpr_eng.xhtml.gz"), "GDPR", "en")
    elif source_id == "eu-ai-act":
        sections = parse_eurlex_xhtml(fixture("eurlex/aiact_eng.xhtml.gz"), "AI Act", "en")
    elif source_id == "de-ddg":
        sections = parse_gii_xml(fixture("gii/ddg.xml.gz")).sections
    elif source_id == "us-section-230":
        sections = parse_uslm(fixture("us/usc47_s230.xml.gz"), 47, ["230"])
    else:
        return ""
    return " ".join(s.text for s in sections).replace("\n", " ")


@pytest.mark.parametrize(
    "section",
    [s for doc in SAMPLE_DOCUMENTS for s in doc.sections],
    ids=lambda s: " ".join(s.heading_path),
)
def test_demo_excerpts_are_verbatim_from_the_official_text(section):
    source_id = next(d.source.id for d in SAMPLE_DOCUMENTS if section in d.sections)
    official = _official_text(source_id)
    for segment in section.text.replace("\n", " ").split("…"):
        segment = segment.strip(" ,;")
        if segment:
            assert segment in official, f"not verbatim: {segment[:80]!r}"


@pytest.mark.parametrize("mode", ["single_pass", "agentic"])
def test_demo_calls_the_ai_act_classifier_for_ai_questions(client, mode):
    events = chat(
        client,
        question="Is an AI system that filters job applications high-risk?",
        answering_mode=mode,
    )
    tool = next(e for e in events if e["type"] == "tool")
    assert tool["name"] == "classify_ai_system"
    assert tool["result"]["risk_class"] == "high_risk"
    guard = next(e for e in events if e["type"] == "guard")
    assert guard["method"] == "keywords" and [t["id"] for t in guard["triggers"]] == [5]
    answer = next(e for e in events if e["type"] == "answer")
    assert "AI Act rule check: high risk" in answer["text"]


def test_demo_feed_shows_the_sample_corpus_as_added(client):
    changes = client.get("/api/changes").json()["changes"]
    assert {c["source_id"] for c in changes} == {d.source.id for d in SAMPLE_DOCUMENTS}
    assert {(c["kind"], c["status"]) for c in changes} == {("added", "applied")}


def test_admin_features_need_a_configured_token(client):
    assert client.get("/api/admin/check").status_code == 503


def test_admin_token_is_checked_and_updates_are_refused_in_demo(tmp_path):
    state = AppState(Settings(demo_mode=True, admin_token="s3cret", config_dir=tmp_path))
    with TestClient(create_app(state)) as c:
        assert c.get("/api/admin/check").status_code == 401
        assert (
            c.get("/api/admin/check", headers={"Authorization": "Bearer wrong"}).status_code == 401
        )
        ok = {"Authorization": "Bearer s3cret"}
        assert c.get("/api/admin/check", headers=ok).json() == {"ok": True}
        assert c.post("/api/admin/update", headers=ok).status_code == 409
        assert c.post("/api/admin/changes/1/approve", headers=ok).status_code == 409
