import pytest

from founder_legal_guide.ingestion.adapters.web import EDPBAdapter, ReuseNotAllowed, WebPageAdapter
from founder_legal_guide.ingestion.registry import SourceEntry
from founder_legal_guide.ingestion.us_parsers import parse_ecfr, parse_uslm, section_matches
from founder_legal_guide.ingestion.web_parser import HtmlPage, pdf_sections

from .ingestion_fakes import FakeFetcher, fixture


@pytest.mark.parametrize(
    ("number", "ranges", "expected"),
    [
        ("230", ["230"], True),
        ("6503", ["6501-6506"], True),
        ("6507", ["6501-6506"], False),
        ("230.506", ["230.500-230.508"], True),
        ("230.510", ["230.500-230.508"], False),
        ("12181", ["12181-12189"], True),
    ],
)
def test_section_ranges(number, ranges, expected):
    assert section_matches(number, ranges) is expected


def test_us_code_section_230_parses_with_paragraph_markers_inline():
    [section] = parse_uslm(fixture("us/usc47_s230.xml.gz"), 47, ["230"])
    assert section.heading_path == (
        "47 U.S.C.",
        "§ 230 – Protection for private blocking and screening of offensive material",
    )
    assert (
        "(1) Treatment of publisher or speaker\nNo provider or user of an interactive computer service"
        in section.text
    )
    assert not any(line in {"(1)", "(a)", "(A)"} for line in section.text.split("\n"))


def test_ecfr_part_parses_into_sections():
    sections = parse_ecfr(fixture("us/ecfr_t16_p312.xml.gz"), 16, None)
    labels = [s.heading_path[1] for s in sections]
    assert labels[0].startswith("§ 312.1 Scope of regulations")
    assert any(label.startswith("§ 312.2 Definitions") for label in labels)
    only = parse_ecfr(fixture("us/ecfr_t16_p312.xml.gz"), 16, ["312.5"])
    assert [s.heading_path[1][:8] for s in only] == ["§ 312.5 "]


HTML = """<html><head><title>Founding a GmbH</title></head><body>
<nav><a href="/">Home</a> Menu Menu Menu</nav>
<main><h1>Founding a GmbH</h1><p>A GmbH needs share capital of at least 25,000 euros, of which half must be paid in.</p>
<h2>Notary</h2><p>The articles of association must be notarised before registration in the commercial register.</p>
<a href="/files/guide.pdf">Download the guide</a></main>
<footer>Impressum · Datenschutz</footer></body></html>"""


def test_html_extraction_keeps_main_content_split_at_headings():
    page = HtmlPage(HTML)
    sections = page.sections("Gründerplattform")
    assert [s.heading_path for s in sections] == [
        ("Gründerplattform", "Founding a GmbH"),
        ("Gründerplattform", "Notary"),
    ]
    assert "Menu" not in " ".join(s.text for s in sections) and "Impressum" not in sections[-1].text
    assert page.pdf_links == [("/files/guide.pdf", "Download the guide")]


def web_entry(url: str, adapter: str = "web_pinned") -> SourceEntry:
    return SourceEntry(
        id="de-gp-gmbh",
        title="GmbH guide",
        jurisdiction="DE",
        legal_areas=["company_formation"],
        tier=3,
        languages=["de"],
        legal_status="in_force",
        adapter=adapter,
        ref={"url": url},
        update="review",
    )


def test_web_adapter_fingerprints_the_text():
    fetcher = FakeFetcher({("https://example.org/gmbh", None): HTML.encode()})
    [doc] = WebPageAdapter(fetcher).fetch(web_entry("https://example.org/gmbh"))
    assert doc.version.startswith("sha256:") and doc.language == "de"


def test_robots_txt_disallow_is_honoured():
    fetcher = FakeFetcher(
        {
            ("https://example.org/robots.txt", None): b"User-agent: *\nDisallow: /private/",
            ("https://example.org/private/page", None): HTML.encode(),
        }
    )
    with pytest.raises(ReuseNotAllowed, match="robots.txt"):
        WebPageAdapter(fetcher).fetch(web_entry("https://example.org/private/page"))


def test_tdm_reservations_are_honoured():
    tdmrep = FakeFetcher(
        {
            (
                "https://example.org/.well-known/tdmrep.json",
                None,
            ): b'[{"location": "/guides/*", "tdm-reservation": 1}]',
            ("https://example.org/guides/a", None): HTML.encode(),
        }
    )
    with pytest.raises(ReuseNotAllowed, match="TDMRep"):
        WebPageAdapter(tdmrep).fetch(web_entry("https://example.org/guides/a"))
    meta = FakeFetcher(
        {
            ("https://example.org/b", None): HTML.replace(
                "<title>", '<meta name="tdm-reservation" content="1"><title>'
            ).encode()
        }
    )
    with pytest.raises(ReuseNotAllowed, match="meta tag"):
        WebPageAdapter(meta).fetch(web_entry("https://example.org/b"))


def _tiny_pdf(*pages: str) -> bytes:
    """A minimal valid PDF with one text line per page."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", ""]
    kids = []
    for i, text in enumerate(pages):
        page_id, content_id = 4 + 2 * i, 5 + 2 * i
        kids.append(f"{page_id} 0 R")
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objects += [
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>",
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        ]
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>"
    objects.insert(2, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offsets = "%PDF-1.4\n", []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n" + "".join(
        f"{o:010d} 00000 n \n" for o in offsets
    )
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF"
    return out.encode("latin-1")


def test_pdfs_become_one_section_per_page():
    sections = pdf_sections(
        _tiny_pdf(
            "Consent must be freely given, specific and informed.",
            "Withdrawal must be as easy as giving consent.",
        ),
        "EDPB 05/2020",
    )
    assert [s.heading_path for s in sections] == [
        ("EDPB 05/2020", "p. 1"),
        ("EDPB 05/2020", "p. 2"),
    ]
    assert sections[1].text.startswith("Withdrawal must be as easy")


def test_edpb_landing_pages_follow_their_pdf():
    landing = HTML.replace(
        "/files/guide.pdf", "https://www.edpb.europa.eu/system/files/guidelines.pdf"
    )
    fetcher = FakeFetcher(
        {
            ("https://www.edpb.europa.eu/documents/x", None): landing.encode(),
            ("https://www.edpb.europa.eu/system/files/guidelines.pdf", None): _tiny_pdf(
                "Consent must be freely given, specific and informed."
            ),
        }
    )
    [doc] = EDPBAdapter(fetcher).fetch(web_entry("https://www.edpb.europa.eu/documents/x", "edpb"))
    assert doc.sections[0].heading_path[1] == "p. 1"


def test_fetcher_retries_network_errors_but_not_refusals(tmp_path):
    import httpx

    from founder_legal_guide.ingestion.http import Fetcher, FetchError

    calls = {"flaky": 0, "blocked": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.strip("/")
        calls[name] += 1
        if name == "flaky" and calls[name] == 1:
            raise httpx.ConnectError("dns hiccup")
        return httpx.Response(200 if name == "flaky" else 403, content=b"ok")

    fetcher = Fetcher(cache_dir=tmp_path, backoff=0)
    fetcher._client = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetcher.get("https://example.org/flaky") == b"ok" and calls["flaky"] == 2
    with pytest.raises(FetchError, match="403"):
        fetcher.get("https://example.org/blocked")
    assert calls["blocked"] == 1
