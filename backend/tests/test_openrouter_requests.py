"""Checks the HTTP requests we would send to OpenRouter, using a local stand-in server.
No API key or network needed."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest
from langchain_core.tools import tool

from founder_legal_guide.models import ModelFactory
from founder_legal_guide.settings import Settings


class _Recorder(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict]] = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append(
            {
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": body,
            }
        )
        if self.path.endswith("/embeddings"):
            inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
            reply = {
                "object": "list",
                "model": body["model"],
                "data": [
                    {"object": "embedding", "index": i, "embedding": [0.1, 0.2, 0.3]}
                    for i in range(len(inputs))
                ],
                "usage": {"prompt_tokens": 3, "total_tokens": 3},
            }
        else:
            reply = {
                "id": "gen-1",
                "object": "chat.completion",
                "created": 0,
                "system_fingerprint": None,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "ok"},
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
            }
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def openrouter():
    _Recorder.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/api/v1", _Recorder.requests
    server.shutdown()


def factory(base_url: str) -> ModelFactory:
    return ModelFactory(Settings(openrouter_api_key="sk-or-test", openrouter_base_url=base_url))


@tool
def search_corpus(query: str) -> str:
    """Search the legal Corpus."""
    return ""


def test_chat_request_uses_model_key_tools_and_strict_provider_routing(openrouter):
    base_url, requests = openrouter
    llm = factory(base_url).chat("anthropic/claude-sonnet-5.5").bind_tools([search_corpus])
    reply = llm.invoke("When must a breach be reported?")

    assert reply.content == "ok"
    request = requests[-1]
    assert request["path"] == "/api/v1/chat/completions"
    assert request["headers"]["authorization"] == "Bearer sk-or-test"
    body = request["body"]
    assert body["model"] == "anthropic/claude-sonnet-5.5"
    assert body["provider"]["require_parameters"] is True
    assert [t["function"]["name"] for t in body["tools"]] == ["search_corpus"]
    assert body["messages"][-1] == {"role": "user", "content": "When must a breach be reported?"}


def test_chat_request_identifies_the_app(openrouter):
    base_url, requests = openrouter
    factory(base_url).chat("openai/gpt-6-sol").invoke("hi")
    headers = requests[-1]["headers"]
    assert headers.get("x-title") == "Founder Legal Guide"
    assert headers.get("http-referer") == "http://localhost:3000"


def test_utility_model_runs_deterministically(openrouter):
    base_url, requests = openrouter
    factory(base_url).chat("anthropic/claude-haiku-5.5", temperature=0.0).invoke("hi")
    assert requests[-1]["body"]["temperature"] == 0.0


def test_embedding_request_goes_to_openrouter_with_the_model_id(openrouter):
    base_url, requests = openrouter
    vectors = (
        factory(base_url).embeddings("baai/bge-m3").embed_documents(["Art. 33 GDPR", "§ 26 BDSG"])
    )

    assert vectors == [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]
    request = requests[-1]
    assert request["path"] == "/api/v1/embeddings"
    assert request["headers"]["authorization"] == "Bearer sk-or-test"
    assert request["body"]["model"] == "baai/bge-m3"
    # Raw text, not tiktoken token ids: OpenRouter models are not all OpenAI tokenizers.
    assert request["body"]["input"] == ["Art. 33 GDPR", "§ 26 BDSG"]


def test_embedding_batches_respect_a_token_budget_and_split_on_refusal():
    import httpx
    import openai

    from founder_legal_guide.models import TokenBudgetEmbeddings

    class Inner:
        def __init__(self):
            self.calls: list[int] = []

        def embed_documents(self, texts):
            self.calls.append(len(texts))
            if len(texts) > 2:
                request = httpx.Request("POST", "https://x")
                raise openai.BadRequestError(
                    "Too many tokens overall",
                    response=httpx.Response(400, request=request),
                    body=None,
                )
            return [[1.0] for _ in texts]

        def embed_query(self, text):
            return [1.0]

    inner = Inner()
    embeddings = TokenBudgetEmbeddings(inner, max_tokens=100)
    texts = ["x" * 90] * 10  # ~31 tokens each: 3 fit the budget, but the provider refuses 3
    assert len(embeddings.embed_documents(texts)) == 10
    assert max(inner.calls) <= 3 and all(c <= 2 for c in inner.calls if c != 3)
