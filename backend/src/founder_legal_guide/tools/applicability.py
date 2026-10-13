"""Applicability checker: does GDPR, CCPA, COPPA, DSA or NIS2 apply, given a few facts?

Rules cite their provision; numeric thresholds come from config/thresholds.yaml. Answers are
"yes", "no" or "unclear"; "unclear" means a fact is missing or the line is a judgment call.
"""

from typing import Literal

from pydantic import BaseModel, Field

from .context import ToolContext

Answer = Literal["yes", "no", "unclear"]
IntermediaryService = Literal[
    "none", "mere_conduit", "caching", "hosting", "online_platform", "online_marketplace"
]
NIS2Sector = Literal[
    "none",
    "cloud_computing",
    "data_centre",
    "content_delivery_network",
    "managed_service_provider",
    "managed_security_service_provider",
    "online_marketplace",
    "online_search_engine",
    "social_network_platform",
    "dns_or_tld",
    "trust_service",
    "public_electronic_communications",
]
_SIZE_INDEPENDENT = {
    "dns_or_tld",
    "trust_service",
    "public_electronic_communications",
}  # NIS2 Art. 2(2)(a)


class BusinessFacts(BaseModel):
    """Facts about the business. Leave anything unknown as null."""

    established_in_eu: bool | None = Field(
        default=None, description="Has an establishment (office, subsidiary) in the EU."
    )
    offers_to_people_in_eu: bool | None = Field(
        default=None, description="Offers goods or services to people in the EU."
    )
    monitors_behaviour_in_eu: bool | None = Field(
        default=None, description="Tracks or profiles people's behaviour in the EU."
    )
    processes_personal_data: bool | None = None
    does_business_in_california: bool | None = None
    annual_gross_revenue_usd: float | None = Field(
        default=None, description="Worldwide, previous calendar year."
    )
    california_consumers_or_households: int | None = Field(
        default=None, description="Whose personal information is bought, sold or shared per year."
    )
    revenue_share_from_selling_or_sharing_data: float | None = Field(default=None, ge=0, le=1)
    service_directed_to_children_under_13: bool | None = None
    knowingly_collects_from_children_under_13: bool | None = None
    intermediary_service: IntermediaryService = Field(
        default="none", description="DSA category of the service, if any."
    )
    nis2_sector: NIS2Sector = "none"
    headcount: int | None = None
    annual_turnover_eur: float | None = None
    balance_sheet_total_eur: float | None = None


class LawResult(BaseModel):
    law: str
    applies: Answer
    reasons: list[str]
    references: list[str]


class Applicability(BaseModel):
    company_size: str
    results: list[LawResult]
    caveats: list[str]


def company_size(facts: BusinessFacts, thresholds: dict) -> str:
    """micro / small / medium / large under Recommendation 2003/361, or "unknown"."""
    if facts.headcount is None or (
        facts.annual_turnover_eur is None and facts.balance_sheet_total_eur is None
    ):
        return "unknown"
    for size in ("micro", "small", "medium"):
        t = thresholds["sme"][size]
        money_ok = any(
            value is not None and value <= ceiling
            for value, ceiling in (
                (facts.annual_turnover_eur, t["turnover_max_eur"]),
                (facts.balance_sheet_total_eur, t["balance_sheet_max_eur"]),
            )
        )
        if facts.headcount < t["headcount_below"] and money_ok:
            return size
    return "large"


def check_applicability(facts: BusinessFacts, ctx: ToolContext) -> Applicability:
    size = company_size(facts, ctx.thresholds)
    return Applicability(
        company_size=size,
        results=[
            _gdpr(facts),
            _ccpa(facts, ctx.thresholds["ccpa"]),
            _coppa(facts),
            _dsa(facts, size),
            _nis2(facts, size),
        ],
        caveats=[
            "Partner and linked enterprises count towards company size (Recommendation 2003/361, Annex Art. 6).",
            "National laws add duties on top (e.g. BDSG, TDDDG, BSIG in Germany; other US state privacy laws).",
            f"Thresholds checked {ctx.thresholds['ccpa']['checked']}; see config/thresholds.yaml.",
        ],
    )


def _gdpr(f: BusinessFacts) -> LawResult:
    refs = ["GDPR Art. 2", "GDPR Art. 3"]
    if f.processes_personal_data is False:
        return LawResult(
            law="GDPR",
            applies="no",
            reasons=["No personal data is processed (Art. 2(1))."],
            references=refs,
        )
    if f.established_in_eu:
        return LawResult(
            law="GDPR",
            applies="yes",
            reasons=["Processing in the context of an EU establishment (Art. 3(1))."],
            references=refs,
        )
    if f.offers_to_people_in_eu or f.monitors_behaviour_in_eu:
        why = (
            "offers goods or services to people in the EU"
            if f.offers_to_people_in_eu
            else "monitors behaviour in the EU"
        )
        return LawResult(
            law="GDPR",
            applies="yes",
            reasons=[
                f"Not established in the EU, but {why} (Art. 3(2)); an EU representative is usually required (Art. 27)."
            ],
            references=[*refs, "GDPR Art. 27"],
        )
    if (
        f.established_in_eu is False
        and f.offers_to_people_in_eu is False
        and f.monitors_behaviour_in_eu is False
    ):
        return LawResult(
            law="GDPR",
            applies="no",
            reasons=["No EU establishment, no offering to or monitoring of people in the EU."],
            references=refs,
        )
    return LawResult(
        law="GDPR",
        applies="unclear",
        reasons=[
            "Need to know: EU establishment, offering to people in the EU, or monitoring their behaviour."
        ],
        references=refs,
    )


def _ccpa(f: BusinessFacts, t: dict) -> LawResult:
    refs = [t["reference"]]
    if f.does_business_in_california is False:
        return LawResult(
            law="CCPA/CPRA",
            applies="no",
            reasons=["Does not do business in California."],
            references=refs,
        )
    # § 1798.140(d)(1): revenue "in excess of" the threshold; the other two "or more".
    tests = (
        (
            f.annual_gross_revenue_usd,
            lambda v: v > t["annual_gross_revenue_usd"],
            f"annual gross revenue above ${t['annual_gross_revenue_usd']:,}",
        ),
        (
            f.california_consumers_or_households,
            lambda v: v >= t["consumers_or_households"],
            f"buys, sells or shares data of {t['consumers_or_households']:,}+ consumers or households",
        ),
        (
            f.revenue_share_from_selling_or_sharing_data,
            lambda v: v >= t["revenue_share_from_selling_or_sharing"],
            "50%+ of revenue from selling or sharing personal information",
        ),
    )
    met = [label for value, passes, label in tests if value is not None and passes(value)]
    unknown = sum(value is None for value, _, _ in tests)
    if met and f.does_business_in_california:
        return LawResult(
            law="CCPA/CPRA",
            applies="yes",
            reasons=[f"Does business in California and meets: {'; '.join(met)}."],
            references=refs,
        )
    if met:
        return LawResult(
            law="CCPA/CPRA",
            applies="unclear",
            reasons=[
                f"Meets a threshold ({'; '.join(met)}), but doing business in California is not confirmed."
            ],
            references=refs,
        )
    if unknown:
        return LawResult(
            law="CCPA/CPRA",
            applies="unclear",
            reasons=["Below the known thresholds; some threshold facts are missing."],
            references=refs,
        )
    return LawResult(
        law="CCPA/CPRA",
        applies="no",
        reasons=["Below all three thresholds of § 1798.140(d)(1)."],
        references=refs,
    )


def _coppa(f: BusinessFacts) -> LawResult:
    refs = ["15 U.S.C. § 6502", "16 CFR Part 312"]
    if f.service_directed_to_children_under_13 or f.knowingly_collects_from_children_under_13:
        return LawResult(
            law="COPPA",
            applies="yes",
            reasons=[
                "Directed to children under 13, or actual knowledge of collecting their personal information."
            ],
            references=refs,
        )
    if (
        f.service_directed_to_children_under_13 is False
        and f.knowingly_collects_from_children_under_13 is False
    ):
        return LawResult(
            law="COPPA",
            applies="no",
            reasons=[
                "Not directed to children under 13 and no actual knowledge of collecting from them."
            ],
            references=refs,
        )
    return LawResult(
        law="COPPA",
        applies="unclear",
        reasons=[
            "Need to know whether the service targets or knowingly reaches children under 13."
        ],
        references=refs,
    )


def _dsa(f: BusinessFacts, size: str) -> LawResult:
    refs = ["DSA Art. 2-3"]
    if f.intermediary_service == "none":
        return LawResult(
            law="DSA",
            applies="no",
            reasons=["Not an intermediary service (mere conduit, caching or hosting)."],
            references=refs,
        )
    if f.offers_to_people_in_eu is False and not f.established_in_eu:
        return LawResult(
            law="DSA",
            applies="no",
            reasons=["No service offered to recipients in the EU (Art. 2(1))."],
            references=refs,
        )
    reasons = [
        "Intermediary service offered in the EU: liability rules and duties for all intermediaries (Art. 4-15) apply."
    ]
    refs += ["DSA Art. 11-15"]
    if f.intermediary_service in ("hosting", "online_platform", "online_marketplace"):
        reasons.append(
            "Hosting: notice-and-action mechanism and statements of reasons (Art. 16-17)."
        )
        refs.append("DSA Art. 16-18")
    small = size in ("micro", "small")
    if f.intermediary_service in ("online_platform", "online_marketplace"):
        if small:
            reasons.append(
                "As a micro or small enterprise (and not a very large online platform), the online-platform "
                "duties of Section 3 (Art. 20-28, except Art. 24(3)) and the marketplace duties of Section 4 "
                "(Art. 30-32) do not apply (Art. 19(1), 29(1)), nor does transparency reporting (Art. 15(2))."
            )
            refs.append("DSA Art. 15(2), 19, 29")
        elif size == "unknown":
            reasons.append(
                "Online-platform and marketplace duties (Art. 20-32) depend on company size; micro and small enterprises are largely exempt."
            )
        else:
            reasons.append(
                "Online-platform duties apply (Art. 20-28); for marketplaces also trader traceability and compliance by design (Art. 30-32)."
            )
            refs.append("DSA Art. 20-32")
    return LawResult(law="DSA", applies="yes", reasons=reasons, references=refs)


def _nis2(f: BusinessFacts, size: str) -> LawResult:
    refs = ["NIS2 Art. 2-3", "NIS2 Annex I-II", "BSIG (DE)"]
    if f.nis2_sector == "none":
        return LawResult(
            law="NIS2",
            applies="no",
            reasons=["Not in a digital sector listed in NIS2 Annex I or II."],
            references=refs,
        )
    if f.nis2_sector in _SIZE_INDEPENDENT:
        return LawResult(
            law="NIS2",
            applies="yes",
            reasons=["Sector covered regardless of size (Art. 2(2)(a))."],
            references=refs,
        )
    if size in ("micro", "small"):
        return LawResult(
            law="NIS2",
            applies="no",
            reasons=[f"Covered sector, but a {size} enterprise is below the size cap (Art. 2(1))."],
            references=refs,
        )
    if size == "unknown":
        return LawResult(
            law="NIS2",
            applies="unclear",
            reasons=[
                "Covered sector; applies from medium size upwards (Art. 2(1)). Headcount and turnover or balance sheet needed."
            ],
            references=refs,
        )
    return LawResult(
        law="NIS2",
        applies="yes",
        reasons=[
            f"Covered sector and a {size} enterprise (Art. 2(1)); in Germany, registration with the BSI under the BSIG."
        ],
        references=refs,
    )
