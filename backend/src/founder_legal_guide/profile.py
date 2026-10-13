"""The Founder Profile (CONTEXT.md): what shapes which law is relevant, never personal advice."""

from typing import Literal

from pydantic import BaseModel

LegalArea = Literal[
    "company_formation",
    "contracts",
    "data_protection",
    "ai_regulation",
    "platform_law",
    "intellectual_property",
    "employment",
    "cybersecurity_product",
    "fundraising",
]
Stage = Literal["idea", "pre_incorporation", "incorporated_pre_revenue", "revenue_or_seed"]
Seat = Literal["DE", "other_eu", "none"]
Market = Literal["EU", "DE", "US"]
AIInvolvement = Literal[
    "none",
    "internal_tools",  # uses AI tools in the company
    "product_on_third_party_model",  # builds a product on someone else's model (e.g. via an API)
    "trains_or_finetunes",  # trains or fine-tunes its own models
    "offers_gpai_model",  # makes a general-purpose AI model available to others
]
AIRole = Literal["none", "deployer", "provider", "gpai_provider"]
Customers = Literal["b2b", "b2c", "both"]
Headcount = Literal["1-9", "10-49", "50-249", "250+"]
RevenueBand = Literal["<2m", "2-10m", "10-50m", ">50m"]

# Plain-language answer → AI Act role. Putting an AI system on the market under your own name
# makes you its provider, even when the model underneath is someone else's (Art. 3(3), Art. 25).
_AI_ROLE: dict[AIInvolvement, AIRole] = {
    "none": "none",
    "internal_tools": "deployer",
    "product_on_third_party_model": "provider",
    "trains_or_finetunes": "provider",
    "offers_gpai_model": "gpai_provider",
}

_LABELS = {
    "idea": "idea stage",
    "pre_incorporation": "pre-incorporation",
    "incorporated_pre_revenue": "incorporated, pre-revenue",
    "revenue_or_seed": "revenue or seed-funded",
    "DE": "Germany",
    "other_eu": "another EU country",
    "none": "none yet",
}


class FounderProfile(BaseModel):
    stage: Stage = "idea"
    company_seat: Seat = "none"
    target_markets: list[Market] = []
    ai_involvement: AIInvolvement = "none"
    customers: Customers = "b2b"
    children_possible: bool = False
    headcount: Headcount = "1-9"
    revenue: RevenueBand = "<2m"

    @property
    def ai_role(self) -> AIRole:
        return _AI_ROLE[self.ai_involvement]

    @property
    def jurisdictions(self) -> set[str]:
        """Where the Founder's company sits and sells. A German seat implies EU and DE law."""
        result = set(self.target_markets)
        if self.company_seat == "DE":
            result |= {"EU", "DE"}
        elif self.company_seat == "other_eu":
            result.add("EU")
        if "DE" in result:
            result.add("EU")
        return result

    def summary(self) -> str:
        markets = ", ".join(self.target_markets) or "not set"
        return (
            f"Stage: {_LABELS[self.stage]}. Company seat: {_LABELS[self.company_seat]}. "
            f"Selling to: {markets}. AI Act role: {self.ai_role} ({self.ai_involvement.replace('_', ' ')}). "
            f"Customers: {self.customers}{', children may be users' if self.children_possible else ''}. "
            f"Headcount {self.headcount}, annual revenue {self.revenue} EUR."
        )
