import pytest

from founder_legal_guide.ingestion.adapters.eurlex import RESOURCE_URL, SPARQL_URL, EurLexAdapter
from founder_legal_guide.ingestion.eurlex_parser import (
    parse_commission_xhtml,
    parse_eurlex_xhtml,
)
from founder_legal_guide.ingestion.registry import SourceEntry

from .ingestion_fakes import FakeFetcher, fixture, sparql_answer


@pytest.fixture(scope="module")
def gdpr_en():
    return parse_eurlex_xhtml(fixture("eurlex/gdpr_eng.xhtml.gz"), "GDPR", "en")


@pytest.fixture(scope="module")
def ai_act_en():
    return parse_eurlex_xhtml(fixture("eurlex/aiact_eng.xhtml.gz"), "AI Act", "en")


def by_anchor(sections, anchor):
    return next(s for s in sections if s.anchor == anchor)


def test_consolidated_gdpr_has_all_99_articles_with_titles(gdpr_en):
    articles = [s for s in gdpr_en if s.kind == "provision"]
    assert len(articles) == 99
    art33 = by_anchor(gdpr_en, "art_33")
    assert art33.heading_path == (
        "GDPR",
        "Art. 33 – Notification of a personal data breach to the supervisory authority",
    )
    assert art33.text.startswith("1. In the case of a personal data breach")
    assert "not later than 72 hours" in art33.text


def test_list_markers_stay_on_their_item_line(gdpr_en):
    lines = by_anchor(gdpr_en, "art_6").text.split("\n")
    assert "(a) the data subject has given consent" in "\n".join(lines)
    assert not any(line in {"(a)", "1.", "(b)"} for line in lines)


def test_german_version_uses_german_labels():
    sections = parse_eurlex_xhtml(fixture("eurlex/gdpr_deu.xhtml.gz"), "DSGVO", "de")
    art33 = by_anchor(sections, "art_33")
    assert art33.heading_path[0] == "DSGVO"
    assert art33.heading_path[1].startswith("Art. 33 – Meldung")


def test_original_act_provides_all_173_recitals():
    sections = parse_eurlex_xhtml(fixture("eurlex/gdpr_oj_eng.xhtml.gz"), "GDPR", "en")
    recitals = [s for s in sections if s.kind == "recital"]
    assert len(recitals) == 173
    assert recitals[0].heading_path == ("GDPR", "Recital 1")
    assert recitals[0].text.startswith("(1) The protection of natural persons")


def test_annexes_split_into_numbered_points(ai_act_en):
    point4 = by_anchor(ai_act_en, "anx_III.4")
    assert point4.heading_path == (
        "AI Act",
        "Annex III – High-risk AI systems referred to in Article 6(2)",
        "4.",
    )
    assert "(a) AI systems intended to be used for the recruitment" in point4.text


def test_amendment_markers_are_removed(ai_act_en):
    # The consolidated AI Act includes Art. 4a, inserted by Regulation (EU) 2026/1744.
    assert by_anchor(ai_act_en, "art_4a")
    assert not any(m in s.text for s in ai_act_en for m in ("►", "▼", "◄"))


def test_commission_documents_split_at_headings():
    xhtml = b"""<html xmlns="http://www.w3.org/1999/xhtml"><body>
      <p class="Normal">EUROPEAN COMMISSION</p>
      <p class="Titrearticle">Article 3</p><p class="Normal">Regulation (EU) 2016/679 is amended.</p>
      <p class="ManualHeading1">2. Legal basis</p><p class="Normal">Article 114 TFEU.</p>
    </body></html>"""
    sections = parse_commission_xhtml(xhtml, "Omnibus")
    assert [s.heading_path for s in sections] == [
        ("Omnibus",),
        ("Omnibus", "Article 3"),
        ("Omnibus", "2. Legal basis"),
    ]


def entry(**overrides) -> SourceEntry:
    base = {
        "id": "eu-gdpr",
        "title": "Regulation (EU) 2016/679 – General Data Protection Regulation (GDPR)",
        "short_title": {"en": "GDPR", "de": "DSGVO"},
        "jurisdiction": "EU",
        "legal_areas": ["data_protection"],
        "tier": 1,
        "languages": ["en"],
        "legal_status": "in_force",
        "adapter": "eurlex",
        "ref": {"celex": "32016R0679"},
        "update": "auto",
    }
    return SourceEntry(**{**base, **overrides})


def test_adapter_combines_latest_consolidated_articles_with_original_recitals():
    fetcher = FakeFetcher(
        {
            (SPARQL_URL, None): sparql_answer("02016R0679-20160504"),
            (RESOURCE_URL.format(celex="02016R0679-20160504"), "eng"): fixture(
                "eurlex/gdpr_eng.xhtml.gz"
            ),
            (RESOURCE_URL.format(celex="32016R0679"), "eng"): fixture(
                "eurlex/gdpr_oj_eng.xhtml.gz"
            ),
        }
    )
    [doc] = EurLexAdapter(fetcher).fetch(entry())

    assert doc.version == "02016R0679-20160504"
    assert (
        doc.source.url
        == "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02016R0679-20160504"
    )
    kinds = [s.kind for s in doc.sections]
    assert kinds.count("recital") == 173 and kinds.count("provision") == 99
    assert doc.sections[0].heading_path[0] == "GDPR"
    # "Latest version" must never come from the cache.
    sparql = next(r for url, r in fetcher.requests if url == SPARQL_URL)
    assert sparql["cache"] is False


def test_adapter_falls_back_to_original_act_when_consolidation_missing_in_a_language():
    fetcher = FakeFetcher(
        {
            (SPARQL_URL, None): sparql_answer("02016R0679-20160504"),
            (RESOURCE_URL.format(celex="32016R0679"), "eng"): fixture(
                "eurlex/gdpr_oj_eng.xhtml.gz"
            ),
        }
    )
    [doc] = EurLexAdapter(fetcher).fetch(entry())
    assert doc.version == "32016R0679"
    assert len([s for s in doc.sections if s.kind == "provision"]) == 99


def test_adapter_skips_languages_without_any_text():
    fetcher = FakeFetcher({(SPARQL_URL, None): sparql_answer()})
    assert EurLexAdapter(fetcher).fetch(entry(languages=["en", "de"])) == []


def test_proposals_are_never_looked_up_as_consolidated():
    fetcher = FakeFetcher({})
    adapter = EurLexAdapter(fetcher)
    assert adapter.latest_consolidated("52025PC0837") is None
    assert fetcher.requests == []
