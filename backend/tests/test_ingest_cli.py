import io
import zipfile

import pytest

from founder_legal_guide.config import ConfigError
from founder_legal_guide.ingestion.adapters.eurlex import RESOURCE_URL, SPARQL_URL
from founder_legal_guide.ingestion.adapters.gii import ZIP_URL
from founder_legal_guide.ingestion.cli import ingest, main, select_entries
from founder_legal_guide.ingestion.registry import load_registry
from founder_legal_guide.retrieval.chunkers import StructureChunker
from founder_legal_guide.retrieval.strategy import RetrievalStrategy
from founder_legal_guide.settings import REPO_ROOT

from .ingestion_fakes import FakeFetcher, fixture, sparql_answer
from .test_retrieval import spec


@pytest.fixture(scope="module")
def registry():
    return load_registry(REPO_ROOT / "config" / "sources.yaml")


def test_repository_source_registry_loads(registry):
    ids = {e.id for e in registry}
    assert {"eu-gdpr", "eu-ai-act", "de-ddg"} <= ids
    gdpr = next(e for e in registry if e.id == "eu-gdpr")
    assert (gdpr.citation_name("en"), gdpr.citation_name("de")) == ("GDPR", "DSGVO")


def test_selection_filters_and_reports_sources_without_an_adapter(registry):
    chosen, _ = select_entries(registry, jurisdictions=["DE"], tiers=[1])
    assert chosen and all(e.jurisdiction == "DE" and e.tier == 1 for e in chosen)
    assert {e.adapter for e in chosen} == {"gii"}
    future = registry[0].model_copy(update={"id": "eu-future", "adapter": "telepathy"})
    _, unsupported = select_entries([*registry, future], sources=["eu-future"])
    assert unsupported == [("eu-future", "no 'telepathy' adapter yet")]


def test_every_registry_source_has_an_adapter(registry):
    _, unsupported = select_entries(registry)
    assert unsupported == []


def test_unknown_source_ids_are_an_error(registry):
    with pytest.raises(ConfigError, match="Unknown source ids: nope"):
        select_entries(registry, sources=["eu-gdpr", "nope"])


def _fetcher() -> FakeFetcher:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("BJNR.xml", fixture("gii/ddg.xml.gz"))
    return FakeFetcher(
        {
            (SPARQL_URL, None): sparql_answer("02016R0679-20160504"),
            (RESOURCE_URL.format(celex="02016R0679-20160504"), "eng"): fixture(
                "eurlex/gdpr_eng.xhtml.gz"
            ),
            (RESOURCE_URL.format(celex="32016R0679"), "eng"): fixture(
                "eurlex/gdpr_oj_eng.xhtml.gz"
            ),
            (ZIP_URL.format(slug="ddg"), None): archive.getvalue(),
        }
    )


def test_ingest_indexes_every_document_into_every_strategy(registry, ctx):
    entries, _ = select_entries(registry, sources=["eu-gdpr", "de-ddg"])
    entries = [
        e.model_copy(update={"languages": ["en"]}) if e.id == "eu-gdpr" else e for e in entries
    ]
    strategies = [
        RetrievalStrategy(spec(name="A"), ctx),
        RetrievalStrategy(spec(name="B", search="vector"), ctx),
    ]

    report = ingest(entries, _fetcher(), strategies)

    assert not report.failed
    assert {(i, lang) for i, lang, *_ in report.indexed} == {("eu-gdpr", "en"), ("de-ddg", "de")}
    for strategy in strategies:
        assert strategy.backend.count() == report.passages
    hit = strategies[0].retrieve("Meldung personal data breach 72 hours").hits
    assert hit


def test_one_failing_source_does_not_stop_the_run(registry, ctx):
    entries, _ = select_entries(registry, sources=["eu-gdpr", "de-bdsg"])
    entries = [
        e.model_copy(update={"languages": ["en"]}) if e.id == "eu-gdpr" else e for e in entries
    ]
    report = ingest(entries, _fetcher(), [RetrievalStrategy(spec(), ctx)])
    assert [i for i, *_ in report.indexed] == ["eu-gdpr"]
    assert [i for i, _ in report.failed] == ["de-bdsg"]


def test_dry_run_counts_text_without_embedding(registry):
    entries, _ = select_entries(registry, sources=["de-ddg"])
    report = ingest(entries, _fetcher(), None, StructureChunker(None, ""))
    assert report.passages > 30 and report.characters > 10_000


def test_cli_refuses_to_embed_without_a_key(monkeypatch, capsys):
    from founder_legal_guide import settings as settings_module

    monkeypatch.setattr(
        "founder_legal_guide.ingestion.cli.get_settings",
        lambda: settings_module.Settings(openrouter_api_key=""),
    )
    assert main(["--source", "de-ddg"]) == 2
    assert "OPENROUTER_API_KEY is not set" in capsys.readouterr().out
