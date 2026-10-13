"""Loads the Source Registry (config/sources.yaml)."""

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from ..config import ConfigError
from ..retrieval.types import SourceInfo


class Applicability(BaseModel):
    date: date
    what: str
    key: str | None = None  # stable name for code that needs a specific date, e.g. "general"


class SourceEntry(BaseModel):
    id: str
    title: str
    # Citation name, e.g. "GDPR", or per language: {en: GDPR, de: DSGVO}.
    short_title: str | dict[str, str] | None = None
    jurisdiction: Literal["EU", "DE", "US"]
    legal_areas: list[str]
    tier: Literal[1, 2, 3]
    languages: list[Literal["en", "de"]]
    legal_status: Literal["pending_proposal", "in_force", "repealed"]
    applies_from: list[Applicability] = Field(default_factory=list)
    adapter: str
    ref: dict
    update: Literal["auto", "review"]
    notes: str = ""

    def citation_name(self, language: str) -> str:
        """Short name used at the start of every citation, e.g. "GDPR" or "DSGVO"."""
        if isinstance(self.short_title, dict):
            return self.short_title.get(language) or next(iter(self.short_title.values()))
        if self.short_title:
            return self.short_title
        return self.title.split(" – ", 1)[-1]

    def info(self, url: str | None = None) -> SourceInfo:
        return SourceInfo(
            id=self.id,
            title=self.title,
            jurisdiction=self.jurisdiction,
            tier=self.tier,
            legal_areas=tuple(self.legal_areas),
            legal_status=self.legal_status,
            url=url or self.ref.get("url"),
        )


def load_registry(path: Path) -> list[SourceEntry]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, yaml.YAMLError) as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc
    entries = []
    for item in raw.get("sources") or []:
        try:
            entries.append(SourceEntry(**item))
        except ValidationError as exc:
            raise ConfigError(f"{path.name}: source '{item.get('id')}' is invalid:\n{exc}") from exc
    ids = [e.id for e in entries]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ConfigError(f"{path.name}: duplicate source ids: {', '.join(sorted(duplicates))}")
    return entries
