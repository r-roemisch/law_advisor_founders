import pytest

from founder_legal_guide.ingestion.adapters import ADAPTERS, SourceAdapter
from founder_legal_guide.ingestion.registry import SourceEntry
from founder_legal_guide.ingestion.state import MemoryVersionStore
from founder_legal_guide.ingestion.update import approve, diff, reject, run_update
from founder_legal_guide.retrieval.strategy import RetrievalStrategy
from founder_legal_guide.retrieval.types import Section, SourceDocument

from .test_retrieval import spec

PUBLISHED: dict[str, SourceDocument] = {}  # what the fake "official site" currently serves
BROKEN: set[str] = set()


@ADAPTERS.register("fake_site")
class FakeSiteAdapter(SourceAdapter):
    def fetch(self, entry):
        if entry.id in BROKEN:
            raise ValueError("site down")
        return [PUBLISHED[entry.id]]


def entry(source_id: str, update: str = "auto") -> SourceEntry:
    return SourceEntry(
        id=source_id,
        title=source_id,
        jurisdiction="EU",
        legal_areas=["data_protection"],
        tier=1,
        languages=["en"],
        legal_status="in_force",
        adapter="fake_site",
        ref={},
        update=update,
    )


def publish(source_id: str, version: str, **articles: str) -> None:
    from .conftest import GDPR

    info = GDPR.__class__(**{**GDPR.__dict__, "id": source_id})
    sections = tuple(Section((source_id, label), text) for label, text in articles.items())
    PUBLISHED[source_id] = SourceDocument(info, "en", sections, version)


@pytest.fixture
def setup(ctx):
    PUBLISHED.clear()
    BROKEN.clear()
    strategy = RetrievalStrategy(spec(), ctx)
    return [strategy], MemoryVersionStore()


def texts(strategy) -> set[str]:
    return {p.text for p, _ in strategy.backend._rows.values()}


def test_first_run_adds_and_indexes_every_source(setup):
    strategies, state = setup
    publish("eu-a", "v1", art1="Consent is required.", art2="Breaches within 72 hours.")
    report = run_update([entry("eu-a")], None, strategies, state)
    [change] = report.changes
    assert (change.kind, change.status, change.summary["added"]) == (
        "added",
        "applied",
        ["art1", "art2"],
    )
    assert texts(strategies[0]) == {"Consent is required.", "Breaches within 72 hours."}
    assert state.current("eu-a", "en").version == "v1"


def test_unchanged_text_produces_no_change_record_even_with_a_new_version(setup):
    strategies, state = setup
    publish("eu-a", "build-1", art1="Same text.")
    run_update([entry("eu-a")], None, strategies, state)
    publish("eu-a", "build-2", art1="Same text.")
    report = run_update([entry("eu-a")], None, strategies, state)
    assert report.changes == [] and report.unchanged == ["eu-a:en"]
    assert state.current("eu-a", "en").version == "build-2"
    assert len(state.changes()) == 1


def test_auto_sources_apply_changes_with_a_section_diff(setup):
    strategies, state = setup
    publish("eu-a", "v1", art1="Old wording.", art2="Unchanged.", art3="Deleted soon.")
    run_update([entry("eu-a")], None, strategies, state)
    publish("eu-a", "v2", art1="New wording.", art2="Unchanged.", art4="Inserted.")
    [change] = run_update([entry("eu-a")], None, strategies, state).changes
    assert change.status == "applied" and (change.old_version, change.new_version) == ("v1", "v2")
    assert change.summary == {"added": ["art4"], "removed": ["art3"], "modified": ["art1"]}
    assert texts(strategies[0]) == {"New wording.", "Unchanged.", "Inserted."}


def test_review_sources_wait_for_approval(setup):
    strategies, state = setup
    publish("eu-page", "sha:1", intro="Original guidance.")
    run_update([entry("eu-page", "review")], None, strategies, state)
    publish("eu-page", "sha:2", intro="Edited guidance.")
    [change] = run_update([entry("eu-page", "review")], None, strategies, state).changes

    assert change.status == "review_needed" and change.pending is not None
    assert texts(strategies[0]) == {"Original guidance."}  # nothing changes before review
    approved = approve(change.id, strategies, state)
    assert approved.status == "approved" and approved.pending is None
    assert texts(strategies[0]) == {"Edited guidance."}
    assert state.current("eu-page", "en").version == "sha:2"
    with pytest.raises(ValueError, match="not waiting for review"):
        approve(change.id, strategies, state)


def test_rejected_review_keeps_the_old_text(setup):
    strategies, state = setup
    publish("eu-page", "sha:1", intro="Original guidance.")
    run_update([entry("eu-page", "review")], None, strategies, state)
    publish("eu-page", "sha:2", intro="Broken scrape: cookie banner text.")
    [change] = run_update([entry("eu-page", "review")], None, strategies, state).changes
    assert reject(change.id, state).status == "rejected"
    assert texts(strategies[0]) == {"Original guidance."}
    assert state.current("eu-page", "en").version == "sha:1"


def test_a_failing_source_is_reported_and_the_run_continues(setup):
    strategies, state = setup
    publish("eu-a", "v1", art1="Text.")
    publish("eu-b", "v1", art1="Other.")
    BROKEN.add("eu-a")
    events = []
    report = run_update([entry("eu-a"), entry("eu-b")], None, strategies, state, events.append)
    assert report.failed == [("eu-a", "site down")]
    assert [c.source_id for c in report.changes] == ["eu-b"]
    assert [e["type"] for e in events] == ["progress", "failed", "progress", "change", "summary"]


def test_diff():
    assert diff({"a": "1", "b": "2"}, {"b": "3", "c": "4"}) == {
        "added": ["c"],
        "removed": ["a"],
        "modified": ["b"],
    }
