"""The update run: detect changed Sources, apply or queue them, and write Change Records.

- Every Source is fetched and fingerprinted per section (a hash of each section's text).
- Unchanged text produces nothing, even when the version string moved (e.g. a rebuilt file).
- New Sources are indexed directly (the registry entry itself was the review).
- Changed `update: auto` Sources (structured official data) are re-indexed: status "applied".
- Changed `update: review` Sources (scraped pages) are queued with the fetched text: status
  "review_needed". Approving indexes exactly the reviewed text; rejecting keeps the old one.
"""

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from ..retrieval.strategy import RetrievalStrategy
from ..retrieval.types import Section, SourceDocument, SourceInfo
from .adapters import ADAPTERS
from .registry import SourceEntry
from .state import ChangeRecord, CorpusState

log = logging.getLogger(__name__)

Event = Callable[[dict], None]


@dataclass
class UpdateReport:
    unchanged: list[str] = field(default_factory=list)
    changes: list[ChangeRecord] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> dict:
        count = lambda status: sum(c.status == status for c in self.changes)
        return {
            "unchanged": len(self.unchanged),
            "applied": count("applied"),
            "review_needed": count("review_needed"),
            "failed": [{"source_id": s, "error": e} for s, e in self.failed],
        }


def section_hashes(doc: SourceDocument) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for section in doc.sections:
        label = " › ".join(section.heading_path[1:]) or section.heading_path[0]
        key, n = label, 2
        while key in hashes:  # untitled or repeated headings stay distinct
            key, n = f"{label} ({n})", n + 1
        hashes[key] = hashlib.sha256(section.text.encode()).hexdigest()[:16]
    return hashes


def diff(old: dict[str, str], new: dict[str, str]) -> dict[str, list[str]]:
    return {
        "added": [k for k in new if k not in old],
        "removed": [k for k in old if k not in new],
        "modified": [k for k in new if k in old and old[k] != new[k]],
    }


def run_update(
    entries: list[SourceEntry],
    fetcher,
    strategies: list[RetrievalStrategy],
    state: CorpusState,
    on_event: Event = lambda e: None,
) -> UpdateReport:
    report = UpdateReport()
    for position, entry in enumerate(entries, start=1):
        on_event(
            {"type": "progress", "source_id": entry.id, "position": position, "total": len(entries)}
        )
        try:
            documents = ADAPTERS.get(entry.adapter)(fetcher).fetch(entry)
            if not documents:
                raise ValueError("no text in any language")
        except Exception as exc:  # noqa: BLE001  (one bad Source must not stop the run)
            report.failed.append((entry.id, str(exc)))
            on_event({"type": "failed", "source_id": entry.id, "error": str(exc)})
            continue
        for doc in documents:
            change = _check_document(entry, doc, strategies, state)
            if change is None:
                report.unchanged.append(f"{entry.id}:{doc.language}")
            else:
                report.changes.append(change)
                on_event({"type": "change", **change.public()})
    on_event({"type": "summary", **report.summary()})
    return report


def _check_document(
    entry: SourceEntry, doc: SourceDocument, strategies: list[RetrievalStrategy], state: CorpusState
) -> ChangeRecord | None:
    hashes = section_hashes(doc)
    previous = state.current(entry.id, doc.language)
    if previous is not None:
        changes = diff(previous.section_hashes, hashes)
        if not any(changes.values()):
            if previous.version != doc.version:
                state.record(entry.id, doc.language, doc.version, hashes)  # same text, new label
            return None
    else:
        changes = {"added": list(hashes), "removed": [], "modified": []}

    change = ChangeRecord(
        source_id=entry.id,
        language=doc.language,
        kind="changed" if previous else "added",
        status="applied",
        old_version=previous.version if previous else None,
        new_version=doc.version,
        summary=changes,
    )
    if previous is not None and entry.update == "review":
        change.status = "review_needed"
        change.pending = document_to_dict(doc)
    else:
        _apply(doc, hashes, strategies, state)
    state.add_change(change)
    return change


def _apply(
    doc: SourceDocument, hashes: dict, strategies: list[RetrievalStrategy], state: CorpusState
) -> None:
    for strategy in strategies:
        strategy.index_document(doc)
    state.record(doc.source.id, doc.language, doc.version, hashes)


def approve(
    change_id: int, strategies: list[RetrievalStrategy], state: CorpusState
) -> ChangeRecord:
    change = state.change(change_id)
    if change is None or change.status != "review_needed" or change.pending is None:
        raise ValueError(f"Change {change_id} is not waiting for review")
    doc = document_from_dict(change.pending)
    _apply(doc, section_hashes(doc), strategies, state)
    state.decide(change_id, "approved")
    return state.change(change_id)


def reject(change_id: int, state: CorpusState) -> ChangeRecord:
    change = state.change(change_id)
    if change is None or change.status != "review_needed":
        raise ValueError(f"Change {change_id} is not waiting for review")
    state.decide(change_id, "rejected")
    return state.change(change_id)


def document_to_dict(doc: SourceDocument) -> dict:
    return {
        "source": doc.source.__dict__ | {"legal_areas": list(doc.source.legal_areas)},
        "language": doc.language,
        "version": doc.version,
        "sections": [
            {
                "heading_path": list(s.heading_path),
                "text": s.text,
                "kind": s.kind,
                "anchor": s.anchor,
            }
            for s in doc.sections
        ],
    }


def document_from_dict(data: dict) -> SourceDocument:
    source = dict(data["source"])
    source["legal_areas"] = tuple(source["legal_areas"])
    return SourceDocument(
        source=SourceInfo(**source),
        language=data["language"],
        version=data["version"],
        sections=tuple(
            Section(tuple(s["heading_path"]), s["text"], s["kind"], s["anchor"])
            for s in data["sections"]
        ),
    )
