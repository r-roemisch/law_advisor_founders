import io
import zipfile

import pytest

from founder_legal_guide.ingestion.adapters.gii import ZIP_URL, GiiAdapter
from founder_legal_guide.ingestion.gii_parser import GiiParseError, parse_gii_xml
from founder_legal_guide.ingestion.registry import SourceEntry

from .ingestion_fakes import FakeFetcher, fixture


@pytest.fixture(scope="module")
def ddg():
    return parse_gii_xml(fixture("gii/ddg.xml.gz"))


def test_one_section_per_paragraph_with_title(ddg):
    p5 = next(s for s in ddg.sections if s.anchor == "p-5")
    assert p5.heading_path == ("DDG", "§ 5 – Allgemeine Informationspflichten")
    lines = p5.text.split("\n")
    assert lines[0].startswith("(1) Diensteanbieter haben")
    assert lines[1].startswith("1. den Namen und die Anschrift")


def test_status_notes_say_when_the_law_was_last_amended(ddg):
    assert ddg.abbreviation == "DDG"
    assert ddg.build_date.isdigit()
    assert any(note.startswith("Stand:") and "geändert" in note for note in ddg.status_notes)


def test_section_ranges_select_articles_and_annexes():
    law = parse_gii_xml(fixture("gii/bgbeg.xml.gz"), ["Art 246-246e", "Anlage 1-3"])
    labels = [s.heading_path[1] for s in law.sections]
    assert labels[0].startswith("Art. 246 – ")
    assert any(label.startswith("Art. 246a § 1 – ") for label in labels)
    assert all(
        label.startswith(("Art. 246", "Anlage 1", "Anlage 2", "Anlage 3")) for label in labels
    )
    assert not any(label.startswith("Art. 245") for label in labels)


def test_invalid_range_is_rejected():
    with pytest.raises(GiiParseError, match="Invalid section range"):
        parse_gii_xml(fixture("gii/ddg.xml.gz"), ["chapter 5"])


def test_adapter_reads_the_zip_and_carries_status_in_the_version():
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("BJNR.xml", fixture("gii/ddg.xml.gz"))
    fetcher = FakeFetcher({(ZIP_URL.format(slug="ddg"), None): archive.getvalue()})
    entry = SourceEntry(
        id="de-ddg",
        title="Digitale-Dienste-Gesetz (DDG)",
        jurisdiction="DE",
        legal_areas=["platform_law"],
        tier=1,
        languages=["de"],
        legal_status="in_force",
        adapter="gii",
        ref={"slug": "ddg"},
        update="auto",
    )
    [doc] = GiiAdapter(fetcher).fetch(entry)
    assert doc.language == "de"
    assert doc.source.url == "https://www.gesetze-im-internet.de/ddg/"
    assert "Stand:" in doc.version
    assert doc.sections[0].heading_path[0] == "DDG"
