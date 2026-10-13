import json

import pytest
from fastapi.testclient import TestClient

from founder_legal_guide.api import AppState, create_app
from founder_legal_guide.disclaimer import DISCLAIMER, DISCLAIMER_HEADER
from founder_legal_guide.ingestion.state import MemoryVersionStore
from founder_legal_guide.observability import MemoryRequestLog

from .conftest import scripted, write_config


@pytest.fixture
def client(settings, fake_models, gdpr_doc):
    write_config(
        settings.config_dir,
        """
default: S1
defaults: {chunker: structure, embedding: fake, backend: memory, search: hybrid}
strategies:
  S1: {description: test}
  S-off: {enabled: false}
""",
    )
    fake_models.answer_factories["test/answer"] = lambda: scripted(
        f"Within 72 hours [1].\n\n_{DISCLAIMER}_"
    )
    state = AppState(settings, fake_models)
    # Never write test traffic into the real database.
    state.request_log = MemoryRequestLog()
    state.corpus_state = state.tool_context.version_store = MemoryVersionStore()
    state.strategy("S1").index_document(gdpr_doc)
    with TestClient(create_app(state)) as c:
        yield c


def parse_sse(text: str) -> list[dict]:
    return [
        json.loads(line[len("data: ") :]) for line in text.splitlines() if line.startswith("data: ")
    ]


def test_every_response_carries_the_disclaimer(client):
    response = client.get("/api/health")
    assert response.headers[DISCLAIMER_HEADER] == DISCLAIMER
    assert response.json()["disclaimer"] == DISCLAIMER


def test_options_list_enabled_strategies_models_and_modes(client):
    body = client.get("/api/options").json()
    assert [s["name"] for s in body["strategies"]] == ["S1"]
    assert body["answer_models"][0]["id"] == "test/answer"
    assert {m["name"] for m in body["answering_modes"]} >= {"single_pass", "agentic"}
    assert body["demo_notice"] is None
    assert len(body["examples"]) == 6


def test_chat_streams_events_ending_with_answer_and_done(client):
    response = client.post("/api/chat", json={"question": "When do I report a breach?\x07"})
    events = parse_sse(response.text)
    assert events[-1] == {"type": "done", "disclaimer": DISCLAIMER}
    answer = events[-2]
    assert answer["type"] == "answer"
    assert answer["citations"]["ok"]
    assert answer["strategy"] == "S1"


@pytest.mark.parametrize(
    "body",
    [
        {"question": "   "},
        {"question": "x" * 2001},
        {"question": "ok", "strategy": "S-off"},
        {"question": "ok", "answer_model": "someone/expensive-model"},
        {"question": "ok", "answering_mode": "telepathy"},
        {"question": "ok", "jurisdictions": ["FR"]},
    ],
)
def test_chat_rejects_invalid_input(client, body):
    assert client.post("/api/chat", json=body).status_code == 422


def test_chat_without_api_key_fails_clearly(client):
    client.app.state.flg.settings.openrouter_api_key = ""
    response = client.post("/api/chat", json={"question": "ok"})
    assert response.status_code == 503
    assert "OPENROUTER_API_KEY" in response.json()["detail"]


def test_answers_are_logged_with_cost_and_gap_signals(client):
    client.post("/api/chat", json={"question": "When do I report a breach?"})
    [record] = client.app.state.flg.request_log.recent()
    assert record.question == "When do I report a breach?" and record.strategy == "S1"
    assert record.citations == 1 and record.gap_signal is None


def test_chat_is_rate_limited_per_client(client):
    from founder_legal_guide.ratelimit import RateLimiter

    client.app.state.flg.rate_limiter = RateLimiter(1, 600)
    headers = {"x-forwarded-for": "203.0.113.7"}
    assert client.post("/api/chat", json={"question": "One?"}, headers=headers).status_code == 200
    limited = client.post("/api/chat", json={"question": "Two?"}, headers=headers)
    assert limited.status_code == 429 and "Retry-After" in limited.headers
    other = client.post(
        "/api/chat", json={"question": "Mine?"}, headers={"x-forwarded-for": "198.51.100.1"}
    )
    assert other.status_code == 200
