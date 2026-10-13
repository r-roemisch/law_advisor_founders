"""Shared fakes: no network, no databases."""

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from pydantic import Field

from founder_legal_guide.retrieval.context import ComponentContext
from founder_legal_guide.retrieval.types import Section, SourceDocument, SourceInfo
from founder_legal_guide.settings import REPO_ROOT, Settings


class ScriptedChatModel(GenericFakeChatModel):
    """Replies with scripted messages in order; accepts bind_tools like a real model."""

    seen: list[list[BaseMessage]] = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        # Emit each scripted message as a single chunk, tool calls included.
        message = self._generate(messages, stop=stop, **kwargs).generations[0].message
        chunk = ChatGenerationChunk(
            message=AIMessageChunk(
                content=message.content,
                tool_call_chunks=[
                    {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
                    for i, c in enumerate(message.tool_calls)
                ],
            )
        )
        if run_manager:
            run_manager.on_llm_new_token(str(message.content), chunk=chunk)
        yield chunk


def scripted(*replies: AIMessage | str) -> ScriptedChatModel:
    messages = [r if isinstance(r, AIMessage) else AIMessage(r) for r in replies]
    return ScriptedChatModel(messages=iter(messages), seen=[])


class FakeModels:
    """Stands in for ModelFactory. `utility` answers utility prompts; `answers` maps model ids
    to factories of scripted answer models."""

    def __init__(self, utility: Callable[[str, str], object] | None = None):
        self.utility = utility or (lambda system, user: {"language": "en", "translation": ""})
        self.answer_factories: dict[str, Callable[[], ScriptedChatModel]] = {}

    def chat(self, model_id: str, *, temperature: float = 0.2):
        if model_id in self.answer_factories:
            return self.answer_factories[model_id]()
        fake = self

        class _Utility(GenericFakeChatModel):
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                reply = fake.utility(str(messages[0].content), str(messages[-1].content))
                self.messages = iter([AIMessage(json.dumps(reply))])
                return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

        return _Utility(messages=iter([]))

    def embeddings(self, model_id: str):
        return DeterministicFakeEmbedding(size=16)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(config_dir=tmp_path, openrouter_api_key="test")


@pytest.fixture
def fake_models() -> FakeModels:
    return FakeModels()


@pytest.fixture
def ctx(settings, fake_models) -> ComponentContext:
    return ComponentContext(settings, fake_models, "utility/model")


GDPR = SourceInfo(
    id="eu-gdpr",
    title="GDPR",
    jurisdiction="EU",
    tier=1,
    legal_areas=("data_protection",),
    legal_status="in_force",
    url="https://eur-lex.europa.eu/eli/reg/2016/679/oj",
)
BDSG = SourceInfo(
    id="de-bdsg",
    title="BDSG",
    jurisdiction="DE",
    tier=1,
    legal_areas=("data_protection", "employment"),
    legal_status="in_force",
)


@pytest.fixture
def gdpr_doc() -> SourceDocument:
    return SourceDocument(
        source=GDPR,
        language="en",
        version="test",
        sections=(
            Section(
                ("GDPR", "Art. 6"),
                "Processing shall be lawful only if the data subject has given consent.",
                anchor="art-6",
            ),
            Section(
                ("GDPR", "Art. 28"),
                "The processor shall process personal data only on documented instructions from the controller (data processing agreement).",
                anchor="art-28",
            ),
            Section(
                ("GDPR", "Art. 33"),
                "The controller shall notify a personal data breach within 72 hours.",
                anchor="art-33",
            ),
        ),
    )


@pytest.fixture
def bdsg_doc() -> SourceDocument:
    return SourceDocument(
        source=BDSG,
        language="de",
        version="test",
        sections=(
            Section(
                ("BDSG", "§ 26"),
                "Personenbezogene Daten von Beschäftigten dürfen verarbeitet werden, wenn dies erforderlich ist.",
                anchor="p26",
            ),
        ),
    )


def write_config(directory: Path, strategies: str, models: str | None = None) -> None:
    for name in ("sources.yaml", "thresholds.yaml"):
        shutil.copy(REPO_ROOT / "config" / name, directory / name)
    (directory / "strategies.yaml").write_text(strategies)
    (directory / "models.yaml").write_text(
        models
        or """
answer:
  - id: test/answer
    label: Test answer model
  - id: test/agent
utility: {id: utility/model}
judge: {id: test/judge}
"""
    )
