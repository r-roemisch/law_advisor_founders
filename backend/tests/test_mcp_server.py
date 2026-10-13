from founder_legal_guide.disclaimer import DISCLAIMER
from founder_legal_guide.mcp_server import server


async def test_tools_are_listed_read_only():
    tools = {t.name: t for t in await server.list_tools()}
    assert set(tools) == {
        "classify_ai_system_tool",
        "check_applicability_tool",
        "compliance_timeline_tool",
        "check_source_currency_tool",
        "search_corpus",
    }
    assert all(t.annotations.read_only_hint for t in tools.values())


async def test_rule_checks_return_structured_results_with_the_disclaimer():
    result = await server.call_tool(
        "classify_ai_system_tool",
        {
            "facts": {
                "ai_involvement": "product_on_third_party_model",
                "annex_iii_area": "employment",
            }
        },
    )
    assert result.structured_content["risk_class"] == "high_risk"
    assert result.structured_content["disclaimer"] == DISCLAIMER
    applicability = await server.call_tool(
        "check_applicability_tool", {"facts": {"established_in_eu": True}}
    )
    gdpr = next(r for r in applicability.structured_content["results"] if r["law"] == "GDPR")
    assert gdpr["applies"] == "yes"
