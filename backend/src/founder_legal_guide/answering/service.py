"""Runs one turn in a chosen Answering Mode and turns the graph's stream into UI events."""

import asyncio
from collections.abc import AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from ..disclaimer import DISCLAIMER
from ..profile import FounderProfile
from .citations import check_citations
from .guard import check_question
from .modes import AnsweringMode, Turn


def message_text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "") if isinstance(block, dict) else str(block) for block in content
    )


async def stream_turn(
    turn: Turn,
    mode: AnsweringMode,
    mode_name: str,
    utility_llm: BaseChatModel | None = None,
    profile: FounderProfile | None = None,
) -> AsyncIterator[dict]:
    """Guard the question, then run the mode's graph. The guard always runs: without a utility
    model it falls back to keyword checks."""
    yield {"type": "progress", "step": "guard", "label": "Checking the question"}
    guard = await asyncio.to_thread(check_question, turn.question, utility_llm)
    yield guard.event()
    turn.question = guard.question
    notes = [f"Founder Profile: {profile.summary()}"] if profile else []
    if guard_notes := guard.instructions():
        notes.append(guard_notes)
    turn.notes = "\n".join(notes)

    graph = mode.build(turn)
    initial = [*turn.history, HumanMessage(turn.question)]
    state: dict = {}

    async for stream_mode, chunk in graph.astream(
        {"messages": initial},
        stream_mode=["custom", "messages", "values"],
        config={"recursion_limit": mode.recursion_limit(turn)},
    ):
        if stream_mode == "custom":
            yield chunk
        elif stream_mode == "messages":
            message, metadata = chunk
            if (
                metadata.get("langgraph_node") in mode.answer_nodes
                and isinstance(message, AIMessageChunk)
                and not message.tool_call_chunks
            ):
                text = message_text(message.content)
                if text:
                    yield {"type": "token", "text": text}
        else:
            state = chunk

    new_messages = state.get("messages", [])[len(initial) :]
    answers = [m for m in new_messages if isinstance(m, AIMessage)]
    answer = message_text(answers[-1].content) if answers else ""
    report = check_citations(answer, turn.retrieved)
    yield {
        "type": "answer",
        "text": answer,
        "citations": {"cited": report.cited, "invalid": report.invalid, "ok": report.ok},
        "usage": _usage(answers),
        "answering_mode": mode_name,
        "escalations": [t["id"] for t in guard.event()["triggers"]],
        "strategy": turn.strategy.name,
        "disclaimer": DISCLAIMER,
    }


def _usage(messages: list[AIMessage]) -> dict:
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for m in messages:
        for key in totals:
            totals[key] += (m.usage_metadata or {}).get(key, 0)
    return totals
