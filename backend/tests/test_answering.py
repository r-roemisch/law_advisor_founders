import pytest
from langchain_core.messages import AIMessage

from founder_legal_guide.answering import (
    ANSWERING_MODES,
    RetrievedSet,
    Turn,
    check_citations,
    stream_turn,
)
from founder_legal_guide.disclaimer import DISCLAIMER
from founder_legal_guide.retrieval.strategy import RetrievalStrategy
from founder_legal_guide.retrieval.types import Hit, SearchFilters

from .conftest import scripted
from .test_retrieval import spec


@pytest.fixture
def strategy(ctx, gdpr_doc, bdsg_doc):
    s = RetrievalStrategy(spec(), ctx)
    s.index_document(gdpr_doc)
    s.index_document(bdsg_doc)
    return s


def make_turn(strategy, llm, question="When must a data breach be notified?"):
    return Turn(
        question=question,
        history=[],
        strategy=strategy,
        llm=llm,
        filters=SearchFilters(),
        retrieved=RetrievedSet(),
        max_searches=2,
    )


async def collect(turn, mode_name):
    return [e async for e in stream_turn(turn, ANSWERING_MODES.get(mode_name)(), mode_name)]


def test_retrieved_set_numbers_passages_once_across_searches(strategy):
    retrieved = RetrievedSet()
    first = strategy.retrieve("breach").hits
    numbered_a = retrieved.add(first)
    numbered_b = retrieved.add(first[:1])
    assert [n for n, _ in numbered_a] == list(range(1, len(first) + 1))
    assert numbered_b[0][0] == 1


def test_citation_check_flags_numbers_that_were_never_retrieved(strategy):
    retrieved = RetrievedSet()
    retrieved.add([Hit(p.passage, 1.0) for p in strategy.retrieve("breach").hits[:2]])
    report = check_citations("Notify within 72 hours [1][2], see also [7].", retrieved)
    assert report.cited == [1, 2]
    assert report.invalid == [7]
    assert not report.ok


async def test_single_pass_streams_progress_sources_tokens_and_checked_answer(strategy):
    llm = scripted(f"**Short answer** Within 72 hours [1].\n\n_{DISCLAIMER}_")
    events = await collect(make_turn(strategy, llm), "single_pass")
    types = [e["type"] for e in events]

    assert types[0] == "progress"
    assert "retrieval" in types
    assert "token" in types
    answer = events[-1]
    assert answer["type"] == "answer"
    assert answer["citations"] == {"cited": [1], "invalid": [], "ok": True}
    assert answer["disclaimer"] == DISCLAIMER
    assert answer["answering_mode"] == "single_pass"
    retrieval = next(e for e in events if e["type"] == "retrieval")
    assert retrieval["hits"][0]["n"] == 1
    # The passages reach the model wrapped as data.
    assert '<passage n="1"' in llm.seen[0][-1].content


async def test_agentic_mode_searches_via_tool_then_answers(strategy):
    llm = scripted(
        AIMessage(
            "",
            tool_calls=[
                {"name": "search_corpus", "args": {"query": "breach 72 hours"}, "id": "c1"}
            ],
        ),
        AIMessage(
            "",
            tool_calls=[
                {
                    "name": "search_corpus",
                    "args": {"query": "Meldung Datenpanne", "jurisdictions": ["DE"]},
                    "id": "c2",
                }
            ],
        ),
        "Notify the authority within 72 hours [1]; German employee data rules also apply [4].",
    )
    events = await collect(make_turn(strategy, llm), "agentic")

    searches = [e for e in events if e["type"] == "retrieval"]
    assert [s["query"] for s in searches] == ["breach 72 hours", "Meldung Datenpanne"]
    assert {h["jurisdiction"] for h in searches[1]["hits"]} == {"DE"}
    answer = events[-1]
    assert answer["answering_mode"] == "agentic"
    assert answer["citations"]["cited"] == [1, 4]
    assert answer["citations"]["ok"]


async def test_agentic_mode_enforces_search_limit(strategy):
    calls = [
        AIMessage(
            "", tool_calls=[{"name": "search_corpus", "args": {"query": f"q{i}"}, "id": f"c{i}"}]
        )
        for i in range(3)
    ]
    llm = scripted(*calls, "Done [1].")
    events = await collect(make_turn(strategy, llm), "agentic")
    assert len([e for e in events if e["type"] == "retrieval"]) == 2
    assert events[-1]["type"] == "answer"


async def test_guard_runs_first_and_tools_work_in_single_pass(strategy):
    from datetime import date

    from founder_legal_guide.ingestion.state import MemoryVersionStore
    from founder_legal_guide.profile import FounderProfile
    from founder_legal_guide.settings import REPO_ROOT
    from founder_legal_guide.tools import ToolContext, build_domain_tools

    from .conftest import FakeModels

    profile = FounderProfile(company_seat="DE", ai_involvement="product_on_third_party_model")
    tool_ctx = ToolContext.load(
        REPO_ROOT / "config", today=date(2026, 10, 12), version_store=MemoryVersionStore()
    )
    llm = scripted(
        AIMessage(
            "",
            tool_calls=[
                {"name": "classify_ai_system", "args": {"annex_iii_area": "employment"}, "id": "t1"}
            ],
        ),
        "High-risk under the AI Act [1] (rule check: classify_ai_system).",
    )
    turn = make_turn(
        strategy, llm, question="We screen CVs with AI. Contact me: ceo@startup.example"
    )
    turn.tools = build_domain_tools(tool_ctx, profile)
    utility = FakeModels(
        utility=lambda system, user: {"triggers": [5], "tax_question": False}
    ).chat("utility")

    events = [
        e
        async for e in stream_turn(
            turn, ANSWERING_MODES.get("single_pass")(), "single_pass", utility, profile
        )
    ]

    guard = next(e for e in events if e["type"] == "guard")
    assert events.index(guard) < next(i for i, e in enumerate(events) if e["type"] == "retrieval")
    assert guard["personal_data"] == ["email"] and guard["triggers"][0]["id"] == 5
    tool = next(e for e in events if e["type"] == "tool")
    assert tool["name"] == "classify_ai_system"
    assert tool["result"]["risk_class"] == "high_risk" and tool["result"]["role"] == "provider"
    answer = events[-1]
    assert answer["escalations"] == [5] and answer["citations"]["ok"]
    # The model never saw the email address, but did see the profile and the trigger.
    first_prompt = llm.seen[0]
    assert "ceo@startup.example" not in str([m.content for m in first_prompt])
    assert "AI Act role: provider" in first_prompt[0].content
    assert "Escalation triggers detected: 5." in first_prompt[0].content
