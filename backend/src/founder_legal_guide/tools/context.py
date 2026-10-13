"""What the domain tools read: the Source Registry, thresholds, and today's date."""

from dataclasses import dataclass, field
from datetime import date
from functools import cached_property
from pathlib import Path

import yaml

from ..ingestion.registry import SourceEntry, load_registry


@dataclass
class ToolContext:
    sources: dict[str, SourceEntry]
    thresholds: dict
    today: date = field(default_factory=date.today)
    version_store: object | None = None  # ingestion.state.SourceVersionStore
    fetcher_factory: object | None = None  # () -> Fetcher, for live checks

    @classmethod
    def load(cls, config_dir: Path, **kwargs) -> "ToolContext":
        entries = load_registry(config_dir / "sources.yaml")
        thresholds = yaml.safe_load((config_dir / "thresholds.yaml").read_text(encoding="utf-8"))
        return cls(sources={e.id: e for e in entries}, thresholds=thresholds, **kwargs)

    def applies_from(self, source_id: str) -> list[tuple[date, str]]:
        entry = self.sources.get(source_id)
        return [(a.date, a.what) for a in entry.applies_from] if entry else []

    @cached_property
    def ai_act_dates(self) -> dict[str, date]:
        """Key AI Act dates by their registry `key` (sources.yaml is the single source of truth)."""
        entry = self.sources.get("eu-ai-act")
        found = {a.key: a.date for a in entry.applies_from if a.key} if entry else {}
        if "new_prohibitions" in found:
            # The Art. 50(2) grace period for legacy generative systems ends the same day.
            found.setdefault("art50_2_legacy", found["new_prohibitions"])
        return found
