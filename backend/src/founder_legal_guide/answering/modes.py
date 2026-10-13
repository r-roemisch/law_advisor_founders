"""Answering Modes: how the guide gets from a question to an answer (CONTEXT.md, ADR 0007).

Each mode builds a LangGraph graph for one turn. Register new ones with
@ANSWERING_MODES.register. Every mode shares the `search_corpus` behaviour below, so the
citation check and the "how this answer was found" events work the same way in all of them.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import BaseModel, Field

from ..profile import LegalArea
from ..registry import Registry
from ..retrieval.strategy import RetrievalStrategy
from ..retrieval.types import SearchFilters
from .citations import RetrievedSet
from .prompts import AGENTIC_SYSTEM, SINGLE_PASS_SYSTEM, format_passages


@dataclass
class Turn:
    """Everything one question needs, fixed for the duration of the turn."""

    question: str
    history: list[BaseMessage]
    strategy: RetrievalStrategy
    llm: BaseChatModel
    filters: SearchFilters
    retrieved: RetrievedSet
    max_searches: int = 4
    tools: list[StructuredTool] = field(default_factory=list)  # domain tools, see tools/
    notes: str = ""  # Founder Profile and guard findings, for the system prompt

    def system_prompt(self, base: str) -> str:
        return f"{base}\n\nContext for this question:\n{self.notes}" if self.notes else base

    def new_messages(self, state: MessagesState) -> list[BaseMessage]:
        """Messages added during this turn (tool calls and results), after history + question."""
        return state["messages"][len(self.history) + 1 :]


class AnsweringMode(ABC):
    label: ClassVar[str]
    description: ClassVar[str]
    # Graph nodes whose model output is the Founder-facing answer (streamed as tokens).
    answer_nodes: ClassVar[frozenset[str]]

    @abstractmethod
    def build(self, turn: Turn) -> CompiledStateGraph: ...

    def recursion_limit(self, turn: Turn) -> int:
        return 25


ANSWERING_MODES: Registry[AnsweringMode] = Registry("answering mode")


def search_corpus(
    turn: Turn,
    query: str,
    jurisdictions: list[str] | None = None,
    legal_areas: list[str] | None = None,
) -> str:
    """Run the turn's Retrieval Strategy, number the hits within the turn, report them to
    the UI, and return the passages formatted for the model."""
    writer = get_stream_writer()
    writer({"type": "progress", "step": "search", "label": f"Searching: {query}"})
    filters = SearchFilters(
        jurisdictions=frozenset(jurisdictions) if jurisdictions else turn.filters.jurisdictions,
        legal_areas=frozenset(legal_areas) if legal_areas else turn.filters.legal_areas,
        tiers=turn.filters.tiers,
    )
    result = turn.strategy.retrieve(query, filters)
    numbered = turn.retrieved.add(result.hits)
    writer(
        {
            "type": "retrieval",
            "strategy": result.trace.strategy,
            "query": query,
            "queries": [{"text": q.text, "language": q.language} for q in result.trace.queries],
            "candidates": result.trace.candidates,
            "reranked": result.trace.reranked,
            "hits": [
                {
                    "n": n,
                    "label": h.passage.citation_label,
                    "source_id": h.passage.source.id,
                    "source_title": h.passage.source.title,
                    "tier": h.passage.source.tier,
                    "jurisdiction": h.passage.source.jurisdiction,
                    "legal_status": h.passage.source.legal_status,
                    "language": h.passage.language,
                    "anchor": h.passage.anchor,
                    "url": h.passage.source.url,
                    "score": round(h.score, 4),
                    "excerpt": h.passage.text[:400],
                }
                for n, h in numbered
            ],
        }
    )
    return format_passages(numbered)


class _SinglePassState(MessagesState):
    context: str


@ANSWERING_MODES.register("single_pass")
class SinglePass(AnsweringMode):
    label = "Single-pass"
    description = "Search once with the question, then answer (domain tools available)."
    answer_nodes = frozenset({"generate"})

    def build(self, turn: Turn) -> CompiledStateGraph:
        llm = turn.llm.bind_tools(turn.tools) if turn.tools else turn.llm

        def retrieve(state: _SinglePassState) -> dict:
            return {"context": search_corpus(turn, turn.question)}

        def generate(state: _SinglePassState) -> dict:
            used_tools = any(isinstance(m, ToolMessage) for m in state["messages"])
            label = (
                "Writing answer"
                if used_tools or not turn.tools
                else "Writing answer (may use tools)"
            )
            get_stream_writer()({"type": "progress", "step": "generate", "label": label})
            prompt = [
                SystemMessage(turn.system_prompt(SINGLE_PASS_SYSTEM)),
                *turn.history,
                HumanMessage(f"Question:\n{turn.question}\n\nPassages:\n{state['context']}"),
                *turn.new_messages(state),
            ]
            return {"messages": [llm.invoke(prompt)]}

        graph = StateGraph(_SinglePassState)
        graph.add_node("retrieve", retrieve)
        graph.add_node("generate", generate)
        graph.add_edge(START, "retrieve")
        graph.add_edge("retrieve", "generate")
        if turn.tools:
            graph.add_node("tools", ToolNode(turn.tools))
            graph.add_conditional_edges("generate", tools_condition)
            graph.add_edge("tools", "generate")
        else:
            graph.add_edge("generate", END)
        return graph.compile()


class _SearchArgs(BaseModel):
    query: str = Field(description="What to look up, in English or German legal terms.")
    jurisdictions: list[Literal["EU", "DE", "US"]] | None = Field(
        default=None, description="Restrict to these jurisdictions."
    )
    legal_areas: list[LegalArea] | None = Field(
        default=None,
        description=(
            "Restrict to these Legal Areas: company_formation, contracts, data_protection, "
            "ai_regulation, platform_law, intellectual_property, employment, "
            "cybersecurity_product, fundraising."
        ),
    )


@ANSWERING_MODES.register("agentic")
class Agentic(AnsweringMode):
    label = "Agentic"
    description = "The model decides what to search for and may search several times."
    answer_nodes = frozenset({"agent"})

    def recursion_limit(self, turn: Turn) -> int:
        return 2 * (turn.max_searches + len(turn.tools)) + 6

    def build(self, turn: Turn) -> CompiledStateGraph:
        searches = 0

        def run_search(query: str, jurisdictions=None, legal_areas=None) -> str:
            nonlocal searches
            if searches >= turn.max_searches:
                return "Search limit reached. Answer with the passages you already have."
            searches += 1
            return search_corpus(turn, query, jurisdictions, legal_areas)

        tool = StructuredTool.from_function(
            run_search,
            name="search_corpus",
            description="Search the legal Corpus (EU, German and US law, guidance and "
            "practical sources). Returns numbered passages to cite as [n].",
            args_schema=_SearchArgs,
        )
        tools = [tool, *turn.tools]
        llm = turn.llm.bind_tools(tools)

        def agent(state: MessagesState) -> dict:
            searched = any(isinstance(m, ToolMessage) for m in state["messages"])
            label = "Writing answer" if searched else "Planning searches"
            get_stream_writer()({"type": "progress", "step": "agent", "label": label})
            prompt = [SystemMessage(turn.system_prompt(AGENTIC_SYSTEM)), *state["messages"]]
            return {"messages": [llm.invoke(prompt)]}

        graph = StateGraph(MessagesState)
        graph.add_node("agent", agent)
        graph.add_node("tools", ToolNode(tools))
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", tools_condition)
        graph.add_edge("tools", "agent")
        return graph.compile()
