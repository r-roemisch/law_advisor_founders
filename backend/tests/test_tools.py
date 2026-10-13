import io
import json
import zipfile
from datetime import date

import pytest

from founder_legal_guide.ingestion.adapters.eurlex import SPARQL_URL
from founder_legal_guide.ingestion.adapters.gii import ZIP_URL
from founder_legal_guide.ingestion.state import MemoryVersionStore
from founder_legal_guide.profile import FounderProfile
from founder_legal_guide.settings import REPO_ROOT
from founder_legal_guide.tools import ToolContext, build_domain_tools
from founder_legal_guide.tools.ai_act import AISystemFacts, classify_ai_system
from founder_legal_guide.tools.applicability import BusinessFacts, check_applicability
from founder_legal_guide.tools.currency import CurrencyQuery, check_source_currency
from founder_legal_guide.tools.timeline import TimelineQuery, compliance_timeline

from .ingestion_fakes import FakeFetcher, fixture, sparql_answer

TODAY = date(2026, 10, 12)


@pytest.fixture(scope="module")
def ctx():
    return ToolContext.load(REPO_ROOT / "config", today=TODAY, version_store=MemoryVersionStore())


# --- Founder Profile ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("involvement", "role"),
    [
        ("none", "none"),
        ("internal_tools", "deployer"),
        ("product_on_third_party_model", "provider"),
        ("trains_or_finetunes", "provider"),
        ("offers_gpai_model", "gpai_provider"),
    ],
)
def test_plain_language_ai_involvement_maps_to_ai_act_role(involvement, role):
    assert FounderProfile(ai_involvement=involvement).ai_role == role


def test_german_seat_implies_eu_and_german_law():
    assert FounderProfile(company_seat="DE", target_markets=["US"]).jurisdictions == {
        "EU",
        "DE",
        "US",
    }


# --- AI Act classifier ----------------------------------------------------------------------


def test_cv_screening_product_is_high_risk_for_its_provider(ctx):
    result = classify_ai_system(
        AISystemFacts(ai_involvement="product_on_third_party_model", annex_iii_area="employment"),
        ctx,
    )
    assert (result.risk_class, result.role, result.escalation) == ("high_risk", "provider", True)
    assert "Annex III point 4" in result.reasons[0]
    assert {o.applies_from for o in result.obligations} == {date(2027, 12, 2)}


def test_prohibited_practice_wins_over_everything(ctx):
    result = classify_ai_system(
        AISystemFacts(
            ai_involvement="internal_tools",
            prohibited_practices=["social_scoring"],
            annex_iii_area="employment",
        ),
        ctx,
    )
    assert result.risk_class == "prohibited" and result.escalation
    assert result.obligations[0].reference == "Art. 5(1)(c)"
    assert result.obligations[0].applies_from == date(2025, 2, 2)


def test_art_6_3_derogation_never_applies_to_profiling(ctx):
    facts = {
        "ai_involvement": "trains_or_finetunes",
        "annex_iii_area": "essential_services",
        "only_narrow_or_preparatory_task": True,
    }
    assert classify_ai_system(AISystemFacts(**facts), ctx).risk_class == "minimal"
    profiled = classify_ai_system(AISystemFacts(**facts, profiles_natural_persons=True), ctx)
    assert profiled.risk_class == "high_risk"


def test_chatbot_provider_gets_transparency_duties_with_dates(ctx):
    result = classify_ai_system(
        AISystemFacts(
            ai_involvement="product_on_third_party_model",
            interacts_with_people=True,
            generates_synthetic_content=True,
        ),
        ctx,
    )
    assert result.risk_class == "transparency"
    refs = {o.reference: o.applies_from for o in result.obligations}
    assert refs == {"Art. 50(1)": date(2026, 8, 2), "Art. 50(2)": date(2026, 8, 2)}
    assert any("2026-12-02" in c for c in result.caveats)


def test_annex_i_products_use_the_later_date(ctx):
    result = classify_ai_system(
        AISystemFacts(ai_involvement="trains_or_finetunes", annex_i_safety_component=True), ctx
    )
    assert result.risk_class == "high_risk"
    assert {o.applies_from for o in result.obligations} == {date(2028, 8, 2)}


def test_without_a_role_the_system_is_classified_but_no_duties_attach(ctx):
    result = classify_ai_system(AISystemFacts(annex_iii_area="employment"), ctx)
    assert (result.risk_class, result.role, result.escalation) == ("high_risk", "none", False)
    assert result.obligations == []
    assert "neither provides nor deploys" in result.reasons[-1]
    chatbot = classify_ai_system(AISystemFacts(interacts_with_people=True), ctx)
    assert chatbot.risk_class == "transparency" and chatbot.obligations == []


def test_gpai_provider_duties(ctx):
    result = classify_ai_system(
        AISystemFacts(ai_involvement="offers_gpai_model", gpai_with_systemic_risk=True), ctx
    )
    assert [o.reference for o in result.obligations] == ["Art. 53", "Art. 51, 55"]


def test_profile_supplies_the_role_when_the_model_omits_it(ctx):
    result = classify_ai_system(
        AISystemFacts(annex_iii_area="education"), ctx, default_involvement="internal_tools"
    )
    assert result.role == "deployer"
    assert [o.reference for o in result.obligations] == ["Art. 26", "Art. 27"]


# --- Applicability checker ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("headcount", "turnover", "balance", "size"),
    [
        (9, 2_000_000, None, "micro"),
        (9, 2_000_001, 1_000_000, "micro"),  # turnover OR balance sheet
        (10, 1_000_000, None, "small"),
        (49, 10_000_000, None, "small"),
        (50, 9_000_000, None, "medium"),
        (249, 60_000_000, 43_000_000, "medium"),
        (250, 1_000_000, None, "large"),
        (None, 1_000_000, None, "unknown"),
    ],
)
def test_sme_categories_follow_the_recommendation(ctx, headcount, turnover, balance, size):
    facts = BusinessFacts(
        headcount=headcount, annual_turnover_eur=turnover, balance_sheet_total_eur=balance
    )
    assert check_applicability(facts, ctx).company_size == size


def results(ctx, **facts):
    return {r.law: r for r in check_applicability(BusinessFacts(**facts), ctx).results}


def test_gdpr_territorial_scope(ctx):
    assert results(ctx, established_in_eu=True)["GDPR"].applies == "yes"
    us_seller = results(ctx, established_in_eu=False, offers_to_people_in_eu=True)["GDPR"]
    assert us_seller.applies == "yes" and "Art. 27" in us_seller.reasons[0]
    assert (
        results(
            ctx,
            established_in_eu=False,
            offers_to_people_in_eu=False,
            monitors_behaviour_in_eu=False,
        )["GDPR"].applies
        == "no"
    )
    assert results(ctx)["GDPR"].applies == "unclear"


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (
            {"does_business_in_california": True, "annual_gross_revenue_usd": 26_625_000},
            "unclear",
        ),  # not "in excess"
        ({"does_business_in_california": True, "annual_gross_revenue_usd": 26_625_001}, "yes"),
        (
            {"does_business_in_california": True, "california_consumers_or_households": 100_000},
            "yes",
        ),  # "or more"
        (
            {
                "does_business_in_california": True,
                "revenue_share_from_selling_or_sharing_data": 0.5,
            },
            "yes",
        ),
        ({"does_business_in_california": False, "annual_gross_revenue_usd": 1e9}, "no"),
        (
            {
                "does_business_in_california": True,
                "annual_gross_revenue_usd": 1e6,
                "california_consumers_or_households": 500,
                "revenue_share_from_selling_or_sharing_data": 0.0,
            },
            "no",
        ),
    ],
)
def test_ccpa_thresholds(ctx, facts, expected):
    assert results(ctx, **facts)["CCPA/CPRA"].applies == expected


def test_dsa_exempts_small_platforms_from_platform_duties(ctx):
    small = results(
        ctx,
        established_in_eu=True,
        intermediary_service="online_platform",
        headcount=12,
        annual_turnover_eur=2e6,
    )["DSA"]
    assert small.applies == "yes" and "Art. 19(1)" in small.reasons[-1]
    medium = results(
        ctx,
        established_in_eu=True,
        intermediary_service="online_marketplace",
        headcount=80,
        annual_turnover_eur=20e6,
    )["DSA"]
    assert "Art. 30-32" in medium.reasons[-1]


def test_nis2_size_cap_and_size_independent_sectors(ctx):
    assert (
        results(ctx, nis2_sector="cloud_computing", headcount=20, annual_turnover_eur=3e6)[
            "NIS2"
        ].applies
        == "no"
    )
    assert (
        results(ctx, nis2_sector="cloud_computing", headcount=60, annual_turnover_eur=3e6)[
            "NIS2"
        ].applies
        == "yes"
    )
    assert (
        results(ctx, nis2_sector="trust_service", headcount=3, annual_turnover_eur=1e5)[
            "NIS2"
        ].applies
        == "yes"
    )


def test_coppa(ctx):
    assert results(ctx, service_directed_to_children_under_13=True)["COPPA"].applies == "yes"
    assert results(ctx)["COPPA"].applies == "unclear"


# --- Timeline -------------------------------------------------------------------------------


def test_timeline_marks_past_and_upcoming_dates_in_order(ctx):
    timeline = compliance_timeline(
        TimelineQuery(jurisdictions=["EU"], legal_areas=["ai_regulation"]), ctx
    )
    dates = [e.date for e in timeline.events]
    assert dates == sorted(dates)
    by_date = {e.date: e for e in timeline.events if e.source_id == "eu-ai-act"}
    assert by_date[date(2027, 12, 2)].status == "upcoming"
    assert by_date[date(2026, 8, 2)].status == "in_effect"
    assert date(2025, 2, 2) not in by_date  # more than a year in the past


def test_timeline_follows_the_founder_profile(ctx):
    profile = FounderProfile(company_seat="DE", target_markets=["DE"])
    timeline = compliance_timeline(TimelineQuery(), ctx, profile.jurisdictions, profile.ai_role)
    assert {e.jurisdiction for e in timeline.events} <= {"EU", "DE"}
    assert not any(e.source_id == "eu-ai-act" for e in timeline.events)  # no AI role, not asked for


# --- Live source check ----------------------------------------------------------------------


def currency_ctx(routes):
    return ToolContext.load(
        REPO_ROOT / "config",
        today=TODAY,
        version_store=MemoryVersionStore(),
        fetcher_factory=lambda: FakeFetcher(routes),
    )


def test_eu_act_up_to_date_and_outdated():
    ctx = currency_ctx({(SPARQL_URL, None): sparql_answer("02024R1689-20260727")})
    assert check_source_currency(CurrencyQuery(source_id="eu-ai-act"), ctx).status == "not_indexed"
    ctx.version_store.record("eu-ai-act", "en", "02024R1689-20260727")
    assert check_source_currency(CurrencyQuery(source_id="eu-ai-act"), ctx).status == "up_to_date"
    ctx.version_store.record("eu-ai-act", "de", "02024R1689-20240712")
    stale = check_source_currency(CurrencyQuery(source_id="eu-ai-act"), ctx)
    assert stale.status == "newer_version_available" and "(de)" in stale.detail


def test_german_law_compares_the_build_date():
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("x.xml", fixture("gii/ddg.xml.gz"))
    ctx = currency_ctx({(ZIP_URL.format(slug="ddg"), None): archive.getvalue()})
    build = check_source_currency(CurrencyQuery(source_id="de-ddg"), ctx).official
    ctx.version_store.record("de-ddg", "de", f"{build}; Stand: …")
    assert check_source_currency(CurrencyQuery(source_id="de-ddg"), ctx).status == "up_to_date"


def test_unreachable_source_reports_unknown_and_unsupported_adapters_say_so():
    ctx = currency_ctx({})
    assert check_source_currency(CurrencyQuery(source_id="eu-ai-act"), ctx).status == "unknown"
    assert (
        check_source_currency(CurrencyQuery(source_id="us-section-230"), ctx).status
        == "unsupported"
    )


# --- LangChain wrappers ---------------------------------------------------------------------


def test_wrapped_tools_return_json_and_report_errors(ctx):
    tools = {
        t.name: t for t in build_domain_tools(ctx, FounderProfile(ai_involvement="internal_tools"))
    }
    assert set(tools) == {
        "classify_ai_system",
        "check_applicability",
        "compliance_timeline",
        "check_source_currency",
    }
    result = json.loads(tools["classify_ai_system"].invoke({"annex_iii_area": "employment"}))
    assert result["role"] == "deployer"
    failing = json.loads(tools["check_source_currency"].invoke({"source_id": "eu-ai-act"}))
    assert "error" in failing  # no fetcher configured in this context
