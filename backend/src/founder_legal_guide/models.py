"""Factories for OpenRouter chat and embedding models (ADR 0007: models are chosen by role)."""

import logging
from functools import lru_cache

import httpx
import openai
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_openai import OpenAIEmbeddings
from langchain_openrouter import ChatOpenRouter

from .settings import Settings

log = logging.getLogger(__name__)


class ModelFactory:
    """Builds models through OpenRouter. Tests substitute a factory returning fakes."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def chat(self, model_id: str, *, temperature: float = 0.2) -> BaseChatModel:
        # Strict provider routing means an unsupported parameter excludes every endpoint, and
        # several reasoning models (e.g. Claude 5.5, GPT-6) do not accept a temperature.
        supported = _supported_parameters(self._settings.openrouter_base_url).get(model_id)
        if supported is not None and "temperature" not in supported:
            temperature = None
        return _chat(
            model_id,
            temperature,
            self._settings.openrouter_api_key,
            self._settings.openrouter_base_url,
            self._settings.app_title,
            self._settings.app_url,
        )

    def embeddings(self, model_id: str) -> Embeddings:
        return _embeddings(
            model_id, self._settings.openrouter_api_key, self._settings.openrouter_base_url
        )


@lru_cache(maxsize=1)
def _supported_parameters(base_url: str) -> dict[str, set[str]]:
    """Model id → supported request parameters, from OpenRouter's public model list."""
    try:
        response = httpx.get(f"{base_url}/models", timeout=15)
        response.raise_for_status()
        return {m["id"]: set(m.get("supported_parameters") or []) for m in response.json()["data"]}
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        log.warning("could not load OpenRouter model capabilities: %s", exc)
        return {}


@lru_cache(maxsize=32)
def _chat(
    model_id: str,
    temperature: float | None,
    api_key: str,
    base_url: str,
    app_title: str,
    app_url: str,
) -> BaseChatModel:
    return ChatOpenRouter(
        model=model_id,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        app_title=app_title,
        app_url=app_url,
        # Route only to providers that support every parameter we send (tools in particular).
        openrouter_provider={"require_parameters": True},
        max_retries=2,
    )


class TokenBudgetEmbeddings(Embeddings):
    """Batches by an estimated token budget instead of a fixed count: some providers (e.g.
    Mistral) refuse requests whose total tokens exceed a limit. A refused batch is halved."""

    def __init__(self, inner: Embeddings, max_tokens: int = 8000, max_items: int = 64):
        self.inner = inner
        self.max_tokens = max_tokens
        self.max_items = max_items

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        batch, budget = [], 0
        for text in texts:
            cost = len(text) // 3 + 1  # conservative: ~3 characters per token for legal text
            if batch and (budget + cost > self.max_tokens or len(batch) >= self.max_items):
                vectors += self._embed(batch)
                batch, budget = [], 0
            batch.append(text)
            budget += cost
        if batch:
            vectors += self._embed(batch)
        return vectors

    def _embed(self, batch: list[str]) -> list[list[float]]:
        try:
            return self.inner.embed_documents(batch)
        except openai.BadRequestError as exc:
            if len(batch) == 1 or "token" not in str(exc).lower():
                raise
            middle = len(batch) // 2
            return self._embed(batch[:middle]) + self._embed(batch[middle:])

    def embed_query(self, text: str) -> list[float]:
        return self.inner.embed_query(text)


@lru_cache(maxsize=16)
def _embeddings(model_id: str, api_key: str, base_url: str) -> Embeddings:
    # Mistral refuses requests above ~16k tokens in total; OpenAI accepts far larger batches.
    if model_id.startswith("mistralai/"):
        return TokenBudgetEmbeddings(_openai_embeddings(model_id, api_key, base_url), 12_000, 64)
    return TokenBudgetEmbeddings(_openai_embeddings(model_id, api_key, base_url), 150_000, 128)


def _openai_embeddings(model_id: str, api_key: str, base_url: str) -> Embeddings:
    return OpenAIEmbeddings(
        model=model_id,
        api_key=api_key,
        base_url=base_url,
        # OpenRouter models are not all tiktoken-compatible; let the provider handle length.
        check_embedding_ctx_length=False,
        # TokenBudgetEmbeddings does the batching; this only caps a single request.
        chunk_size=1000,
    )
