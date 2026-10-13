"""Compliance timeline: dated obligations from the Source Registry, filtered to the Founder."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from ..profile import LegalArea
from .context import ToolContext


class TimelineQuery(BaseModel):
    jurisdictions: list[Literal["EU", "DE", "US"]] | None = Field(
        default=None, description="Defaults to the Founder Profile's jurisdictions."
    )
    legal_areas: list[LegalArea] | None = Field(
        default=None, description="Restrict to these Legal Areas."
    )
    include_past_days: int = Field(
        default=365, ge=0, le=3650, description="How far back to list dates."
    )


class TimelineEvent(BaseModel):
    date: date
    source_id: str
    source: str
    jurisdiction: str
    what: str
    status: Literal["in_effect", "upcoming"]
    days_from_today: int
    legal_status: str


class Timeline(BaseModel):
    today: date
    events: list[TimelineEvent]
    note: str


def compliance_timeline(
    query: TimelineQuery,
    ctx: ToolContext,
    default_jurisdictions: set[str] | None = None,
    ai_role: str = "none",
) -> Timeline:
    jurisdictions = set(query.jurisdictions or default_jurisdictions or {"EU", "DE", "US"})
    areas = set(query.legal_areas or [])
    events = []
    for entry in ctx.sources.values():
        if entry.jurisdiction not in jurisdictions or entry.legal_status == "repealed":
            continue
        if areas and not areas.intersection(entry.legal_areas):
            continue
        # Without an AI role, AI-only law is noise, unless the Founder asked for it explicitly.
        if not areas and ai_role == "none" and set(entry.legal_areas) == {"ai_regulation"}:
            continue
        for item in entry.applies_from:
            delta = (item.date - ctx.today).days
            if delta < -query.include_past_days:
                continue
            events.append(
                TimelineEvent(
                    date=item.date,
                    source_id=entry.id,
                    source=entry.citation_name("en"),
                    jurisdiction=entry.jurisdiction,
                    what=item.what,
                    status="upcoming" if delta > 0 else "in_effect",
                    days_from_today=delta,
                    legal_status=entry.legal_status,
                )
            )
    events.sort(key=lambda e: e.date)
    return Timeline(
        today=ctx.today,
        events=events,
        note="Dates come from the Source Registry (config/sources.yaml). Pending proposals are not law.",
    )
