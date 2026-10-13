"""AI Act risk classifier: a deterministic decision tree over Art. 5, 6, 50 and 51-55.

It classifies what the Founder describes; it does not judge whether the description is right.
Anything prohibited or high-risk is an Escalation Trigger (talk to a lawyer).
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from ..profile import AIInvolvement, AIRole
from .context import ToolContext

ProhibitedPractice = Literal[
    "subliminal_or_manipulative",  # Art. 5(1)(a)
    "exploits_vulnerabilities",  # Art. 5(1)(b)
    "social_scoring",  # Art. 5(1)(c)
    "crime_prediction_by_profiling",  # Art. 5(1)(d)
    "untargeted_facial_image_scraping",  # Art. 5(1)(e)
    "emotion_recognition_work_or_education",  # Art. 5(1)(f)
    "biometric_categorisation_sensitive_traits",  # Art. 5(1)(g)
    "realtime_remote_biometric_id_law_enforcement",  # Art. 5(1)(h)
    "non_consensual_intimate_deepfakes_or_csam",  # Art. 5(1)(ba)-(bb), inserted by 2026/1744
]
AnnexIIIArea = Literal[
    "biometrics",
    "critical_infrastructure",
    "education",
    "employment",
    "essential_services",
    "law_enforcement",
    "migration_border",
    "justice_democracy",
]
_ANNEX_III_POINT = {
    "biometrics": 1,
    "critical_infrastructure": 2,
    "education": 3,
    "employment": 4,
    "essential_services": 5,
    "law_enforcement": 6,
    "migration_border": 7,
    "justice_democracy": 8,
}
_PROHIBITED_REF = {
    "subliminal_or_manipulative": "Art. 5(1)(a)",
    "exploits_vulnerabilities": "Art. 5(1)(b)",
    "social_scoring": "Art. 5(1)(c)",
    "crime_prediction_by_profiling": "Art. 5(1)(d)",
    "untargeted_facial_image_scraping": "Art. 5(1)(e)",
    "emotion_recognition_work_or_education": "Art. 5(1)(f)",
    "biometric_categorisation_sensitive_traits": "Art. 5(1)(g)",
    "realtime_remote_biometric_id_law_enforcement": "Art. 5(1)(h)",
    "non_consensual_intimate_deepfakes_or_csam": "Art. 5(1)(ba)-(bb)",
}
_ROLE: dict[AIInvolvement, AIRole] = {
    "none": "none",
    "internal_tools": "deployer",
    "product_on_third_party_model": "provider",
    "trains_or_finetunes": "provider",
    "offers_gpai_model": "gpai_provider",
}


class AISystemFacts(BaseModel):
    """What the Founder's AI system does. Unknown answers should stay at their defaults."""

    ai_involvement: AIInvolvement | None = Field(
        default=None,
        description="How the company is involved with AI (decides provider vs deployer). "
        "Defaults to the Founder Profile.",
    )
    prohibited_practices: list[ProhibitedPractice] = Field(
        default_factory=list, description="Any Art. 5 practice the system performs."
    )
    annex_i_safety_component: bool = Field(
        default=False,
        description="The AI is a safety component of (or is) a product under EU product-safety "
        "law listed in Annex I that needs third-party conformity assessment (e.g. medical devices, machinery).",
    )
    annex_iii_area: AnnexIIIArea | None = Field(
        default=None, description="The Annex III use area the system is intended for, if any."
    )
    profiles_natural_persons: bool = Field(
        default=False,
        description="The system profiles natural persons (always high-risk under Annex III).",
    )
    only_narrow_or_preparatory_task: bool = Field(
        default=False,
        description="The Annex III system only performs a narrow procedural or preparatory task, or "
        "improves a completed human activity, without materially influencing decisions (Art. 6(3)).",
    )
    interacts_with_people: bool = Field(
        default=False, description="Chatbots, voice assistants, agents."
    )
    generates_synthetic_content: bool = Field(
        default=False, description="Generates text, images, audio or video."
    )
    creates_deepfakes: bool = Field(
        default=False,
        description="Generates or manipulates realistic depictions of real people, places or events.",
    )
    emotion_recognition_or_biometric_categorisation: bool = Field(
        default=False, description="Outside the prohibited cases of Art. 5."
    )
    gpai_with_systemic_risk: bool = Field(
        default=False, description="General-purpose model trained with more than 10^25 FLOP."
    )


class Obligation(BaseModel):
    reference: str
    duty: str
    applies_from: date | None = None


class AIActClassification(BaseModel):
    risk_class: Literal["prohibited", "high_risk", "transparency", "minimal"]
    role: AIRole
    reasons: list[str]
    obligations: list[Obligation]
    escalation: bool
    caveats: list[str]


def classify_ai_system(
    facts: AISystemFacts, ctx: ToolContext, default_involvement: AIInvolvement = "none"
) -> AIActClassification:
    role = _ROLE[facts.ai_involvement or default_involvement]
    dates = ctx.ai_act_dates
    reasons, obligations, caveats = (
        [],
        [],
        [
            "This classifies the facts as described; misdescribed facts give a wrong result.",
            "Check the Commission's guidelines on the AI system definition and on high-risk classification.",
        ],
    )

    if facts.prohibited_practices:
        refs = ", ".join(_PROHIBITED_REF[p] for p in facts.prohibited_practices)
        when = (
            dates.get("new_prohibitions")
            if facts.prohibited_practices == ["non_consensual_intimate_deepfakes_or_csam"]
            else dates.get("prohibitions")
        )
        return AIActClassification(
            risk_class="prohibited",
            role=role,
            reasons=[f"Prohibited practice under {refs}."],
            obligations=[
                Obligation(
                    reference=refs,
                    duty="Do not place on the market, put into service or use.",
                    applies_from=when,
                )
            ],
            escalation=True,
            caveats=caveats,
        )

    risk_class = "minimal"
    if facts.annex_i_safety_component:
        risk_class = "high_risk"
        reasons.append(
            "Safety component of an Annex I product needing third-party conformity assessment (Art. 6(1))."
        )
        high_risk_date = dates.get("high_risk_annex_i")
    elif facts.annex_iii_area:
        point = _ANNEX_III_POINT[facts.annex_iii_area]
        if facts.only_narrow_or_preparatory_task and not facts.profiles_natural_persons:
            reasons.append(
                f"Annex III point {point} area, but the Art. 6(3) derogation may apply (no significant risk). "
                "The provider must document this assessment before placing on the market and register the system (Art. 6(4), Art. 49(2))."
            )
            obligations.append(
                Obligation(
                    reference="Art. 6(4), Art. 49(2)",
                    duty="Document the not-high-risk assessment and register the system.",
                    applies_from=dates.get("high_risk_annex_iii"),
                )
            )
            caveats.append(
                "The Art. 6(3) derogation is narrow; treat a doubtful case as high-risk."
            )
            high_risk_date = None
        else:
            risk_class = "high_risk"
            why = (
                " (it profiles natural persons, so Art. 6(3) cannot apply)"
                if facts.profiles_natural_persons
                else ""
            )
            reasons.append(f"Annex III point {point} use case{why} (Art. 6(2)).")
            high_risk_date = dates.get("high_risk_annex_iii")
    else:
        high_risk_date = None

    if risk_class == "high_risk" and role != "none":
        if role in ("provider", "gpai_provider"):
            obligations += [
                Obligation(
                    reference="Art. 8-15",
                    duty="Meet the requirements: risk management, data governance, technical documentation, logging, transparency to deployers, human oversight, accuracy and robustness.",
                    applies_from=high_risk_date,
                ),
                Obligation(
                    reference="Art. 16-17",
                    duty="Provider duties, including a quality management system.",
                    applies_from=high_risk_date,
                ),
                Obligation(
                    reference="Art. 43, 47-49",
                    duty="Conformity assessment, EU declaration of conformity, CE marking, registration in the EU database.",
                    applies_from=high_risk_date,
                ),
            ]
        else:
            obligations += [
                Obligation(
                    reference="Art. 26",
                    duty="Deployer duties: use per instructions, human oversight, monitor, keep logs, inform affected workers where relevant.",
                    applies_from=high_risk_date,
                ),
                Obligation(
                    reference="Art. 27",
                    duty="Fundamental rights impact assessment where the deployer is a public body, provides public services, or uses credit-scoring or life/health-insurance systems.",
                    applies_from=high_risk_date,
                ),
            ]

    transparency = []
    if facts.interacts_with_people and role in ("provider", "gpai_provider"):
        transparency.append(
            Obligation(
                reference="Art. 50(1)",
                duty="Design the system so people know they are interacting with AI, unless obvious.",
                applies_from=dates.get("general"),
            )
        )
    if facts.generates_synthetic_content and role in ("provider", "gpai_provider"):
        transparency.append(
            Obligation(
                reference="Art. 50(2)",
                duty="Mark synthetic output in a machine-readable, detectable way.",
                applies_from=dates.get("general"),
            )
        )
        caveats.append(
            f"Systems placed on the market before {dates.get('general')} have until {dates.get('art50_2_legacy')} for Art. 50(2) marking."
        )
    if facts.emotion_recognition_or_biometric_categorisation and role == "deployer":
        transparency.append(
            Obligation(
                reference="Art. 50(3)",
                duty="Inform exposed people of the system's operation.",
                applies_from=dates.get("general"),
            )
        )
    if facts.creates_deepfakes and role == "deployer":
        transparency.append(
            Obligation(
                reference="Art. 50(4)",
                duty="Disclose that deepfake content is artificially generated or manipulated.",
                applies_from=dates.get("general"),
            )
        )
    if transparency:
        obligations += transparency
        if risk_class == "minimal":
            risk_class = "transparency"
            reasons.append("Transparency obligations under Art. 50 apply.")

    if role == "gpai_provider":
        obligations.append(
            Obligation(
                reference="Art. 53",
                duty="GPAI provider duties: technical documentation, information for downstream providers, copyright policy, public summary of training content.",
                applies_from=dates.get("gpai"),
            )
        )
        if facts.gpai_with_systemic_risk:
            obligations.append(
                Obligation(
                    reference="Art. 51, 55",
                    duty="Notify the Commission; model evaluation, adversarial testing, incident reporting, cybersecurity.",
                    applies_from=dates.get("gpai"),
                )
            )

    if role == "none":
        # The risk class belongs to the system; obligations attach to its provider or deployer.
        art50 = (
            facts.interacts_with_people
            or facts.generates_synthetic_content
            or facts.creates_deepfakes
            or facts.emotion_recognition_or_biometric_categorisation
        )
        if risk_class == "minimal" and art50:
            risk_class = "transparency"
            reasons.append("Transparency obligations under Art. 50 attach to such a system.")
        reasons.append(
            "The company neither provides nor deploys this system, so no obligations attach to it; "
            "the risk class describes the system itself."
        )
        obligations = []
    if risk_class == "minimal":
        reasons.append(
            "No prohibited practice, no high-risk use case and no Art. 50 trigger described."
        )
    if role == "deployer" and risk_class != "high_risk":
        caveats.append(
            "Deployers become providers if they put their name on a system or substantially modify it (Art. 25)."
        )

    return AIActClassification(
        risk_class=risk_class,
        role=role,
        reasons=reasons,
        obligations=obligations,
        escalation=risk_class == "high_risk" and role != "none",
        caveats=caveats,
    )
