"""Domain tools the Answer Model can call. Each is a deterministic function with typed input;
the LangChain wrappers add Founder Profile defaults and report every call to the UI."""

import json
import logging
from collections.abc import Callable

from langchain_core.tools import StructuredTool
from langgraph.config import get_stream_writer
from pydantic import BaseModel

from ..profile import FounderProfile
from .ai_act import AISystemFacts, classify_ai_system
from .applicability import BusinessFacts, check_applicability
from .context import ToolContext
from .currency import CurrencyQuery, check_source_currency
from .timeline import TimelineQuery, compliance_timeline

log = logging.getLogger(__name__)

__all__ = ["ToolContext", "build_domain_tools"]


def _report(event: dict) -> None:
    try:
        get_stream_writer()(event)
    except (RuntimeError, KeyError):  # called outside a graph run (e.g. tests, MCP)
        pass


def _tool(
    name: str, description: str, schema: type[BaseModel], run: Callable[[BaseModel], BaseModel]
) -> StructuredTool:
    def call(**kwargs) -> str:
        args = schema(**kwargs)
        try:
            result = run(args).model_dump(mode="json")
        except Exception as exc:
            log.exception("tool %s failed", name)
            result = {"error": f"{type(exc).__name__}: {exc}"}
        _report(
            {
                "type": "tool",
                "name": name,
                "args": args.model_dump(mode="json", exclude_defaults=True),
                "result": result,
            }
        )
        return json.dumps(result, ensure_ascii=False)

    return StructuredTool.from_function(
        call, name=name, description=description, args_schema=schema
    )


def build_domain_tools(ctx: ToolContext, profile: FounderProfile | None) -> list[StructuredTool]:
    profile = profile or FounderProfile()
    return [
        _tool(
            "classify_ai_system",
            "Classify an AI system under the EU AI Act (prohibited, high-risk, transparency, minimal) and "
            "list the obligations with their application dates. Use whenever the question involves building, "
            "selling or using AI.",
            AISystemFacts,
            lambda a: classify_ai_system(a, ctx, profile.ai_involvement),
        ),
        _tool(
            "check_applicability",
            "Check whether GDPR, CCPA/CPRA, COPPA, the DSA and NIS2 apply, from facts about the business "
            "(establishment, markets, revenue, users, service type, size). Leave unknown facts null.",
            BusinessFacts,
            lambda a: check_applicability(a, ctx),
        ),
        _tool(
            "compliance_timeline",
            "List dated legal milestones (application dates, deadlines) relevant to the Founder, from the "
            "Source Registry. Use for 'when' questions and for the Deadlines section.",
            TimelineQuery,
            lambda a: compliance_timeline(a, ctx, profile.jurisdictions, profile.ai_role),
        ),
        _tool(
            "check_source_currency",
            "Check live whether the indexed text of a Source is still the current official version "
            "(EU acts via EUR-Lex, German laws via gesetze-im-internet.de).",
            CurrencyQuery,
            lambda a: check_source_currency(a, ctx),
        ),
    ]
