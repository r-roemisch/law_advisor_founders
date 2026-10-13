"""The Founder Legal Guide's tools as an MCP server.

Exposes the four Rule Checks and corpus search to any MCP client (Claude Desktop, Claude Code,
IDEs). Every result carries the "not legal advice" statement (ADR 0002).

    founder-legal-guide-mcp                 # stdio, for desktop clients
    founder-legal-guide-mcp --http 8765     # streamable HTTP at http://localhost:8765/mcp
"""

import argparse
from functools import lru_cache
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .disclaimer import DISCLAIMER
from .ingestion.http import Fetcher
from .ingestion.state import PostgresVersionStore
from .profile import AIInvolvement, LegalArea
from .retrieval.types import SearchFilters
from .settings import get_settings
from .tools import ToolContext
from .tools.ai_act import AISystemFacts, classify_ai_system
from .tools.applicability import BusinessFacts, check_applicability
from .tools.currency import CurrencyQuery, check_source_currency
from .tools.timeline import TimelineQuery, compliance_timeline

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

server = MCPServer(
    name="founder-legal-guide",
    title="Founder Legal Guide",
    instructions=(
        "Rule checks and a searchable corpus of EU, German and US law for tech and AI founders. "
        f"{DISCLAIMER} Cite search results by their citation label; never present a pending proposal as law."
    ),
)


@lru_cache(maxsize=1)
def _context() -> ToolContext:
    settings = get_settings()
    return ToolContext.load(
        settings.config_dir,
        version_store=PostgresVersionStore(settings.database_url),
        fetcher_factory=Fetcher,
    )


@lru_cache(maxsize=1)
def _app_state():
    from .api import AppState  # heavy: models, strategies; only needed for search

    return AppState(get_settings())


def _with_disclaimer(result) -> dict[str, Any]:
    return result.model_dump(mode="json") | {"disclaimer": DISCLAIMER}


@server.tool(annotations=READ_ONLY, structured_output=True)
def classify_ai_system_tool(
    facts: AISystemFacts, role_if_unstated: AIInvolvement = "none"
) -> dict[str, Any]:
    """Classify an AI system under the EU AI Act (prohibited / high-risk / transparency / minimal)
    and list the obligations with their application dates."""
    return _with_disclaimer(classify_ai_system(facts, _context(), role_if_unstated))


@server.tool(annotations=READ_ONLY, structured_output=True)
def check_applicability_tool(facts: BusinessFacts) -> dict[str, Any]:
    """Check whether GDPR, CCPA/CPRA, COPPA, the DSA and NIS2 apply, from facts about a business.
    Leave unknown facts out."""
    return _with_disclaimer(check_applicability(facts, _context()))


@server.tool(annotations=READ_ONLY, structured_output=True)
def compliance_timeline_tool(query: TimelineQuery) -> dict[str, Any]:
    """Dated legal milestones (application dates, deadlines) from the Source Registry."""
    return _with_disclaimer(compliance_timeline(query, _context(), None, "provider"))


@server.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True), structured_output=True
)
def check_source_currency_tool(source_id: str) -> dict[str, Any]:
    """Check live whether the indexed text of a Source is the current official version."""
    return _with_disclaimer(check_source_currency(CurrencyQuery(source_id=source_id), _context()))


@server.tool(annotations=READ_ONLY, structured_output=True)
def search_corpus(
    query: str,
    jurisdictions: list[Literal["EU", "DE", "US"]] | None = None,
    legal_areas: list[LegalArea] | None = None,
    strategy: str | None = None,
    k: int = 8,
) -> dict[str, Any]:
    """Search the legal Corpus (EU, German and US law, official guidance, practical pages) with a
    Retrieval Strategy (default: the configured default). English or German queries."""
    state = _app_state()
    name = strategy or state.strategies_config.default
    if name not in state.strategies_config.enabled():
        raise ValueError(f"Unknown or disabled strategy '{name}'")
    filters = SearchFilters(
        jurisdictions=frozenset(jurisdictions) if jurisdictions else None,
        legal_areas=frozenset(legal_areas) if legal_areas else None,
    )
    result = state.strategy(name).retrieve(query, filters, k=max(1, min(k, 20)))
    return {
        "strategy": name,
        "passages": [
            {
                "citation": h.passage.citation_label,
                "source_id": h.passage.source.id,
                "jurisdiction": h.passage.source.jurisdiction,
                "tier": h.passage.source.tier,
                "legal_status": h.passage.source.legal_status,
                "language": h.passage.language,
                "url": h.passage.source.url,
                "text": h.passage.text,
            }
            for h in result.hits
        ],
        "disclaimer": DISCLAIMER,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="founder-legal-guide-mcp")
    parser.add_argument(
        "--http", type=int, metavar="PORT", help="Serve streamable HTTP instead of stdio"
    )
    args = parser.parse_args(argv)
    if args.http:
        server.run("streamable-http", host="0.0.0.0", port=args.http)
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()
